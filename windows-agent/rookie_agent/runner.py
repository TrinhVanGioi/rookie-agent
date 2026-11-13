"""Run a learned workflow on a Java application, one controlled step at a time (docs/design.md 6).

The runner does not know Java Access Bridge: it drives a `Driver` and asks a
`Controller` (the GDV, through the side panel or the console) at the control
points. Rules enforced here, whatever the server or the workflow says:

- a `money` step is never `auto`, a `write` step is always `approve`;
- outside the sandbox only an `approved` workflow runs;
- a `money` step runs only on a mock window (PoC: synthetic data only);
- an element that cannot be found stops the run and asks the GDV; nothing is guessed;
- input values stay in this process and never appear in results or logs.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

SUPPORTED_ACTIONS = frozenset({"click", "fill", "select", "read_value", "wait_for"})
RISKS = frozenset({"read", "write", "money"})
MODES = frozenset({"auto", "review", "approve"})
MOCK_WINDOW_MARKERS = ("Mock TPSS",)
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")


class ElementNotFound(LookupError):
    """No selector of the step matches a component on screen."""


class WorkflowRefused(ValueError):
    """The workflow breaks a hard rule or cannot be run by this runner. Nothing was executed."""


class Driver(Protocol):
    """What the runner needs from the application under control."""

    def window_title(self) -> str: ...
    def exists(self, selectors: list[str]) -> bool: ...
    def click(self, selectors: list[str]) -> None: ...
    def fill(self, selectors: list[str], value: str) -> None: ...
    def select(self, selectors: list[str], value: str) -> None: ...
    def read_value(self, selectors: list[str]) -> str: ...


class Controller(Protocol):
    """The human in the loop. `approve` and `review` block until the GDV answers."""

    def approve(self, step: dict[str, Any], index: int, total: int) -> bool: ...
    def review(self, step: dict[str, Any], index: int, total: int) -> bool: ...
    def progress(self, step_id: str, status: str, detail: str) -> None: ...


class AutoController:
    """Sandbox only: grants every approval and records what happened."""

    def __init__(self) -> None:
        self.log: list[tuple[str, str, str]] = []

    def approve(self, step: dict[str, Any], index: int, total: int) -> bool:
        return True

    def review(self, step: dict[str, Any], index: int, total: int) -> bool:
        return True

    def progress(self, step_id: str, status: str, detail: str) -> None:
        self.log.append((step_id, status, detail))


def placeholders(text: str | None) -> list[str]:
    return _PLACEHOLDER.findall(text or "")


def required_inputs(workflow: dict[str, Any]) -> list[str]:
    """Names the GDV must supply: declared inputs without a default that a step uses."""
    produced: set[str] = set()
    needed: list[str] = []
    defaults = {item["name"] for item in workflow.get("inputs", []) if item.get("default") is not None}
    for step in workflow.get("steps", []):
        for name in placeholders(step.get("value")):
            if name not in produced and name not in defaults and name not in needed:
                needed.append(name)
        if step.get("save_as"):
            produced.add(step["save_as"])
    return needed


def check_workflow(workflow: dict[str, Any], inputs: dict[str, str], sandbox: bool) -> None:
    """Refuse anything that must not run. Raises WorkflowRefused with every reason."""
    problems: list[str] = []
    if workflow.get("schema_version") != 1:
        problems.append("schema_version không được hỗ trợ")
    if workflow.get("engine") != "java":
        problems.append("workflow không thuộc hướng Java")
    if not sandbox and workflow.get("status") != "approved":
        problems.append("workflow chưa được duyệt (chỉ chạy bản approved)")
    steps = workflow.get("steps") or []
    if not steps:
        problems.append("workflow không có bước nào")
    for step in steps:
        step_id = step.get("id", "?")
        action, risk, mode = step.get("action"), step.get("risk"), step.get("mode")
        if action not in SUPPORTED_ACTIONS:
            problems.append(f"bước {step_id}: action {action!r} chưa hỗ trợ ở hướng Java")
        if risk not in RISKS or mode not in MODES:
            problems.append(f"bước {step_id}: risk hoặc mode không hợp lệ")
        if risk == "money" and mode == "auto":
            problems.append(f"bước {step_id}: bước money không được là auto")
        if risk == "write" and mode != "approve":
            problems.append(f"bước {step_id}: bước write phải là approve")
        if action in SUPPORTED_ACTIONS and not (step.get("target") or {}).get("selectors"):
            problems.append(f"bước {step_id}: thiếu target")
        if action in ("fill", "select") and step.get("value") is None:
            problems.append(f"bước {step_id}: thiếu value")
        if action == "read_value" and not step.get("save_as"):
            problems.append(f"bước {step_id}: thiếu save_as")
    missing = [name for name in required_inputs(workflow) if name not in inputs]
    if missing:
        problems.append("thiếu giá trị đầu vào: " + ", ".join(missing))
    if problems:
        raise WorkflowRefused("; ".join(problems))


def _is_mock(title: str) -> bool:
    return any(marker in title for marker in MOCK_WINDOW_MARKERS)


def run_workflow(
    workflow: dict[str, Any],
    inputs: dict[str, str],
    driver: Driver,
    controller: Controller,
    stop: threading.Event | None = None,
    sandbox: bool = False,
    element_timeout: float = 10.0,
    settle: float = 0.15,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Execute the workflow. Returns `{"status", "message", "steps": [{"id", "status", "detail"}]}`.

    status: finished, stopped (Dừng khẩn), rejected (GDV không duyệt), needs_help
    (không tìm thấy phần tử), refused (vi phạm quy tắc), failed (lỗi khi thao tác).
    """
    stop = stop or threading.Event()
    done: list[dict[str, str]] = []

    def result(status: str, message: str) -> dict[str, Any]:
        return {"status": status, "message": message, "steps": done}

    try:
        check_workflow(workflow, inputs, sandbox)
    except WorkflowRefused as error:
        return result("refused", str(error))
    if sandbox and not _is_mock(driver.window_title()):
        return result("refused", "Chế độ thử chỉ chạy trên cửa sổ mock.")

    values: dict[str, str] = {
        item["name"]: str(item["default"]) for item in workflow.get("inputs", []) if item.get("default") is not None
    }
    values.update(inputs)
    steps = workflow["steps"]
    total = len(steps)

    def note(step: dict[str, Any], status: str, detail: str = "") -> None:
        done.append({"id": step["id"], "status": status, "detail": detail})
        controller.progress(step["id"], status, detail)

    def wait_until_found(step: dict[str, Any], act: Callable[[], Any]) -> Any:
        """Retry while the element is missing; give up at the timeout or on Dừng khẩn."""
        deadline = time.monotonic() + element_timeout
        while True:
            if stop.is_set():
                raise _Stopped()
            try:
                return act()
            except ElementNotFound:
                if time.monotonic() >= deadline:
                    raise
                sleep(0.2)

    for index, step in enumerate(steps):
        if stop.is_set():
            return result("stopped", f"Dừng khẩn trước bước {step['id']}.")
        selectors = step["target"]["selectors"]
        action = step["action"]

        if step["risk"] == "money" and not _is_mock(driver.window_title()):
            note(step, "refused", "bước money chỉ được chạy trên mock")
            return result("refused", f"Bước {step['id']} là bước tiền: PoC chỉ cho chạy trên mock.")

        if step["mode"] == "approve":
            if sandbox:
                controller.progress(step["id"], "auto_approved", "chế độ thử")
            else:
                controller.progress(step["id"], "waiting_approval", "")
                approved = controller.approve(step, index, total)
                if stop.is_set():  # Dừng khẩn wins over any answer, including "no"
                    note(step, "stopped", "Dừng khẩn")
                    return result("stopped", f"Dừng khẩn trước bước {step['id']}.")
                if not approved:
                    note(step, "rejected", "GDV không duyệt")
                    return result("rejected", f"GDV không duyệt bước {step['id']}.")

        controller.progress(step["id"], "running", "")
        try:
            if action == "click":
                wait_until_found(step, lambda: driver.click(selectors))
            elif action == "fill":
                value = _PLACEHOLDER.sub(lambda match: values[match.group(1)], step["value"])
                wait_until_found(step, lambda: driver.fill(selectors, value))
            elif action == "select":
                value = _PLACEHOLDER.sub(lambda match: values[match.group(1)], step["value"])
                wait_until_found(step, lambda: driver.select(selectors, value))
            elif action == "read_value":
                values[step["save_as"]] = wait_until_found(step, lambda: driver.read_value(selectors))
            elif action == "wait_for":
                wait_until_found(step, lambda: _require(driver.exists(selectors)))
        except _Stopped:
            note(step, "stopped", "Dừng khẩn")
            return result("stopped", f"Dừng khẩn ở bước {step['id']}.")
        except ElementNotFound:
            note(step, "needs_help", "không tìm thấy phần tử")
            return result(
                "needs_help",
                f"Không tìm thấy phần tử của bước {step['id']} sau {element_timeout:g} giây. Agent dừng để hỏi GDV.",
            )
        except Exception as error:
            # The message of a driver error describes the component, never the value.
            note(step, "failed", type(error).__name__)
            return result("failed", f"Lỗi ở bước {step['id']}: {error}")

        note(step, "done")
        sleep(settle)

        if step["mode"] == "review" and not sandbox:
            controller.progress(step["id"], "waiting_review", "")
            proceed = controller.review(step, index, total)
            if stop.is_set():
                return result("stopped", f"Dừng khẩn sau bước {step['id']}.")
            if not proceed:
                return result("rejected", f"GDV dừng sau khi xem kết quả bước {step['id']}.")

    return result("finished", f"Đã chạy xong {total} bước.")


class _Stopped(Exception):
    pass


def _require(found: bool) -> None:
    if not found:
        raise ElementNotFound()
