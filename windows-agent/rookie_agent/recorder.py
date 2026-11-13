"""Turn what Java Access Bridge reports into events (schemas/event.schema.json).

This module knows nothing about the bridge itself: `rookie_agent.jab.session`
feeds it `Element`s, and tests feed it fakes. All PII decisions are made here,
on the GDV's machine, before anything leaves the process:

- password fields produce no event at all;
- sensitive fields produce an event with the class of the field and no value;
- only fields classed as plain keep their value.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from rookie_agent.classify import classify
from rookie_agent.selectors import Element, selectors_for

SCHEMA_VERSION = 1

TEXT_ROLES = frozenset({"text"})
# Reported through mouse clicks.
CLICK_ROLES = frozenset({"push button", "menu", "menu item", "hyperlink"})
# Reported through their checked state, so keyboard use is recorded too.
TOGGLE_ROLES = frozenset({"check box", "radio button", "toggle button"})
TAB_ROLE = "page tab"
TABLE_ROLE = "table"
COMBO_ROLE = "combo box"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Recorder:
    def __init__(self, session_id: str | None = None, clock: Callable[[], str] = _now) -> None:
        self.session_id = session_id or f"s-{uuid.uuid4().hex[:12]}"
        self._clock = clock
        self._events: list[dict] = []
        # Edited text fields waiting to be written out, in the order they were first edited.
        self._dirty: dict[str, tuple[Element, str]] = {}
        # Last selection written per component: the bridge reports each selection more than once.
        self._selected: dict[str, str] = {}

    @property
    def events(self) -> list[dict]:
        return list(self._events)

    def _emit(self, kind: str, element: Element, value: str | None = None, value_class: str | None = None) -> None:
        self._events.append(
            {
                "schema_version": SCHEMA_VERSION,
                "engine": "java",
                "session_id": self.session_id,
                "seq": len(self._events),
                "ts": self._clock(),
                "type": kind,
                "url": element.window,
                "target": {
                    "selectors": selectors_for(element),
                    "label": element.name or None,
                    "tag": element.role,
                },
                "value": value,
                "value_class": value_class,
                "api_calls": [],
            }
        )

    # ---- text -------------------------------------------------------------------

    def text_changed(self, element: Element, value: str | None, focused: bool) -> None:
        """A text component changed. Only edits made while it has focus count as typing;
        the application clearing a form after a submit must not be recorded as input."""
        if element.role not in TEXT_ROLES or not focused:
            return
        if classify(element.name, element.role).kind == "ignore":
            return
        self._dirty[element.key] = (element, value or "")

    def _flush(self, key: str) -> None:
        pending = self._dirty.pop(key, None)
        if pending is None:
            return
        element, value = pending
        field = classify(element.name, element.role)
        if field.kind == "plain":
            self._emit("input", element, value=value)
        elif field.kind == "sensitive":
            self._emit("input", element, value_class=field.value_class)

    def _flush_all(self) -> None:
        for key in list(self._dirty):
            self._flush(key)

    def focus_lost(self, element: Element) -> None:
        self._flush(element.key)

    # ---- clicks and selections ----------------------------------------------------

    def clicked(self, element: Element) -> None:
        """A mouse click. Text fields, panels and labels are not actions."""
        if element.role in CLICK_ROLES:
            self._flush_all()
            self._emit("click", element)

    def toggled(self, element: Element) -> None:
        """A check box, radio button or toggle button changed its checked state."""
        if element.role in TOGGLE_ROLES:
            self._flush_all()
            self._emit("click", element)

    def tab_selected(self, element: Element) -> None:
        if element.role == TAB_ROLE:
            self._flush_all()
            self._emit("click", element)

    def _select(self, element: Element, value: str, value_class: str | None = None) -> None:
        if self._selected.get(element.key) == value:
            return
        self._selected[element.key] = value
        self._flush_all()
        if value_class is None:
            self._emit("select", element, value=value)
        else:
            self._emit("select", element, value_class=value_class)

    def row_selected(self, element: Element, row: int) -> None:
        """A table row was selected. The row index is kept; cell contents are not."""
        if element.role == TABLE_ROLE and row >= 0:
            self._select(element, str(row))

    def option_selected(self, element: Element, option: str, focused: bool) -> None:
        """The user picked an option in a combo box. As with text, a change made by the
        application itself (the combo box does not have focus) is not an action of the user."""
        if element.role != COMBO_ROLE or not focused:
            return
        field = classify(element.name, element.role)
        if field.kind == "plain":
            self._select(element, option)
        elif field.kind == "sensitive":
            # Keep the fact that a choice was made, not which one.
            self._select(element, option, value_class=field.value_class)

    def stop(self) -> list[dict]:
        """Write out pending edits and return every event of the session."""
        self._flush_all()
        return self.events
