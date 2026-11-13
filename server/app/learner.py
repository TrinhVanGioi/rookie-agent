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

from app.risk import mode_for, risk_of
from app.schemas import validate_workflow

RECOMMENDED_SESSIONS = 3
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
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
    """Merge repeated edits of one field and drop a click repeated on the same element."""
    result: list[dict[str, Any]] = []
    for event in sorted(events, key=lambda item: item["seq"]):
        if result and _key(result[-1]) == _key(event) and event["type"] in ("input", "select", "click"):
            if event["type"] != "click":
                result[-1] = event  # the last value typed is the one that counts
            continue
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
    sessions: list[list[dict[str, Any]]], workflow_id: str, version: int = 1
) -> tuple[dict[str, Any], list[str]]:
    """Return (workflow in `draft`, warnings)."""
    if not sessions or any(not events for events in sessions):
        raise LearnError("Cần ít nhất một phiên ghi có sự kiện.")
    engines = {event["engine"] for events in sessions for event in events}
    if len(engines) != 1:
        raise LearnError("Các phiên ghi phải cùng một hướng (web hoặc java).")
    engine = engines.pop()

    runs = [normalize(events) for events in sessions]
    warnings: list[str] = []
    if len(runs) < RECOMMENDED_SESSIONS:
        warnings.append(
            f"Chỉ có {len(runs)} phiên ghi; nên ghi ít nhất {RECOMMENDED_SESSIONS} lần với dữ liệu khác nhau."
        )

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

    for index in range(len(reference)):
        column = [run[index] for run in runs]
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
                step["action"] = "click"
            else:
                step["action"] = "fill" if first["type"] == "input" else "select"
                classes = [event["value_class"] for event in column if event["value_class"]]
                values = [event["value"] for event in column]
                if classes or len(set(values)) > 1 or len(runs) == 1:
                    name = unique(slug(label), used_names)
                    item: dict[str, Any] = {"name": name, "type": _value_type(values)}
                    if classes:
                        item["value_class"] = classes[0]
                    elif len(runs) == 1:
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
        steps.append(step)

    if not steps:
        raise LearnError("Không còn bước nào agent được phép thực hiện trong các phiên ghi này.")

    workflow = {
        "schema_version": 1,
        "engine": engine,
        "id": workflow_id,
        "version": version,
        "status": "draft",
        "inputs": inputs,
        "steps": steps,
    }
    validate_workflow(workflow)
    return workflow, warnings
