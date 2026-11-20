"""After a step: is the screen what the recordings showed? (task 12.2, Monitor and Analyze)

The postcondition of a step (`expect.appears`) names what must be on the screen after it: a table, a field, a message in a frame. The
screen is read in memory (the values stay in this process); only names leave this module. Three answers:

- `ok`: everything expected is there, and nothing new has come up;
- `missing`: something expected is not there (yet): the runner waits a little, then stops and asks;
- `unexpected`: a frame (a dialog) or a message the recordings never showed after this step came up: a business change; the runner
  stops at this safe point and asks. It never presses anything in it.
"""

from __future__ import annotations

from typing import Any

from rookie_agent.adaptive.expect import masked
from rookie_agent.ie import read


def _names(frames: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    found = set()
    for frame, kind, name in read._items(frames):
        item = masked({"frame": frame, "kind": kind, "name": name})
        if item is not None:
            found.add((item["frame"], item["kind"], item["name"]))
    return found


def check(appears: list[dict[str, Any]], before: list[dict[str, Any]], after: list[dict[str, Any]], *,
          known_frames: set[str], volatile: set[tuple[str, str, str]] | None = None, answered_in: set[str] | None = None) -> dict[str, Any]:
    """`known_frames`: the frames the flow was recorded in (its selectors, its postconditions, the screen before the step).
    `volatile`: what changes by itself (`read.volatile`), never news. `answered_in`: the frames the next step acts in: a box there is
    the one the flow answers next (a confirmation the teller taught), the way on, not news."""
    skip = volatile or set()
    now = _names(after)
    missing = [dict(item) for item in appears if (item["frame"], item["kind"], item["name"]) not in now]
    expected_messages = {item["frame"] for item in appears if item["kind"] == "message"} | set(answered_in or ())
    before_frames = {str(f.get("frame") or "top") for f in before}
    unexpected: list[dict[str, str]] = []
    for name in [str(f.get("frame") or "top") for f in after]:
        if name not in before_frames and name not in known_frames and {"frame": name, "kind": "frame"} not in unexpected:
            unexpected.append({"frame": name, "kind": "frame"})
    for change in read.changed(before, after, skip):
        frame = change["frame"]
        if change["kind"] == "message" and frame not in expected_messages and (frame, "message", read.ALL) not in skip:
            item = {"frame": masked(change)["frame"], "kind": "message"}
            if item not in unexpected and {"frame": frame, "kind": "frame"} not in unexpected:
                unexpected.append(item)
    if unexpected:
        return {"state": "unexpected", "unexpected": unexpected, "missing": missing}
    if missing:
        return {"state": "missing", "missing": missing, "unexpected": []}
    return {"state": "ok", "missing": [], "unexpected": []}
