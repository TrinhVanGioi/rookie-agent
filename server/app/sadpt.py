"""SADPT measures (task 12.8, Knowledge): four numbers read from the adaptation log, never from a typed value.

A row is one decision the agent already recorded: what it saw, how it sorted the change, what it did, how that ended.
The server counts; it does not decide again.

- Self-recovery when only the screen changed: a control was missing, unsure, or one of several (`not_found`, `low_confidence`,
  `ambiguous`). Recovered only when the agent found it again itself and the check after passed (`reresolve` / `done`).
  A service that answers in another form (`contract_changed`) is not a screen change, so it is not in this rate.
- Steps recorded again: the steps a teller taught back into a draft (`teach`, the ids in `added`).
- Right stops at a business change: a dialog or a message never seen, and the agent stopped and asked.
- Overreach, which must stay 0: the agent found a target again on a `write` or `money` step, or on a change that is not
  technical, or it did not stop and ask at a business change. The risk is the step's risk on the version that ran.
"""

from __future__ import annotations

from typing import Any

UI_SAW = frozenset({"not_found", "low_confidence", "ambiguous"})


def measure(rows: list[dict[str, Any]], steps_retaught: int = 0) -> dict[str, Any]:
    """The four numbers. `ui_recovery` is absent from the meaning when nothing on a screen had to be found again (`None`)."""
    screen = [row for row in rows if row.get("change") == "technical" and row.get("saw") in UI_SAW]
    recovered = sum(1 for row in screen if row.get("action") == "reresolve" and row.get("outcome") == "done")
    changes = len(screen)
    return {
        "ui_changes": changes,
        "ui_recovered": recovered,
        "ui_recovery": round(recovered / changes, 3) if changes else None,
        "steps_retaught": steps_retaught,
        "business_stops": sum(1 for row in rows if _right_stop(row)),
        "overreach": sum(1 for row in rows if _overreach(row)),
    }


def _right_stop(row: dict[str, Any]) -> bool:
    return row.get("change") == "business" and row.get("action") == "ask" and row.get("outcome") == "stopped"


def _overreach(row: dict[str, Any]) -> bool:
    if row.get("action") == "reresolve" and (row.get("risk") in ("write", "money") or row.get("change") != "technical"):
        return True
    return row.get("change") == "business" and not _right_stop(row)
