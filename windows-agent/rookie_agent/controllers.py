"""The human in the loop for the runner: the side panel (through the native host) or the console."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class RemoteController:
    """Asks the GDV through messages and waits for the answer.

    `emit` sends an unsolicited message to the side panel. `decide` is called when the
    panel answers. An emergency stop unblocks a pending question and answers "no".
    """

    def __init__(self, emit: Callable[[dict[str, Any]], None], stop: threading.Event) -> None:
        self._emit = emit
        self._stop = stop
        self._answer: bool | None = None
        self._cv = threading.Condition()
        self.pending: str | None = None  # "approve" or "review" while a question is open

    def _ask(self, kind: str, step: dict[str, Any], index: int, total: int) -> bool:
        with self._cv:
            self._answer, self.pending = None, kind
        # The panel shows the step's name and risk, never the values typed.
        self._emit(
            {
                "event": "waiting",
                "kind": kind,
                "step_id": step["id"],
                "label": (step.get("target") or {}).get("label"),
                "risk": step["risk"],
                "index": index,
                "total": total,
            }
        )
        with self._cv:
            while self._answer is None and not self._stop.is_set():
                self._cv.wait(0.1)
            answer = bool(self._answer) and not self._stop.is_set()
            self.pending = None
        return answer

    def approve(self, step: dict[str, Any], index: int, total: int) -> bool:
        return self._ask("approve", step, index, total)

    def review(self, step: dict[str, Any], index: int, total: int) -> bool:
        return self._ask("review", step, index, total)

    def decide(self, approve: bool) -> bool:
        """The GDV answered. Returns False when there was no open question."""
        with self._cv:
            if self.pending is None:
                return False
            self._answer = approve
            self._cv.notify_all()
        return True

    def progress(self, step_id: str, status: str, detail: str) -> None:
        self._emit({"event": "progress", "step_id": step_id, "status": status, "detail": detail})


class ConsoleController:
    """Asks on the console. Ctrl+C is the emergency stop."""

    def __init__(self, ask: Callable[[str], str] = input, say: Callable[[str], None] = print) -> None:
        self._ask, self._say = ask, say

    def _confirm(self, prompt: str) -> bool:
        return self._ask(prompt + " [c = có / k = không]: ").strip().lower() in ("c", "co", "có", "y", "yes")

    @staticmethod
    def _name(step: dict[str, Any]) -> str:
        label = (step.get("target") or {}).get("label") or step["id"]
        return f"{label} (rủi ro: {step['risk']})"

    def approve(self, step: dict[str, Any], index: int, total: int) -> bool:
        return self._confirm(f"Bước {index + 1}/{total} cần DUYỆT trước khi chạy: {self._name(step)}. Duyệt?")

    def review(self, step: dict[str, Any], index: int, total: int) -> bool:
        return self._confirm(f"Bước {index + 1}/{total} đã chạy xong: {self._name(step)}. Xem kết quả rồi, đi tiếp?")

    def progress(self, step_id: str, status: str, detail: str) -> None:
        self._say(f"  {step_id}: {status}" + (f" ({detail})" if detail else ""))
