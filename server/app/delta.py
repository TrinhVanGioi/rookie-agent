"""Delta Learning: teach again only the part of a flow that changed (task 12.5, docs/design.md 15).

A run stopped at a safe point because the system now asks something new (a confirmation box, a new field). The teller records just
that part; it is learned by the same rules as any recording (risk, mode, inputs, postconditions) and put into the flow right after the
step where the run stopped. What the teller then did again of the old flow is the old flow going on, not a new step: the new part ends
at the first step that the flow already has. Every other step stays exactly as it was. The result is a new draft version: it is tried,
and approved by a person, before it is used; the version it was made from does not change.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from app.learner import LearnError, learn, slug
from app.schemas import validate_workflow


class DeltaError(ValueError):
    """The part cannot be put into the flow. The message says why, in plain words."""


def _selectors(step: dict[str, Any]) -> set[str]:
    return set((step.get("target") or {}).get("selectors") or [])


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """The same action on the same element (a selector in common): the step a flow already has."""
    return a.get("action") == b.get("action") and bool(_selectors(a) & _selectors(b))


def splice(workflow: dict[str, Any], after_step: str, sessions: list[list[dict[str, Any]]], version: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """`(new draft, change)`: the steps of the recorded part that the flow does not have, after `after_step`."""
    steps = workflow["steps"]
    place = next((i for i, step in enumerate(steps) if step["id"] == after_step), None)
    if place is None:
        raise DeltaError(f"Không có bước «{after_step}» trong bản này của việc.")
    try:
        part, _ = learn(sessions, workflow["id"], version, workflow.get("title"))
    except LearnError as error:
        raise DeltaError(f"Chưa học được đoạn vừa dạy: {error}") from error
    before, rest = steps[: place + 1], steps[place + 1:]
    added: list[dict[str, Any]] = []
    for step in part["steps"]:
        if any(_same(step, old) for old in rest):
            break                      # the old flow goes on from here
        if any(_same(step, old) for old in before):
            continue                   # a step done again (the search pressed once more): the flow has it
        added.append(step)
    if not added:
        raise DeltaError("Đoạn vừa dạy không có bước nào mới so với việc đã học. Hãy làm đúng phần mới (ví dụ bấm ĐỒNG Ý ở hộp thoại mới) rồi Dừng.")

    names = {item["name"] for item in workflow["inputs"]}
    inputs = list(copy.deepcopy(workflow["inputs"]))
    used_ids = {step["id"] for step in steps}
    renamed: dict[str, str] = {}
    for item in part["inputs"]:
        if not any(f"{{{item['name']}}}" == str(step.get("value") or "") for step in added):
            continue
        name, counter = item["name"], 2
        while name in names:
            name, counter = f"{item['name']}_{counter}", counter + 1
        names.add(name)
        renamed[item["name"]] = name
        inputs.append({**item, "name": name})
    new_steps = []
    for number, step in enumerate(added, start=1):
        fresh = copy.deepcopy(step)
        base = f"d{version}_{number}_{slug((step.get('target') or {}).get('label'), 'buoc')}"[:48]
        candidate, counter = base, 2
        while candidate in used_ids:
            candidate, counter = f"{base}_{counter}", counter + 1
        used_ids.add(candidate)
        fresh["id"] = candidate
        value = str(fresh.get("value") or "")
        match = re.fullmatch(r"\{([a-z][a-z0-9_]*)\}", value)
        if match and match.group(1) in renamed:
            fresh["value"] = f"{{{renamed[match.group(1)]}}}"
        new_steps.append(fresh)

    new = copy.deepcopy(workflow)
    new.update(version=version, status="draft", inputs=inputs, steps=copy.deepcopy(before) + new_steps + copy.deepcopy(rest),
               schema_version=max(int(workflow.get("schema_version") or 1), int(part.get("schema_version") or 1)))
    validate_workflow(new)
    return new, {"op": "teach", "after": after_step, "added": [step["id"] for step in new_steps]}
