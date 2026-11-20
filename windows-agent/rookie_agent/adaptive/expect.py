"""What the screen showed right after each recorded action, kept with the event as names only (task 12.1, Monitor).

The recorder reads the screen after every action (`IeSession.seen`, in memory, with the values). Here each event gets the part that
changed: frame, kind (field, table, message) and name. A field's label and a frame's name are masked like any label (digits); a message
keeps no text at all, only that one appeared (its text can hold a customer's name). On the server the parts every recording shows become
the step's postcondition (`expect`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rookie_agent.ie.recorder import _mask

MAX_SHOWS = 20
KINDS = ("field", "table", "message")


def _ms(ts: str) -> int | None:
    try:
        return int(round(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000))
    except (TypeError, ValueError):
        return None


def masked(change: dict[str, Any]) -> dict[str, str] | None:
    kind = str(change.get("kind") or "")
    if kind not in KINDS:
        return None
    frame = _mask(str(change.get("frame") or "top"))[:120] or "top"
    name = "" if kind == "message" else _mask(str(change.get("name") or ""))[:60]
    return {"frame": frame, "kind": kind, "name": name}


def attach_shows(events: list[dict[str, Any]], seen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The events, each with `shows` when the screen was read after it (an empty list: read, and nothing changed). An event the
    screen was not read after gets no `shows`, so it says nothing either way."""
    after: dict[int, list[dict[str, str]]] = {}
    for entry in seen:
        moment = (entry.get("after") or {}).get("t")
        if entry.get("provisional") or moment is None:
            continue
        items = after.setdefault(int(moment), [])
        for change in entry.get("changed") or []:
            item = masked(change)
            if item is not None and item not in items:
                items.append(item)
    out = []
    for event in events:
        moment = _ms(str(event.get("ts") or ""))
        if moment in after:
            out.append({**event, "shows": after[moment][:MAX_SHOWS]})
        else:
            out.append(dict(event))
    return out
