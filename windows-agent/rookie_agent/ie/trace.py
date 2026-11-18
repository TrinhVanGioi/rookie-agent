"""Build the masked trace (schemas/trace.schema.json) from the raw lines of several recording sessions.

Runs on the teller's PC, before anything is saved or sent (CLAUDE.md rule 2). Every action is kept: this module does not decide
what is "worth" recording, the model that designs the workflow does. It only removes or masks what is sensitive:

- a password, OTP, hidden or file field produces no event at all; the number of dropped events is counted;
- a typed character is never kept: a key event holds only the class of the key (enter, tab, ...);
- a field value is kept only when the field is classified `plain`, otherwise only its class;
- numbers in labels and titles are masked (a word with 3 or more digits becomes `#`);
- the text of something that is not a control (a table cell, a list row) belongs to the customer: it is kept only when it is
  identical in every session, otherwise it becomes `#`. With a single session it always becomes `#`.
"""

from __future__ import annotations

import re
from typing import Any

from rookie_agent.classify import classify
from rookie_agent.ie.recorder import IGNORED_TYPES, SECRET_NAME, IeRecorder, _mask

SCHEMA_VERSION = 2
RULES_VERSION = "1"
ENGINE = "ie"
KINDS = frozenset({"click", "dblclick", "key", "change", "focus", "blur", "submit", "load", "unload"})
SNAP = "snap"  # what a choice list shows when the page is ready: not an action, it becomes `initial` and `options`
MAX_OPTIONS = 50
MIN_LINKED = 3   # a value shorter than this means nothing when it matches something on the screen
KEY_CLASSES = frozenset({"enter", "tab", "escape", "function", "arrow", "char", "other"})
CONTROL_TAGS = frozenset({"input", "select", "textarea", "button", "a"})
HASH = "#"


def _safe_id(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", text) or "s"


class TraceBuilder:
    def __init__(self, app_title: str = "", trace_id: str = "t-1") -> None:
        self._app = _mask(app_title) or "IE"
        self._trace_id = trace_id
        self._sessions: list[tuple[str, list[dict[str, Any]]]] = []
        self._dropped = 0
        self._requests: dict[str, list[dict[str, Any]]] = {}
        self._screens: dict[str, list[dict[str, Any]]] = {}   # session id -> what the screen showed after each action

    def add_session(self, session_id: str, lines: list[dict[str, Any]]) -> None:
        """One recording: its raw lines, in any order. Sensitive lines are removed here, now."""
        kept: list[dict[str, Any]] = []
        for index, raw in enumerate(lines):
            kind = {"input": "change", "select": "change"}.get(str(raw.get("kind") or ""), str(raw.get("kind") or ""))
            if kind == SNAP:
                # only an ordinary (plain) list keeps its value and its options; anything else leaves nothing at all
                if not self._is_secret(raw, kind) and IeRecorder._class_of(raw).kind == "plain":
                    kept.append({**raw, "kind": SNAP, "_order": index})
                continue
            if kind not in KINDS:
                continue
            if self._is_secret(raw, kind):
                self._dropped += 1
                continue
            item = dict(raw)
            item["kind"] = kind
            item["_order"] = index
            kept.append(item)
        self._sessions.append((session_id, kept))

    def add_requests(self, session_id: str, requests: list[dict[str, Any]]) -> None:
        """The requests the page made during a session (`IeSession.requests`). Only their shape goes into the trace: the method, the
        path without its query, the status and the time. Never the request, the response or the query."""
        self._requests[session_id] = list(requests)

    def add_screens(self, session_id: str, snapshots: list[dict[str, Any]]) -> None:
        """What the screen showed after the actions of a session (`IeSession.seen`). Only its structure goes into the trace."""
        self._screens[session_id] = [x for x in snapshots if x.get("after")]

    # ---- what may not be kept ----------------------------------------------------

    @staticmethod
    def _is_secret(raw: dict[str, Any], kind: str) -> bool:
        field_type = str(raw.get("type") or "").lower()
        if field_type in IGNORED_TYPES:
            return True
        if kind == "click":
            return False  # pressing a button named "Quen mat khau" is an action; no value is involved
        text = " ".join(str(raw.get(key) or "") for key in ("label", "name", "id"))
        if SECRET_NAME.search(text):
            return True
        return kind == "change" and IeRecorder._class_of(raw).kind == "ignore"

    # ---- output ------------------------------------------------------------------

    @staticmethod
    def _element_key(raw: dict[str, Any]) -> str:
        return "|".join(str(raw.get(key) or "") for key in ("frame", "id", "name", "tag")) + f"|{raw.get('pos', -1)}"

    def _links_of(self, session_id: str, actions: list[dict[str, Any]], events: list[dict[str, Any]], start: int) -> list[dict[str, Any]]:
        """A value the teller typed that the screen had shown just before is a link between the two steps (the account number found by the
        search, typed into the next screen). Found here, on this PC, from the full values in memory; only the link goes into the trace: which
        event typed it, which action's screen showed it, and the path of the value on that screen. Never the value."""
        from rookie_agent.ie import read

        snapshots = [x for x in self._screens.get(session_id, []) if x.get("frames")]
        links: list[dict[str, Any]] = []
        for raw, event in zip(actions, events):
            if raw["kind"] != "change":
                continue
            typed = str(raw.get("value") or "").strip()
            if len(typed) < MIN_LINKED:
                continue
            moment = int(raw.get("t") or 0)
            for snapshot in reversed([x for x in snapshots if int(x.get("t") or 0) <= moment]):
                found = [item["path"] for item in read.listing(read.model(snapshot["frames"])) if item["value"] == typed]
                if not found:
                    continue
                after = snapshot.get("after") or {}
                kind = {"input": "change", "select": "change"}.get(str(after.get("kind")), str(after.get("kind")))
                when = max(0, int(after.get("t") or 0) - start) if after.get("t") else None
                source = next((e["eid"] for e in events if when is not None and e["kind"] == kind and e["t_rel_ms"] == when), None)
                links.append({"eid": event["eid"], "from_eid": source, "path": found[0], "ambiguous": len(found) > 1})
                break
        return links

    def _requests_of(self, session_id: str, events: list[dict[str, Any]], start: int) -> list[dict[str, Any]]:
        result = []
        for item in self._requests.get(session_id, []):
            path = str(item.get("url") or "").split("?", 1)[0].split("#", 1)[0]
            after = item.get("after") or {}
            kind = {"input": "change", "select": "change"}.get(str(after.get("kind")), str(after.get("kind")))
            moment = max(0, int(after.get("t") or 0) - start) if after.get("t") else None
            eid = next((e["eid"] for e in events if moment is not None and e["kind"] == kind and e["t_rel_ms"] == moment), None)
            result.append({"after_eid": eid, "method": str(item.get("method") or "").upper(), "path": _mask(path)[:200],
                           "status": int(item.get("status") or 0), "ms": int(item.get("ms") or 0)})
        return result

    def _screens_of(self, session_id: str, events: list[dict[str, Any]], start: int) -> list[dict[str, Any]]:
        """One entry per action that was followed by a look at the screen: the event it follows, the frames that changed, and the
        structure of what changed (never a value)."""
        result = []
        for snapshot in self._screens.get(session_id, []):
            after = snapshot["after"]
            kind = {"input": "change", "select": "change"}.get(str(after.get("kind")), str(after.get("kind")))
            moment = max(0, int(after.get("t") or 0) - start)
            eid = next((e["eid"] for e in events if e["kind"] == kind and e["t_rel_ms"] == moment), None)
            items = self._screen_items(snapshot)
            if items:
                result.append({"after_eid": eid, "region": [str(r) for r in snapshot.get("region") or []], "items": items})
        return result

    @staticmethod
    def _class_name(label: str) -> str:
        found = classify(label)
        return "plain" if found.kind == "plain" else (found.value_class or "unclassified")

    def _screen_items(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        """The kind, the headers and the class of each column, the number of rows, the level of a message: never a value, never the
        text of a message (it can hold a customer's name)."""
        changed = {(c["frame"], c["kind"], str(c.get("name"))) for c in snapshot.get("changed") or []}
        items: list[dict[str, Any]] = []
        for frame in snapshot.get("frames") or []:
            name = str(frame.get("frame") or "top")
            for index, table in enumerate(frame.get("tables") or []):
                if (name, "table", str(table.get("id") or f"t{index}")) not in changed:
                    continue
                headers = [str(h) for h in table.get("headers") or []]
                items.append({"frame": name, "kind": "table", "table_id": _mask(table.get("id") or ""), "headers": [_mask(h) for h in headers],
                              "col_classes": [self._class_name(h) for h in headers],
                              "row_count": int(table.get("row_count") or len(table.get("rows") or []))})
            for pair in frame.get("fields") or []:
                if (name, "field", str(pair.get("label"))) in changed:
                    items.append({"frame": name, "kind": "field", "label": _mask(pair.get("label")),
                                  "value_class": self._class_name(str(pair.get("label") or ""))})
            if any(key[0] == name and key[1] == "message" for key in changed):
                for level in sorted({str(m.get("level") or "info") for m in frame.get("messages") or []}):
                    items.append({"frame": name, "kind": "message", "level": level})
        return items

    def _initial(self, snaps: list[dict[str, Any]], actions: list[dict[str, Any]], keys: dict[str, str]) -> dict[str, Any]:
        """What each ordinary choice list showed before the teller touched it in this session: the last snapshot taken before the
        first touch (a page script may set the default after onload), or the first snapshot when it was never touched."""
        touched: dict[str, int] = {}
        for raw in actions:
            touched.setdefault(self._element_key(raw), int(raw.get("t") or 0))
        chosen: dict[str, dict[str, Any]] = {}
        for raw in snaps:  # already in time order
            key = self._element_key(raw)
            moment = int(raw.get("t") or 0)
            if key not in chosen or moment <= touched.get(key, moment):
                chosen[key] = raw
        return {
            keys[key]: {"value": None if raw.get("optv") is None else str(raw["optv"]),
                        "text": None if raw.get("value") is None else _mask(str(raw["value"]))}
            for key, raw in chosen.items() if key in keys
        }

    def build(self) -> dict[str, Any]:
        keys: dict[str, str] = {}              # element key -> el_id, in order of first appearance
        first: dict[str, dict[str, Any]] = {}  # element key -> the first raw line that mentions it
        labels: dict[str, dict[str, str]] = {}  # element key -> {session_id: masked label}
        controls: dict[str, bool] = {}
        for session_id, lines in self._sessions:
            for raw in sorted(lines, key=lambda item: (int(item.get("t") or 0), item["_order"])):
                if raw["kind"] in ("load", "unload") and not raw.get("tag"):
                    continue
                key = self._element_key(raw)
                if key not in keys:
                    keys[key] = f"e{len(keys) + 1}"
                    first[key] = raw
                labels.setdefault(key, {}).setdefault(session_id, _mask(raw.get("label")))
                tag = str(raw.get("tag") or "").lower()
                controls[key] = controls.get(key, False) or bool(raw.get("ctl", tag in CONTROL_TAGS))

        options: dict[str, list[dict[str, Any]]] = {}  # element key -> its options (ordinary lists only)
        for _, lines in self._sessions:
            for raw in sorted(lines, key=lambda item: (int(item.get("t") or 0), item["_order"])):
                key = self._element_key(raw)
                if key not in options and isinstance(raw.get("opts"), list) and IeRecorder._class_of(raw).kind == "plain":
                    options[key] = [{"value": None if o.get("v") is None else str(o["v"]), "text": _mask(o.get("t"))}
                                    for o in raw["opts"][:MAX_OPTIONS] if isinstance(o, dict)]

        count = len(self._sessions)
        elements: dict[str, Any] = {}
        for key, el_id in keys.items():
            raw = first[key]
            tag = str(raw.get("tag") or "").lower()
            per_session = labels[key]
            if controls[key]:
                label = next(iter(per_session.values()), "")
            else:  # the text of a row or a cell is the customer's: only text that never changes is the screen's own
                same = len(per_session) == count and len(set(per_session.values())) == 1
                label = next(iter(per_session.values())) if same and count >= 2 else HASH
            frame = str(raw.get("frame") or "top")
            selectors = IeRecorder._selectors(raw, frame, "" if label == HASH else label, tag)
            if not selectors:
                selectors = [f"frame={frame}|{tag or 'node'}[{raw.get('pos', -1)}]"]
            elements[el_id] = {
                "frame": frame, "tag": tag, "type": str(raw.get("type") or "").lower(),
                "label": label or None, "selectors": selectors, "is_control": controls[key],
            }
            if key in options:
                elements[el_id]["options"] = options[key]

        sessions = []
        for number, (session_id, lines) in enumerate(self._sessions, start=1):
            ordered = sorted(lines, key=lambda item: (int(item.get("t") or 0), item["_order"]))
            snaps = [raw for raw in ordered if raw["kind"] == SNAP]
            ordered = [raw for raw in ordered if raw["kind"] != SNAP]
            start = int(ordered[0].get("t") or 0) if ordered else 0
            events = []
            for seq, raw in enumerate(ordered):
                key = self._element_key(raw)
                kind = raw["kind"]
                value, value_class, value_before, option_value = None, None, None, None
                if kind == "change":
                    field = IeRecorder._class_of(raw)
                    if field.kind == "plain":
                        value = str(raw.get("value") if raw.get("value") is not None else "")
                        value_before = None if raw.get("before") is None else str(raw["before"])
                        option_value = None if raw.get("optv") is None else str(raw["optv"])
                    else:
                        value_class = field.value_class or "unclassified"
                key_class = None
                if kind == "key":
                    key_class = raw.get("keyclass") if raw.get("keyclass") in KEY_CLASSES else "other"
                events.append({
                    "eid": f"s{number}e{seq:03d}", "seq": seq, "t_rel_ms": max(0, int(raw.get("t") or 0) - start), "kind": kind,
                    "el_id": keys.get(key), "key_class": key_class, "value": value, "value_class": value_class,
                    "screen": _mask(raw.get("title")), "value_before": value_before, "option_value": option_value,
                })
            if events:
                session: dict[str, Any] = {"session_id": _safe_id(session_id), "events": events}
                initial = self._initial(snaps, ordered, keys)
                if initial:
                    session["initial"] = initial
                screens = self._screens_of(session_id, events, start)
                if screens:
                    session["screens"] = screens
                links = self._links_of(session_id, ordered, events, start)
                if links:
                    session["links"] = links
                requests = self._requests_of(session_id, events, start)
                if requests:
                    session["requests"] = requests
                sessions.append(session)
        return {
            "schema_version": SCHEMA_VERSION, "engine": ENGINE, "trace_id": self._trace_id, "app": self._app,
            "sessions": sessions, "elements": elements,
            "masking": {"rules_version": RULES_VERSION, "dropped_count": self._dropped},
        }
