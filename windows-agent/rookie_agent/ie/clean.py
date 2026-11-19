"""Clean the recordings of one task before learning (task 11.4): one place, one list of rules, checked by tests/test_ie_matrix.py.

Done on the teller's PC, where the recordings and their requests are. What goes to the server is the cleaned events.

Rules (in this order):
0. **The page asking by itself is not the teller's work.** A call made three times or more with the same method, address and body,
   numbers of five digits or more in the address counted as one (a cache-buster, a time), whose answer no later call needs, is the
   page polling (a keep-alive, a clock). It is left out of every effect and of the flow (`replay.build_api` uses `polling`).
2. **A mistaken press is not a step.** The page's own message box (a warning after a date in the wrong format: `dlgMessageBox`
   and the like, the same words as page_recorder.js `isMessageBox`), the calls that open it and the presses made inside it are left
   out. A press that called no service, when the same button is pressed again later in the recording and that time does, was a
   mistake: it is left out with what it fired; the field typed again in between keeps its last value (the Learner merges it).
1. **The same effect is the same step.** A teller presses Enter in a field one time and the button the next time: both fire the same
   service. The effect of an action is the calls it fired, named by what they do (the GWT service and method of the body, the path
   otherwise; never a value). An Enter in a field, in a recording where the button with the same effect was not pressed, becomes a
   press of that button when another recording typed the same field and pressed it. Running on the screen then presses the button,
   which works whichever way the teller did it.
"""

from __future__ import annotations

import copy
import re
from collections import Counter
from typing import Any
from urllib.parse import parse_qs, urlsplit

POLLING = 3            # the same call this many times, with no later call needing its answer, is the page asking by itself
_LONG_NUMBER = re.compile(r"\d{5,}")
_MESSAGE_BOX = re.compile(r"(messagebox|dlgmsg|dlgalert|dlgconfirm|dlgwarn|dlgerror|dlginfo)", re.IGNORECASE)   # = page_recorder.js isMessageBox


def is_message_box(url: str) -> bool:
    return bool(_MESSAGE_BOX.search(str(url or "").split("?", 1)[0]))


def poll_key(request: dict[str, Any]) -> tuple[str, str, str]:
    return (str(request.get("method") or "GET").upper(), _LONG_NUMBER.sub("#", str(request.get("url") or "")),
            _LONG_NUMBER.sub("#", str(request.get("body") or "")))


def polling(requests: list[dict[str, Any]]) -> set[int]:
    """Rule 0: the indexes (`index`, else the place in the list) of the calls that are the page asking by itself."""
    counts = Counter(poll_key(r) for r in requests)
    needed = {rule.get("from") for r in requests for rule in (r.get("links") or {}).values()}
    return {int(r.get("index", i)) for i, r in enumerate(requests) if counts[poll_key(r)] >= POLLING and int(r.get("index", i)) not in needed}


def _op(request: dict[str, Any]) -> str:
    """What one call does, without any value: METHOD path, plus the service and method of a GWT-RPC body or the `method=` of the query."""
    url = str(request.get("url") or "")
    parts = urlsplit(url)
    name = f"{str(request.get('method') or 'GET').upper()} {parts.path}"
    body = str(request.get("body") or "")
    fields = body.split("|")
    if len(fields) > 6 and fields[0] == "7":          # GWT-RPC: 7|0|n|base|strong name|service|method|…
        return f"{name} {fields[5].rsplit('.', 1)[-1]}.{fields[6]}"
    method = (parse_qs(parts.query).get("method") or [""])[0]
    return f"{name} {method}".strip()


def effect(document: dict[str, Any], seq: int) -> tuple[str, ...]:
    """The calls an action fired (those the server answered, not the page polling), as `_op` names, in order."""
    requests = document.get("requests") or []
    asking = polling(requests)
    return tuple(_op(r) for i, r in enumerate(requests)
                 if r.get("after_seq") == seq and 100 <= int(r.get("status") or 0) < 400 and int(r.get("index", i)) not in asking
                 and not is_message_box(str(r.get("url") or "")))


def _in_message_box(event: dict[str, Any]) -> bool:
    return is_message_box(str(event.get("url") or ""))


def drop_mistakes(document: dict[str, Any]) -> dict[str, Any]:
    """Rule 2 on one recording: a copy without the message box and the mistaken presses."""
    events = [e for e in document.get("events") or [] if not _in_message_box(e)]
    pressed = [e for e in events if e.get("type") in ("click", "submit") and e.get("seq") is not None]
    gone: set[int] = set()
    for place, event in enumerate(pressed):
        if effect(document, int(event["seq"])):
            continue
        again = any(_key(later) == _key(event) and effect(document, int(later["seq"])) for later in pressed[place + 1:])
        if again:
            gone.add(int(event["seq"]))
    requests = [r for r in document.get("requests") or []
                if not is_message_box(str(r.get("url") or "")) and r.get("after_seq") not in gone]
    return {**document, "events": [e for e in events if e.get("seq") is None or int(e["seq"]) not in gone], "requests": requests}


_MARK_E = re.compile(r"⟦e(\d+)⟧")


def renumber(document: dict[str, Any]) -> dict[str, Any]:
    """Events numbered 0, 1, 2… again after some were left out (the server wants them in a row), and what points at them follows:
    the `after_seq` of each call and the marks ⟦eN⟧ of the typed values in the templates."""
    new = {int(e["seq"]): place for place, e in enumerate(document.get("events") or []) if e.get("seq") is not None}
    events = [{**e, "seq": place} for place, e in enumerate(document.get("events") or [])]

    def mark(match: re.Match[str]) -> str:
        old = int(match.group(1))
        return f"⟦e{new[old]}⟧" if old in new else match.group(0)

    requests = []
    for r in document.get("requests") or []:
        moved = {**r, **{k: _MARK_E.sub(mark, str(r[k])) for k in ("url", "body", "headers") if isinstance(r.get(k), str)}}
        if r.get("after_seq") is not None:
            moved["after_seq"] = new.get(int(r["after_seq"]))
        requests.append(moved)
    return {**document, "events": events, "requests": requests}


def clean(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every rule, in order, on the recordings of one task: copies; the stored recordings are not changed."""
    copies = [renumber(drop_mistakes(copy.deepcopy(d))) for d in documents]
    unified = unify_triggers(copies)
    return [{**d, "events": events} for d, events in zip(copies, unified)]


def _key(event: dict[str, Any]) -> str:
    target = event.get("target") or {}
    return (target.get("selectors") or [""])[0]


def unify_triggers(documents: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Rule 1. The events of each recording, an Enter rewritten as the press of the button with the same effect where one is known."""
    out = [copy.deepcopy(d.get("events") or []) for d in documents]
    presses: dict[tuple[str, ...], Counter] = {}           # effect -> the buttons pressed for it, and how often
    typed: list[set[str]] = []
    targets: dict[str, dict[str, Any]] = {}
    for document, events in zip(documents, out):
        typed.append({_key(e) for e in events if e.get("type") in ("input", "select")})
        for event in events:
            if event.get("type") == "click" and event.get("seq") is not None:
                done = effect(document, int(event["seq"]))
                if done:
                    presses.setdefault(done, Counter())[_key(event)] += 1
                    targets.setdefault(_key(event), event.get("target") or {})
    for number, (document, events) in enumerate(zip(documents, out)):
        mine = {_key(e) for e in events if e.get("type") == "click"}
        for event in events:
            if event.get("type") != "submit" or event.get("seq") is None:
                continue
            done = effect(document, int(event["seq"]))
            button = next((b for b, _ in presses.get(done, Counter()).most_common()), None) if done else None
            others_typed = any(_key(event) in typed[i] for i in range(len(out)) if i != number)
            if button and button not in mine and others_typed:
                event["type"] = "click"
                event["target"] = copy.deepcopy(targets[button])
                event["value"] = None
    return out
