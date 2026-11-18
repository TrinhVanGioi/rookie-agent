"""A stand-in for the model behind Genie Codie, for tests only. It is run as a real process by the server (`codie --mode M --cwd W -p P`),
reads `trace.json` (and `design.json`) in the working directory, and answers the way a good model would, between the marker lines.

It only knows what the tests need: it groups the events of the recordings into steps, makes a value a parameter when the recordings differ
(or the field is sensitive), makes it a link when the trace says the screen showed it before, and an optional step when a recording lacks it.
"""

import json
import re
import sys
import unicodedata

OPEN, CLOSE = "<<<MV_RESULT", "MV_RESULT>>>"


def slug(text):
    plain = unicodedata.normalize("NFD", (text or "").replace("đ", "d").replace("Đ", "D"))
    plain = "".join(c for c in plain if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", "_", plain).strip("_") or "gia_tri"


def acting(session, elements):
    """The actions of one recording in order; typing in the same field again replaces the earlier typing."""
    result = []
    for event in session["events"]:
        if event["kind"] not in ("click", "submit", "change"):
            continue
        if result and result[-1]["el_id"] == event["el_id"] and event["kind"] == "change" and result[-1]["kind"] == "change":
            result[-1] = event
            continue
        result.append(event)
    return result


def action_of(event, elements):
    if event["kind"] == "change":
        return "select" if elements[event["el_id"]]["tag"] == "select" else "fill"
    return event["kind"]


def design(trace):
    elements, sessions = trace["elements"], trace["sessions"]
    per_session = {s["session_id"]: acting(s, elements) for s in sessions}
    used = {sid: set() for sid in per_session}
    columns = []                                           # (action, el_id, {sid: event})
    for sid, events in per_session.items():
        for event in events:
            action = action_of(event, elements)
            for column in columns:
                if column[0] == action and column[1] == event["el_id"] and sid not in column[2]:
                    column[2][sid] = event
                    break
            else:
                columns.append((action, event["el_id"], {sid: event}))
    steps, links = [], {(s["session_id"], link["eid"]): link for s in sessions for link in s.get("links", [])}
    names = set()
    for number, (action, el_id, found) in enumerate(columns, start=1):
        step = {"n": len(steps) + 1, "intent_vi": elements[el_id].get("label") or action, "action": action, "el_id": el_id,
                "evidence": {sid: [e["eid"]] for sid, e in found.items()}}
        if len(found) < len(sessions):
            step["optional"] = "if_different" if action in ("fill", "select") else "if_present"
        if action in ("fill", "select"):
            values = [(e.get("value"), e.get("option_value")) for e in found.values()]
            link = next((links[(sid, e["eid"])] for sid, e in found.items() if (sid, e["eid"]) in links), None)
            sensitive = any(e.get("value_class") not in (None, "unclassified", "plain") for e in found.values())
            if link and not sensitive and len(set(values)) == 1:
                step["value_kind"], step["link"] = "link", {"var": "kq", "path": link["path"]}
            elif sensitive or len(set(values)) > 1 or len(found) == 1 or step.get("optional") or values[0] == (None, None):    # not stored: nothing to be a constant
                name = slug(elements[el_id].get("label"))
                while name in names:
                    name += "_2"
                names.add(name)
                step["value_kind"], step["param_name"] = "param", name
            else:
                step["value_kind"], step["const_value"] = "const", values[0][0] if values[0][0] is not None else values[0][1]
        steps.append(step)
        if step.get("value_kind") == "link":
            pass
    # the read_fields step goes right after the click that showed the linked value
    result, read_added = [], False
    for step in steps:
        result.append(step)
    for index, step in enumerate(list(result)):
        if step.get("value_kind") == "link" and not read_added:
            source = next((i for i, s in enumerate(result) if s["action"] == "click"), None)
            for number, candidate in enumerate(result):
                if candidate["action"] == "click" and all(
                        any(e == link["from_eid"] for e in candidate["evidence"].get(sid, [])) for (sid, _), link in links.items() if link["from_eid"] and sid in candidate["evidence"]):
                    source = number
                    break
            result.insert(source + 1, {"n": 0, "intent_vi": "Đọc màn hình", "action": "read_fields", "save_as": "kq", "evidence": {}})
            read_added = True
    for number, step in enumerate(result, start=1):
        step["n"] = number
    return {"title": "Việc đã học", "steps": result, "ignored": ignored(trace, result), "questions": [], "overall_confidence": 0.9}


def ignored(trace, steps):
    covered = {e for s in steps for es in s["evidence"].values() for e in es}
    out = []
    for session in trace["sessions"]:
        for event in session["events"]:
            if event["kind"] in ("click", "submit", "change") and event["eid"] not in covered:
                out.append({"eid": event["eid"], "reason": "repeat"})
    return out


def draft(plan):
    steps, inputs = [], []
    for step in plan["steps"]:
        item = {"action": step["action"], "target": {"el_id": step["el_id"]} if step.get("el_id") else None,
                "optional": {"mode": step["optional"]} if step.get("optional") else None}
        if step["action"] in ("fill", "select"):
            kind = step["value_kind"]
            item["value"] = ("{" + step["param_name"] + "}" if kind == "param" else step["const_value"] if kind == "const"
                             else "{" + step["link"]["var"] + "." + step["link"]["path"] + "}")
            if kind == "param":
                inputs.append({"name": step["param_name"], "type": "string", "label": step["intent_vi"]})
        if step["action"] == "read_fields":
            item["save_as"] = step["save_as"]
        steps.append(item)
    return {"title": plan.get("title"), "inputs": inputs, "steps": steps}


def main():
    mode = sys.argv[sys.argv.index("--mode") + 1]
    print("[task] active 1")
    if mode.endswith("design"):
        answer = design(json.load(open("trace.json", encoding="utf-8")))
    else:
        answer = draft(json.load(open("design.json", encoding="utf-8")))
    print(OPEN)
    print(json.dumps(answer, ensure_ascii=False))
    print(CLOSE)


main()
