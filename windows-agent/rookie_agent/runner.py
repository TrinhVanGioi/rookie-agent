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

SUPPORTED_ACTIONS = frozenset({"click", "fill", "select", "submit", "read_value", "wait_for", "read_fields"})
RISKS = frozenset({"read", "write", "money"})
MODES = frozenset({"auto", "review", "approve"})
MOCK_WINDOW_MARKERS = ("Mock TPSS", "Quầy mẫu")   # the lab counter (mock-site/touchpoint.py) is a mock too
LOGIN_CHECK_SECONDS = 3.0   # how long to look for the sign-in page before taking the teller as signed in already
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*)\}")   # {acct}, or {kq.grid.1.so_tk}: a value read from the screen
# A step that works on a password or OTP field is the teller's own: the agent never types there, so it never sends there either.
_SECRET_TARGET = re.compile(r"pass|pwd|pw(?![a-z])|otp|secret|mat.?khau|(?<![a-z])pin(?![a-z])", re.IGNORECASE)


def is_manual(step: dict[str, Any]) -> bool:
    """Signing in: pressing Enter in a password field. The person does it; the agent waits."""
    selectors = (step.get("target") or {}).get("selectors") or []
    return step.get("action") == "submit" and any(_SECRET_TARGET.search(selector) for selector in selectors)


class ElementNotFound(LookupError):
    """No selector of the step matches a component on screen."""


class NeedsHelp(Exception):
    """The step cannot go on without a person (two elements alike, a locked field, an entry that is not in the list, a value the
    page did not keep). `message` says what is wrong in plain words and never holds a value that was typed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


REPAIRABLE = frozenset({"ambiguous", "low_confidence"})   # the element is unclear: the teller may point at it (task 6.2)
POST_TIMEOUT = 8.0   # task 12.2: how long the screen may take to show what a step of a version 4 flow is expected to show
POST_POLL = 0.3
KIND_WORDS = {"table": "bảng", "field": "ô", "message": "thông báo"}


class WorkflowRefused(ValueError):
    """The workflow breaks a hard rule or cannot be run by this runner. Nothing was executed."""


class Driver(Protocol):
    """What the runner needs from the application under control."""

    def window_title(self) -> str: ...
    def exists(self, selectors: list[str]) -> bool: ...
    def click(self, selectors: list[str]) -> None: ...
    def fill(self, selectors: list[str], value: str) -> None: ...
    def select(self, selectors: list[str], value: str) -> None: ...
    def submit(self, selectors: list[str]) -> None: ...
    def read_value(self, selectors: list[str]) -> str: ...
    def read_screen(self) -> dict[str, str]: ...


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


def resolve(text: str, values: dict[str, Any]) -> str:
    """Put the values in a step's text. `{acct}` is an input or a value read earlier; `{kq.grid.1.so_tk}` is one value of a screen that a
    `read_fields` step kept under the name `kq`. A name that is not there is a question for the teller, never a guess."""
    def put(match: re.Match[str]) -> str:
        name = match.group(1)
        if "." not in name:
            return str(values[name])
        base, path = name.split(".", 1)
        data = values.get(base)
        if not isinstance(data, dict):
            raise NeedsHelp("no_data", f"«{base}» chưa được đọc từ màn hình ở bước nào trước đó.")
        try:
            return data[path]
        except KeyError:
            raise NeedsHelp("no_data", f"Màn hình không có dữ liệu «{name}» (hoặc có ở nhiều chỗ nên agent không biết lấy chỗ nào).") from None
    return _PLACEHOLDER.sub(put, text)


def required_inputs(workflow: dict[str, Any]) -> list[str]:
    """Names the GDV must supply: declared inputs without a default that a step uses."""
    produced: set[str] = set()
    needed: list[str] = []
    defaults = {item["name"] for item in workflow.get("inputs", []) if item.get("default") is not None or item.get("required") is False}
    for step in workflow.get("steps", []):
        for name in placeholders(step.get("value")):
            name = name.split(".", 1)[0]
            if name not in produced and name not in defaults and name not in needed:
                needed.append(name)
        if step.get("save_as"):
            produced.add(step["save_as"])
    return needed


def check_workflow(workflow: dict[str, Any], inputs: dict[str, str], sandbox: bool, engine: str = "java", versions: tuple[int, ...] = (1,)) -> None:
    """Refuse anything that must not run. Raises WorkflowRefused with every reason. `engine` and `versions` say what this runner
    drives: the Java runner takes (java, 1), the Internet Explorer runner (ie, 2 or 3)."""
    problems: list[str] = []
    if workflow.get("schema_version") not in versions:
        problems.append("schema_version không được hỗ trợ")
    if workflow.get("engine") != engine:
        problems.append(f"workflow không thuộc hướng {'Java' if engine == 'java' else engine}")
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
        if action == "read_fields" and engine != "ie":
            problems.append(f"bước {step_id}: read_fields chỉ có ở hướng Internet Explorer")
        if action in SUPPORTED_ACTIONS and action != "read_fields" and not (step.get("target") or {}).get("selectors"):
            problems.append(f"bước {step_id}: thiếu target")
        if action in ("fill", "select") and step.get("value") is None:
            problems.append(f"bước {step_id}: thiếu value")
        if action in ("read_value", "read_fields") and not step.get("save_as"):
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
    values: dict[str, Any] | None = None,
    engine: str = "java",
    versions: tuple[int, ...] = (1,),
    allow_write_on_real: bool = False,
    element_timeout: float = 10.0,
    settle: float = 0.15,
    sleep: Callable[[float], None] = time.sleep,
    download_steps: dict[str, str] | None = None,
    post_timeout: float = POST_TIMEOUT,
) -> dict[str, Any]:
    """Execute the workflow. Returns `{"status", "message", "steps": [{"id", "status", "detail"}]}`.

    `download_steps` {step id: name}: steps whose press makes the page answer a file (a report as PDF). IE then shows its own Open/Save bar,
    which the agent cannot press reliably: the run stops right after the press and tells the teller to press Lưu (docs/design.md 6.4.11).

    status: finished, stopped (Dừng khẩn), rejected (GDV không duyệt), needs_help
    (không tìm thấy phần tử), refused (vi phạm quy tắc), failed (lỗi khi thao tác).
    """
    stop = stop or threading.Event()
    done: list[dict[str, str]] = []
    repairs: list[dict[str, Any]] = []   # task 6.2: the element the teller pointed at for a step the agent could not find (selectors only)
    decisions: list[dict[str, Any]] = []  # task 12.2: every adaptation decision (what was seen, how sorted, what done); names only
    # Task 12.2 (SADPT): a version 4 flow is checked step by step against its postconditions, when the driver can read the screen.
    adaptive = engine == "ie" and int(workflow.get("schema_version") or 0) >= 4 and callable(getattr(driver, "look", None))
    known_frames = _known_frames(workflow) if adaptive else set()

    def result(status: str, message: str) -> dict[str, Any]:
        out = {"status": status, "message": message, "steps": done}
        if repairs:
            out["repairs"] = repairs
        if decisions:
            out["decisions"] = decisions
        return out

    def postcheck(step: dict[str, Any], before: list[dict[str, Any]]) -> dict[str, Any]:
        """Look at the screen until it shows what the step is expected to show, or until something never seen comes up (twice in a row:
        a page still drawing is not taken for news), or until the time is up."""
        from rookie_agent.adaptive import verify
        from rookie_agent.ie import read

        appears = (step.get("expect") or {}).get("appears") or []
        place = next((i for i, s in enumerate(steps) if s is step), -1)
        following = steps[place + 1] if 0 <= place < len(steps) - 1 else {}
        answered_in = {sel[len("frame="):].split("|", 1)[0] for sel in (following.get("target") or {}).get("selectors") or []
                       if sel.startswith("frame=") and "|" in sel}
        deadline = time.monotonic() + post_timeout
        previous: list[dict[str, Any]] | None = None
        volatile: set[Any] = set()
        last = ""
        while True:
            if stop.is_set():
                raise _Stopped()
            now = _look(driver)
            if now is None:                    # the screen cannot be read now: nothing to say either way
                return {"state": "ok", "missing": [], "unexpected": []}
            if previous is not None:
                volatile |= read.volatile(previous, now)
            verdict = verify.check(appears, before, now, known_frames=known_frames, volatile=volatile, answered_in=answered_in)
            if verdict["state"] == "ok" or (verdict["state"] == "unexpected" and last == "unexpected") or time.monotonic() >= deadline:
                return verdict
            last, previous = verdict["state"], now
            sleep(POST_POLL)

    def repair(step: dict[str, Any], selectors: list[str], want: str) -> dict[str, Any] | None:
        """Task 6.2: up to 3 look-alikes are marked in the page (nothing is pressed) and the teller says which one is meant, or none."""
        if sandbox or engine != "ie" or not hasattr(driver, "suggest") or not hasattr(controller, "pick"):
            return None
        candidates = driver.suggest(selectors, want)[:3]
        if not candidates:
            return None
        driver.mark(candidates)
        try:
            choice = controller.pick(step, candidates)
        finally:
            driver.unmark()
        if choice is None or stop.is_set() or not 0 <= choice < len(candidates):
            return None
        chosen = candidates[choice]
        repairs.append({"step_id": step["id"], "selectors": list(chosen["selectors"])})
        return chosen

    def reresolve(step: dict[str, Any], selectors: list[str], want: str) -> dict[str, Any] | None:
        """Task 12.3: a read step of a version 4 flow allowed to re-resolve (`adapt.reresolve`) takes the one look-alike with strong
        enough evidence (`locate.auto_pick`), without asking and without marking the page. The screen is checked after it."""
        if not adaptive or step["risk"] != "read" or not (step.get("adapt") or {}).get("reresolve") or not hasattr(driver, "suggest"):
            return None
        from rookie_agent.ie import locate

        candidates = driver.suggest(selectors, want)[:3]
        pick = locate.auto_pick(step.get("target") or {}, candidates)
        if pick is None:
            return None
        return {**candidates[pick["index"]], "signals": pick["signals"]}

    try:
        check_workflow(workflow, inputs, sandbox, engine, versions)
    except WorkflowRefused as error:
        return result("refused", str(error))
    if sandbox and not _is_mock(driver.window_title()):
        return result("refused", "Chế độ thử chỉ chạy trên cửa sổ mock.")

    if values is None:
        values = {}
    values.update({item["name"]: str(item["default"]) for item in workflow.get("inputs", []) if item.get("default") is not None})
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
            except NeedsHelp as locked:
                # a button the page unlocks a moment after the field is filled (it checks the value first): wait, never unlock it
                if locked.code != "disabled" or time.monotonic() >= deadline:
                    raise
                sleep(0.2)

    # Already signed in: a flow recorded from the sign-in page starts with the sign-in block (the steps up to the teller's own
    # Enter in the password). When the first of them is not on screen, the whole block is skipped instead of stopping, and a
    # click right after it (an «OK») is done only if it shows up. Nothing is guessed: a later step that is missing still stops.
    signed_in_skip: set[int] = set()
    maybe_click: set[int] = set()
    login_end = next((i for i, s in enumerate(steps) if engine == "ie" and is_manual(s)), -1)
    if login_end >= 0 and not sandbox:
        first = (steps[0].get("target") or {}).get("selectors") or []
        if first and not _wait_for_presence(driver, first, LOGIN_CHECK_SECONDS, stop, sleep):
            signed_in_skip = set(range(login_end + 1))
            if login_end + 1 < total and steps[login_end + 1]["action"] == "click":
                maybe_click.add(login_end + 1)

    for index, step in enumerate(steps):
        if stop.is_set():
            return result("stopped", f"Dừng khẩn trước bước {step['id']}.")
        if index in signed_in_skip:
            note(step, "skipped", "đã đăng nhập sẵn")
            continue
        if index in maybe_click:
            if not _wait_for_presence(driver, (step.get("target") or {}).get("selectors") or [], LOGIN_CHECK_SECONDS, stop, sleep):
                note(step, "skipped", "đã đăng nhập sẵn")
                continue
        selectors = (step.get("target") or {}).get("selectors") or []
        action = step["action"]

        if step["risk"] == "money" and not _is_mock(driver.window_title()):
            note(step, "refused", "bước money chỉ được chạy trên mock")
            return result("refused", f"Bước {step['id']} là bước tiền: PoC chỉ cho chạy trên mock.")

        if engine == "ie" and step["risk"] == "write" and not allow_write_on_real and not _is_mock(driver.window_title()):
            note(step, "refused", "bước ghi chỉ được chạy trên trang mock")
            return result("refused", f"Bước {step['id']} ghi dữ liệu: trên UAT hay hệ thống thật chỉ chạy các bước chỉ xem; bước ghi chỉ chạy trên trang mock (người phụ trách có thể bật riêng).")

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

        if engine == "ie" and is_manual(step):
            # sign in: the teller types the password and presses Enter; the agent waits and goes on when told
            controller.progress(step["id"], "waiting_review", "manual")
            proceed = controller.review({**step, "manual": True}, index, total)
            if stop.is_set():
                note(step, "stopped", "Dừng khẩn")
                return result("stopped", f"Dừng khẩn ở bước {step['id']}.")
            if not proceed:
                note(step, "rejected", "GDV dừng ở bước đăng nhập")
                return result("rejected", f"GDV dừng ở bước {step['id']} (đăng nhập).")
            note(step, "done", "manual")
            continue

        optional = step.get("optional") or {}
        if optional.get("mode") == "if_different":
            # a list or a field the teller may leave empty: empty means "keep what the screen already shows"
            names = placeholders(step.get("value"))
            if any(not values.get(name) for name in names if "." not in name):
                note(step, "skipped", "để trống: giữ giá trị đang có trên màn hình")
                continue
        elif optional.get("mode") == "if_present":
            waited = _wait_for_presence(driver, selectors, optional.get("wait_ms", 2000) / 1000.0, stop, sleep)
            if stop.is_set():
                note(step, "stopped", "Dừng khẩn")
                return result("stopped", f"Dừng khẩn ở bước {step['id']}.")
            if not waited:
                note(step, "skipped", "không có trên màn hình")
                continue

        controller.progress(step["id"], "running", "")

        def perform(sel: list[str]) -> None:
            if action == "click":
                wait_until_found(step, lambda: driver.click(sel))
            elif action == "fill":
                value = resolve(step["value"], values)
                wait_until_found(step, lambda: driver.fill(sel, value))
            elif action == "select":
                value = resolve(step["value"], values)
                wait_until_found(step, lambda: driver.select(sel, value))
            elif action == "submit":
                wait_until_found(step, lambda: driver.submit(sel))
            elif action == "read_fields":
                values[step["save_as"]] = driver.read_screen()      # the whole screen as data; it stays in this process
            elif action == "read_value":
                values[step["save_as"]] = wait_until_found(step, lambda: driver.read_value(sel))
            elif action == "wait_for":
                wait_until_found(step, lambda: _require(driver.exists(sel)))

        before = _look(driver) if adaptive else None
        watch = adaptive and (bool(step.get("expect")) or action in ("click", "submit"))
        found_again: dict[str, Any] | None = None
        try:
            try:
                perform(selectors)
            except (NeedsHelp, ElementNotFound) as missing:
                if isinstance(missing, NeedsHelp) and missing.code not in REPAIRABLE:
                    raise
                want = "field" if action in ("fill", "select", "submit") else "press" if action == "click" else "any"
                saw = missing.code if isinstance(missing, NeedsHelp) else "not_found"
                found_again = reresolve(step, selectors, want)
                chosen = found_again or repair(step, selectors, want)
                if found_again is None and adaptive:
                    # task 12.8: a screen change the agent did not recover by itself is still a decision (it asked, or it stopped)
                    from rookie_agent.adaptive import classify

                    decisions.append(classify.decision(step["id"], saw, "ask", "stopped" if chosen is None else "asked", risk=step.get("risk")))
                if chosen is None:
                    raise
                if step["risk"] != "read":
                    # rule of 6.3: a corrected write or money step runs only after the corrected agent is approved again
                    note(step, "needs_help", "đã nhớ ô GDV chọn, chờ Duyệt lại")
                    return result("needs_help", f"Bước {step['id']}: đã nhớ ô bạn chọn. Bước ghi dữ liệu hoặc tiền chỉ chạy sau khi bản sửa của agent được Duyệt lại.")
                perform([chosen["src"]])
                watch = watch or found_again is not None        # an element found again by the agent is always checked after
            if watch and before is not None:
                from rookie_agent.adaptive import classify

                verdict = postcheck(step, before)
                if verdict["state"] != "ok":
                    if found_again is not None:      # the element it found is not trusted: no draft is made from it
                        decisions.append(classify.decision(step["id"], saw, "reresolve", "postcheck_failed", {"how": "+".join(found_again["signals"])}, risk=step.get("risk")))
                    where = (verdict["unexpected"] or verdict["missing"])[0]
                    decisions.append(classify.decision(step["id"], verdict["state"], "ask", "stopped", where, risk=step.get("risk")))
                    note(step, "needs_help", verdict["state"])
                    out = result("needs_help", _post_message(step, verdict))
                    if verdict["state"] == "unexpected":
                        out["teach_after"] = step["id"]        # task 12.5: «Dạy lại đoạn này» starts right here
                    return out
            if found_again is not None:
                from rookie_agent.adaptive import classify

                repairs.append({"step_id": step["id"], "selectors": list(found_again["selectors"]), "auto": True})
                decisions.append(classify.decision(step["id"], saw, "reresolve", "done", {"how": "+".join(found_again["signals"])}, risk=step.get("risk")))
        except _Stopped:
            note(step, "stopped", "Dừng khẩn")
            return result("stopped", f"Dừng khẩn ở bước {step['id']}.")
        except NeedsHelp as error:
            note(step, "needs_help", error.code)
            return result("needs_help", f"Bước {step['id']}: {error.message} Agent dừng để hỏi bạn.")
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

        if step["id"] in (download_steps or {}):
            note(step, "needs_help", "tải file về: bấm Lưu trên thanh của IE")
            return result("needs_help", f"Bước «{download_steps[step['id']]}» tải một file về. IE hiện thanh Mở/Lưu của riêng nó mà agent không bấm được chắc chắn: "
                                        "hãy bấm Lưu trên thanh đó. Muốn agent tự lưu file vào thư mục Rookie, dùng «Chạy mô phỏng».")
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


def _known_frames(workflow: dict[str, Any]) -> set[str]:
    """The frames the flow was recorded in: those of its selectors and of its postconditions. A frame outside them that comes up
    after a step is a dialog the recordings never had."""
    frames = {"top"}
    for step in workflow.get("steps") or []:
        for selector in (step.get("target") or {}).get("selectors") or []:
            if selector.startswith("frame=") and "|" in selector:
                frames.add(selector[len("frame="):].split("|", 1)[0])
        for item in (step.get("expect") or {}).get("appears") or []:
            frames.add(str(item.get("frame")))
    return frames


def _look(driver: Any) -> list[dict[str, Any]] | None:
    """The screen as frames (values in memory only), or None when it cannot be read right now."""
    try:
        return driver.look()
    except Exception:  # noqa: BLE001  a page that is changing may not answer; the check is then skipped, never guessed
        return None


def _post_message(step: dict[str, Any], verdict: dict[str, Any]) -> str:
    """In plain words, without a value: what came up, or what did not, after the step."""
    name = step.get("intent") or (step.get("target") or {}).get("label") or step["id"]
    if verdict["state"] == "unexpected":
        item = verdict["unexpected"][0]
        what = "một hộp thoại" if item["kind"] == "frame" else "một thông báo"
        return (f"Sau bước «{name}», màn hình hiện {what} chưa từng thấy lúc học (khung «{item['frame']}»). Có thể quy trình đã đổi: "
                "agent dừng ở đây và không bấm gì trong đó. Bạn xem màn hình; nếu đây là bước mới, hãy dạy lại đoạn này.")
    wanted = ", ".join(f"{KIND_WORDS.get(m['kind'], m['kind'])} «{m['name']}»" if m["name"] else f"một {KIND_WORDS.get(m['kind'], m['kind'])}"
                       for m in verdict["missing"][:3])
    return f"Sau bước «{name}», màn hình chưa hiện {wanted} như lúc học. Agent dừng để bạn xem màn hình."


def _require(found: bool) -> None:
    if not found:
        raise ElementNotFound()


def _wait_for_presence(driver: Driver, selectors: list[str], seconds: float, stop: threading.Event, sleep: Callable[[float], None]) -> bool:
    """True when the element shows up within `seconds`. Looks at least once; never waits past the emergency stop."""
    deadline = time.monotonic() + seconds
    while True:
        if driver.exists(selectors):
            return True
        if stop.is_set() or time.monotonic() >= deadline:
            return False
        sleep(0.1)
