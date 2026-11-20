"""Rule-based Learner: turn a few recordings of the same task into one workflow (docs/design.md 5).

Steps 1, 2 and 4 of the design: normalize, align the sessions, assign risk by
rule. Nothing here is specific to a business function: the same code learns a
reconciliation, a CIF lookup or a transfer, on either engine.

The Learner only generalizes what it has seen. Sessions that do not follow the
same sequence of steps are refused rather than merged by guessing.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.align import align, present, reordered
from app.risk import mode_for, risk_of
from app.schemas import validate_workflow

RECOMMENDED_SESSIONS = 3
MIN_SHARED = 0.6   # the steps every recording has must be at least this part of the longest recording: else it is not one task
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{2}/\d{2}/\d{4}$|^\d{2}-\d{2}-\d{4}$")   # ISO, or the day/month/year a calendar writes
_NUMBER = re.compile(r"^-?\d+([.,]\d+)?$")


class LearnError(ValueError):
    """The sessions cannot be turned into a workflow. The message says why."""


def slug(text: str | None, fallback: str = "gia_tri") -> str:
    """`Tài khoản chuyển` -> `tai_khoan_chuyen`. Always a valid input name."""
    text = (text or "").replace("đ", "d").replace("Đ", "D")
    ascii_text = unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")
    if not name:
        return fallback
    return name if name[0].isalpha() else f"p_{name}"


def _key(event: dict[str, Any]) -> tuple[str, str]:
    target = event.get("target")
    return event["type"], target["selectors"][0] if target else event.get("url", "")


def normalize(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge repeated edits of one field and drop a click repeated on the same element.

    A field edited again with only other fields edited in between (the user name typed, the branch typed, the user name
    corrected) is one step, at the place of its first edit, with the last value. A click, a submit or a page change between
    the two edits closes that: the page may have changed, so both edits stay.
    """
    result: list[dict[str, Any]] = []
    edited: dict[tuple[str, str], int] = {}  # field -> its place in result, since the last click, submit or page change
    for event in sorted(events, key=lambda item: item["seq"]):
        kind = event["type"]
        if result and _key(result[-1]) == _key(event) and kind in ("input", "select", "click"):
            if kind != "click":
                result[-1] = event  # the last value typed is the one that counts
            continue
        if kind in ("input", "select"):
            place = edited.get(_key(event))
            if place is not None:
                result[place] = event
                continue
            edited[_key(event)] = len(result)
        else:
            edited.clear()
        result.append(event)
    return result


def _value_type(values: list[str | None]) -> str:
    known = [value for value in values if value is not None]
    if known and all(_DATE.match(value) for value in known):
        return "date"
    if known and all(_NUMBER.match(value) for value in known):
        return "number"
    return "string"


def _describe(event: dict[str, Any]) -> str:
    label = (event.get("target") or {}).get("label") or event.get("url") or "?"
    return f"{event['type']} «{label}»"


def learn(
    sessions: list[list[dict[str, Any]]], workflow_id: str, version: int = 1, title: str | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Return (workflow in `draft`, warnings)."""
    if not sessions or any(not events for events in sessions):
        raise LearnError("Cần ít nhất một phiên ghi có sự kiện.")
    engines = {event["engine"] for events in sessions for event in events}
    if len(engines) != 1:
        raise LearnError("Các phiên ghi phải cùng một hướng (web, java hoặc ie).")
    engine = engines.pop()

    runs = [normalize(events) for events in sessions]
    warnings: list[str] = []
    if len(runs) < RECOMMENDED_SESSIONS:
        warnings.append(
            f"Chỉ có {len(runs)} phiên ghi; nên ghi ít nhất {RECOMMENDED_SESSIONS} lần với dữ liệu khác nhau."
        )

    if engine == "ie":
        columns = _line_up(runs)
    else:
        # Align: every session must be the same sequence of actions on the same elements.
        reference = [_key(event) for event in runs[0]]
        for number, run in enumerate(runs[1:], start=2):
            keys = [_key(event) for event in run]
            if keys != reference:
                position = next(
                    (i for i, (a, b) in enumerate(zip(reference, keys)) if a != b), min(len(reference), len(keys))
                )
                first = _describe(runs[0][position]) if position < len(runs[0]) else "(hết bước)"
                other = _describe(run[position]) if position < len(run) else "(hết bước)"
                raise LearnError(
                    f"Phiên ghi {number} khác phiên 1 ở bước {position + 1}: {other} so với {first}. "
                    "Learner chưa học được quy trình có nhánh; hãy ghi lại các phiên theo cùng trình tự."
                )
        columns = [[run[index] for run in runs] for index in range(len(reference))]

    inputs: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    used_names: set[str] = set()
    used_ids: set[str] = set()

    def unique(name: str, used: set[str]) -> str:
        candidate, counter = name, 2
        while candidate in used:
            candidate, counter = f"{name}_{counter}", counter + 1
        used.add(candidate)
        return candidate

    optional_steps: list[str] = []
    # task 12.1 (SADPT): recordings that say what the screen showed after each action give a version 4 flow, whose steps carry their
    # business intent, a postcondition and an adaptation policy. Older recordings are learned exactly as before.
    adaptive = engine == "ie" and any("shows" in event for run in runs for event in run)
    for index, cells in enumerate(columns):
        column = present(cells)
        sometimes = len(column) < len(runs)      # a step that not every recording has
        first = column[0]
        target = first.get("target")
        label = (target or {}).get("label")
        risk = max((risk_of(event) for event in column), key=lambda r: ({"read": 0, "write": 1, "money": 2}[r.level], r.human_only))

        if risk.human_only:
            warnings.append(
                f"Bước {index + 1} ({_describe(first)}) chỉ người được thực hiện. "
                "Workflow dừng trước bước này; các bước sau không được đưa vào."
            )
            break

        step: dict[str, Any] = {"id": unique(f"s{index + 1}_{slug(label, 'buoc')}"[:48], used_ids)}
        if first["type"] == "navigate":
            step.update(action="goto", url=first["url"])
        else:
            selectors: list[str] = []
            for event in column:
                for selector in event["target"]["selectors"]:
                    if selector not in selectors:
                        selectors.append(selector)
            step["target"] = {"selectors": selectors, "label": label, "tag": target.get("tag")}
            if first["type"] in ("click", "submit"):
                step["action"] = "click" if first["type"] == "click" else "submit"
            else:
                step["action"] = "fill" if first["type"] == "input" else "select"
                classes = [event["value_class"] for event in column if event["value_class"]]
                values = [event["value"] for event in column]
                if classes or len(set(values)) > 1 or len(column) == 1 or sometimes:
                    name = unique(slug(label), used_names)
                    item: dict[str, Any] = {"name": name, "type": _value_type(values)}
                    if sometimes:
                        item["required"] = False
                    if label:
                        item["label"] = label  # what the GDV sees on screen, shown instead of the name
                    if classes:
                        item["value_class"] = classes[0]
                    elif len(column) == 1 and not sometimes:
                        warnings.append(
                            f"«{label}» chỉ có một giá trị mẫu nên được coi là tham số {{{name}}}; "
                            "ghi thêm phiên để biết đây là tham số hay hằng số."
                        )
                    inputs.append(item)
                    step["value"] = f"{{{name}}}"
                else:
                    step["value"] = values[0] or ""
        step["risk"] = risk.level
        step["mode"] = mode_for(risk.level)
        if adaptive:
            _adapt_step(step, column, label)
        if sometimes:
            step["optional"] = _optional_of(first, step, risk.level, len(column), len(runs), warnings)
            optional_steps.append(step["id"])
        steps.append(step)

    if not steps:
        raise LearnError("Không còn bước nào agent được phép thực hiện trong các phiên ghi này.")

    workflow = {
        "schema_version": (4 if adaptive else 3 if optional_steps else 2) if engine == "ie" else 1,
        "engine": engine,
        "id": workflow_id,
        "version": version,
        "status": "draft",
        "inputs": inputs,
        "steps": steps,
    }
    if title:
        workflow["title"] = title  # the name the GDV gave this agent
    validate_workflow(workflow)
    return workflow, warnings


def _adapt_step(step: dict[str, Any], column: list[dict[str, Any]], label: str | None) -> None:
    """Task 12.1: the semantic part of a step (docs/design.md 15).

    - `intent`: what a press does, in the words of the screen (its label).
    - `expect`: what every recording showed right after the action (frame, kind, name; no value). What only some showed (a clock, a
      message by chance) is not expected. A recording without `shows` says nothing either way.
    - `adapt.reresolve`: only a read step may have its target found again by the agent when the screen changed; it is checked after.
    """
    if step.get("action") in ("click", "submit") and label:
        step["intent"] = label[:80]
    known = [event["shows"] for event in column if isinstance(event.get("shows"), list)]
    if known:
        key = lambda item: (item["frame"], item["kind"], item["name"])   # noqa: E731
        common = set.intersection(*({key(item) for item in shows} for shows in known))
        appears = [item for item in known[0] if key(item) in common]
        if appears:
            step["expect"] = {"appears": [{"frame": f, "kind": k, "name": n} for f, k, n in dict.fromkeys(key(i) for i in appears)][:20]}
    step["adapt"] = {"reresolve": step["risk"] == "read"}


def with_adaptation(workflow: dict[str, Any], sessions: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """Task 12.1: a flow built another way (by the model) gets the intent, postcondition and adaptation policy the rules learn from the
    same recordings, step by step, matched by a selector they share. The flow's own risk and mode stay; `adapt` follows them. Recordings
    without `shows`, or that the rules cannot line up, leave the flow as it is."""
    if workflow.get("engine") != "ie" or not any("shows" in event for events in sessions for event in events):
        return workflow
    try:
        ruled, _ = learn(sessions, workflow["id"], workflow.get("version", 1), workflow.get("title"))
    except LearnError:
        return workflow
    by_selector = {selector: step for step in ruled["steps"] for selector in (step.get("target") or {}).get("selectors", [])}
    for step in workflow["steps"]:
        twin = next((by_selector[s] for s in (step.get("target") or {}).get("selectors", []) if s in by_selector), None)
        if twin is not None:
            step.update({key: twin[key] for key in ("intent", "expect") if key in twin})
        step["adapt"] = {"reresolve": step["risk"] == "read"}
    workflow["schema_version"] = 4
    validate_workflow(workflow)
    return workflow


def _line_up(runs: list[list[dict[str, Any]]]) -> list[list[dict[str, Any] | None]]:
    """The recordings of an Internet Explorer task lined up, one column per action, with gaps where a recording lacks it."""
    if len(runs) == 1:
        return [[event] for event in runs[0]]
    columns = align(runs, _key)
    moved = reordered(columns, _key)
    if moved:
        marker, one, other = moved[0]
        label = next((c for col in columns for c in col if c is not None and str(_key(c)) == marker), None)
        raise LearnError(
            f"Các lần ghi làm cùng thao tác «{_describe(label) if label else marker}» nhưng theo thứ tự khác nhau (lần {one + 1} và lần {other + 1}). "
            "Learner không đoán thứ tự; hãy ghi lại các lần theo cùng trình tự."
        )
    shared = sum(1 for column in columns if len(present(column)) == len(runs))
    longest = max(len(run) for run in runs)
    if shared < MIN_SHARED * longest:
        raise LearnError("Các lần ghi giống nhau quá ít nên không phải cùng một việc. Hãy ghi lại cùng một việc, cùng trình tự.")
    return columns


def _optional_of(first: dict[str, Any], step: dict[str, Any], risk: str, seen: int, total: int, warnings: list[str]) -> dict[str, Any]:
    """What a step that only some recordings have means. A step that writes or moves money is never made optional."""
    label = (first.get("target") or {}).get("label") or step["id"]
    if risk != "read":
        raise LearnError(
            f"Bước «{label}» ghi dữ liệu hoặc chuyển tiền nhưng chỉ có ở {seen}/{total} lần ghi. "
            "Agent không học bước ghi hay bước tiền là tuỳ chọn; hãy ghi lại các lần theo cùng trình tự."
        )
    if step["action"] in ("fill", "select"):
        mode = "if_different"
    elif step["action"] == "click":
        mode = "if_present"
    else:
        raise LearnError(f"Bước «{label}» ({step['action']}) chỉ có ở {seen}/{total} lần ghi và không thể là bước tuỳ chọn. Hãy ghi lại cùng trình tự.")
    warnings.append(f"Bước «{label}» chỉ có ở {seen}/{total} lần ghi nên được học là bước tuỳ chọn.")
    if total == 2:
        warnings.append(f"Mới có 2 lần ghi nên chưa chắc bước «{label}» thật sự tuỳ chọn; nên ghi thêm một lần.")
    return {"mode": mode}
