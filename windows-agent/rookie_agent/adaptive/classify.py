"""What kind of change the agent is looking at, and what it may do about it (task 12.2, Analyze; docs/design.md 15).

- technical (the element is not where it was, or not sure): the agent may look for it again, only on a read step, and checks after;
- business (a dialog or a message never seen while recording): the agent stops at this safe point and asks; it never presses in it;
- unknown (what should be on the screen is not): the agent waits, then stops and asks.

Every decision is one row for the audit: what was seen, how it was sorted, what was done, how it ended. Names only, never a value.
"""

from __future__ import annotations

from typing import Any

SORT = {
    "not_found": ("technical", "reresolve"),
    "low_confidence": ("technical", "reresolve"),
    "ambiguous": ("technical", "ask"),
    "unexpected": ("business", "ask"),
    "missing": ("unknown", "ask"),
    "contract_changed": ("technical", "ask"),   # a service answers in another form: the call is not used again until someone checks it
}


def classify(saw: str) -> dict[str, str]:
    change, action = SORT.get(saw, ("unknown", "ask"))
    return {"saw": saw, "change": change, "action": action}


def decision(step_id: str, saw: str, action: str, outcome: str, detail: dict[str, Any] | None = None, *,
             risk: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"step_id": step_id, "saw": saw, "change": classify(saw)["change"], "action": action, "outcome": outcome}
    if risk in ("read", "write", "money"):   # task 12.8: the step's risk, so a self-recovery on a write or money step is visible
        row["risk"] = risk
    if detail:
        row["where"] = {k: str(v) for k, v in detail.items() if k in ("frame", "kind", "name", "how", "score")}
    return row
