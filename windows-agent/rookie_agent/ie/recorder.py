"""Turn what the recorder inside an Internet Explorer page reports into events (schemas/event.schema.json).

`page_recorder.js` (in the page, old JavaScript) hands over raw lines. All decisions about what may be kept are made
here, on the teller's PC, before anything is saved or sent (CLAUDE.md rule 2):

- a password, OTP or hidden field produces no event at all, whatever the page says;
- a sensitive field produces an event with the class of the field and no value;
- only a field classed as plain keeps its value; a field nobody classified is sensitive;
- digits runs in labels and titles are masked, as a label can hold a number from the screen.
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from rookie_agent.classify import classify

SCHEMA_VERSION = 2
ENGINE = "ie"
PRESS_DEBOUNCE_MS = 500
IGNORED_TYPES = frozenset({"password", "hidden", "file"})
# The page-side recorder already skips these; the agent does not rely on it.
SECRET_NAME = re.compile(r"pass|pwd|otp|secret|mat.?khau|(?<![a-z])pin(?![a-z])", re.IGNORECASE)
LONG_NUMBER = re.compile(r"\d{6,}")
PRESSABLE_TAGS = {"button": "button", "a": "link", "input": "button", "img": "button", "td": "button", "div": "button", "span": "button", "li": "button"}


def _mask(text: str | None) -> str:
    return LONG_NUMBER.sub("#", " ".join((text or "").split()))[:60]


def _iso(milliseconds: int) -> str:
    moment = datetime.fromtimestamp(milliseconds / 1000.0, tz=timezone.utc)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class IeRecorder:
    def __init__(self, app_title: str = "", session_id: str | None = None) -> None:
        self.session_id = session_id or f"s-{uuid.uuid4().hex[:12]}"
        self._app = _mask(app_title) or "IE"
        self._raw: list[dict[str, Any]] = []
        self._last_press: dict[str, int] = {}

    # ---- input from the page ------------------------------------------------------

    def handle(self, line: dict[str, Any]) -> None:
        """One raw action from the page. It is judged now; what is not allowed is dropped here."""
        kind = str(line.get("kind") or "")
        if kind not in ("click", "input", "select", "submit"):
            return
        field_type = str(line.get("type") or "").lower()
        text = " ".join(str(line.get(key) or "") for key in ("label", "name", "id"))
        if kind in ("input", "select") and (field_type in IGNORED_TYPES or SECRET_NAME.search(text)):
            return
        if field_type == "hidden":
            return
        if kind in ("input", "select") and self._class_of(line).kind == "ignore":
            return
        self._raw.append(line)

    @staticmethod
    def _class_of(line: dict[str, Any]):
        role = "password text" if str(line.get("type") or "").lower() == "password" else ""
        return classify(str(line.get("label") or line.get("name") or line.get("id") or ""), role)

    # ---- output -------------------------------------------------------------------

    def stop(self) -> list[dict[str, Any]]:
        """The events of the session, in the order they happened (lines from different frames arrive in any order)."""
        lines = sorted(self._raw, key=lambda item: int(item.get("t") or 0))
        events: list[dict[str, Any]] = []
        for line in lines:
            event = self._event(line, len(events))
            if event is None or self._is_repeat(line, event):
                continue
            events.append(event)
        return events

    def _is_repeat(self, line: dict[str, Any], event: dict[str, Any]) -> bool:
        """The same button reported twice in a moment (mouse and key) is one click."""
        if event["type"] != "click":
            return False
        key = event["target"]["selectors"][0]
        moment = int(line.get("t") or 0)
        previous = self._last_press.get(key)
        self._last_press[key] = moment
        return previous is not None and moment - previous < PRESS_DEBOUNCE_MS

    def _event(self, line: dict[str, Any], seq: int) -> dict[str, Any] | None:
        kind = str(line["kind"])
        tag = str(line.get("tag") or "").lower()
        field_type = str(line.get("type") or "").lower()
        label = _mask(line.get("label"))
        frame = str(line.get("frame") or "top")
        selectors = self._selectors(line, frame, label, tag)
        if not selectors:
            return None
        if kind == "click":
            shown_tag = field_type if tag == "input" and field_type in ("checkbox", "radio") else PRESSABLE_TAGS.get(tag, "button")
        else:
            shown_tag = tag
        value: str | None = None
        value_class: str | None = None
        if kind in ("input", "select"):
            field = self._class_of(line)
            if field.kind == "plain":
                value = str(line.get("value") if line.get("value") is not None else "")
            else:
                value_class = field.value_class or "unclassified"
        title = _mask(line.get("title"))
        return {
            "schema_version": SCHEMA_VERSION,
            "engine": ENGINE,
            "session_id": self.session_id,
            "seq": seq,
            "ts": _iso(int(line.get("t") or time.time() * 1000)),
            "type": kind,
            "url": f"{self._app}/{title}" if title else self._app,
            "target": {"selectors": selectors, "label": label or None, "tag": shown_tag},
            "value": value,
            "value_class": value_class,
            "api_calls": [],
        }

    @staticmethod
    def _selectors(line: dict[str, Any], frame: str, label: str, tag: str) -> list[str]:
        """Most stable first: the id, the name, the visible label, then the position among the same tags."""
        found: list[str] = []
        if line.get("id"):
            found.append(f"frame={frame}|id={line['id']}")
        if line.get("name"):
            found.append(f"frame={frame}|name={line['name']}")
        if label:
            found.append(f"frame={frame}|label={label}")
        position = line.get("pos")
        if isinstance(position, int) and position >= 0 and tag:
            found.append(f"frame={frame}|{tag}[{position}]")
        return found
