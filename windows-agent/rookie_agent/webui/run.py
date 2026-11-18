"""Running a learned flow from the page of this PC (tasks 4.42 to 4.45): the person in the loop, and what is kept of a run.

`WebController` is the person's side of `runner.run_workflow`: it holds the question open until the page answers it, and builds the
card the person decides on from what is on this PC (what will be sent, what the screen shows). Values appear on that card because
the person at this PC typed them and sees this PC; they are never part of the result and never written anywhere. A question has a
random id and only that id can answer it, so an old click cannot approve a new step.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
ASK_LOCK_SECONDS = 0.8   # the page keeps the Duyệt button locked this long after a question appears (a double click must not answer the next one)


class WebController:
    def __init__(self, stop: threading.Event, values: dict[str, str], see: Callable[[], str]) -> None:
        self._stop = stop
        self._values = values
        self._see = see
        self._cv = threading.Condition()
        self._answer: bool | None = None
        self._choice: int | None = None
        self.ask: dict[str, Any] | None = None     # the open question, or None
        self.steps: list[dict[str, str]] = []      # id, status, detail: never a value
        self.decisions: list[dict[str, Any]] = []  # who answered what: the step, the kind of question, the risk, yes or no
        self.context: dict[str, Any] = {}          # extra fields of every card (the twin: «BẢN SAO», the stage and its role)
        self.details: dict[str, dict[str, Any]] = {}   # task 7.5: per step, what a simulated run sent and got back; memory only, never audited

    def show(self, step_id: str, shown: dict[str, Any]) -> None:
        self.details[step_id] = shown

    # ---- the questions -------------------------------------------------------------

    def _resolve(self, step: dict[str, Any]) -> str | None:
        """What this step will send, from the typed inputs and from what earlier steps read on the screen (one store, shared with the run)."""
        if step.get("action") in ("fill", "select") and step.get("value") is not None:
            from rookie_agent.runner import NeedsHelp, resolve

            try:
                return resolve(step["value"], self._values)
            except (NeedsHelp, KeyError):
                return "(chưa có giá trị: bước trước chưa đọc được)"
        return None

    def _ask(self, kind: str, step: dict[str, Any], index: int, total: int) -> bool:
        try:
            seen = self._see()
        except Exception:  # noqa: BLE001  the card is a help: a screen that cannot be read must not stop the question
            seen = "không đọc được màn hình lúc này"
        card = {"id": uuid.uuid4().hex, "kind": kind, "step_id": step["id"], "label": (step.get("target") or {}).get("label"),
                "action": step.get("action"), "risk": step["risk"], "index": index, "total": total,
                "will_send": self._resolve(step), "manual": bool(step.get("manual")), "seen": seen, "lock_seconds": ASK_LOCK_SECONDS, "asked_at": time.time(), **self.context}
        with self._cv:
            self._answer, self.ask = None, card
            while self._answer is None and not self._stop.is_set():
                self._cv.wait(0.1)
            answer = bool(self._answer) and not self._stop.is_set()
            self.ask = None
        self.decisions.append({"step_id": step["id"], "kind": kind, "risk": step["risk"], "approved": answer})
        return answer

    def pick(self, step: dict[str, Any], candidates: list[dict[str, Any]]) -> int | None:
        """Task 6.2: «Có phải ô này?» The look-alikes are coloured on the page; the teller names one (0..2) or none (None)."""
        card = {"id": uuid.uuid4().hex, "kind": "pick", "step_id": step["id"], "label": (step.get("target") or {}).get("label"),
                "action": step.get("action"), "risk": step["risk"], "lock_seconds": ASK_LOCK_SECONDS, "asked_at": time.time(),
                "candidates": [{"label": c.get("label") or "", "tag": c.get("tag") or "", "color": ["vàng", "xanh dương", "xanh lá"][i]}
                               for i, c in enumerate(candidates[:3])]}
        with self._cv:
            self._answer, self._choice, self.ask = None, None, card
            while self._answer is None and not self._stop.is_set():
                self._cv.wait(0.1)
            choice = self._choice if self._answer and not self._stop.is_set() else None
            self.ask = None
        self.decisions.append({"step_id": step["id"], "kind": "pick", "risk": step["risk"], "approved": choice is not None})
        return choice

    def approve(self, step: dict[str, Any], index: int, total: int) -> bool:
        return self._ask("approve", step, index, total)

    def review(self, step: dict[str, Any], index: int, total: int) -> bool:
        return self._ask("review", step, index, total)

    def decide(self, ask_id: str, approve: bool, choice: int | None = None) -> bool:
        """The person answered the open question. False when there is none, or when the id is not its id. For «Có phải ô này?»
        `choice` is the element named (None: none of them)."""
        with self._cv:
            if self.ask is None or self.ask["id"] != ask_id:
                return False
            if self.ask["kind"] == "pick":
                count = len(self.ask.get("candidates") or [])
                self._choice = choice if isinstance(choice, int) and 0 <= choice < count else None
                approve = self._choice is not None
            self._answer = bool(approve)
            self._cv.notify_all()
        return True

    # ---- what happened ------------------------------------------------------------

    def progress(self, step_id: str, status: str, detail: str) -> None:
        for item in self.steps:
            if item["id"] == step_id:
                item["status"], item["detail"] = status, detail
                return
        self.steps.append({"id": step_id, "status": status, "detail": detail})


def trial_of(workflow: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """A trial (Chạy thử) only reads: the steps before the first one that writes or moves money. Returns the shortened flow and the
    name of the step it stops before (None when the whole flow only reads)."""
    kept: list[dict[str, Any]] = []
    for step in workflow["steps"]:
        if step["risk"] != "read":
            return {**workflow, "status": "approved", "steps": kept}, (step.get("target") or {}).get("label") or step["id"]
        kept.append(step)
    return {**workflow, "status": "approved", "steps": kept}, None
