"""Kho luồng: the agents of this PC that are approved and have finished a real run, shown as cards (docs/design.md 6.4).

Local to this PC. A card holds names, counts and a made-up example sentence: never a value a teller typed or a page answered.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from rookie_agent.assistant import slots

COUNTED_MODES = ("run", "simulate")          # a trial (dry), a twin run and a repair are not a run of the agent
RISK_SENTENCE = {"read": "Chỉ xem, không ghi gì vào hệ thống.", "write": "Có bước ghi, luôn dừng chờ bạn Duyệt.",
                 "money": "Có bước tiền, luôn dừng chờ người kiểm soát Duyệt."}
RISK_ORDER = {"read": 0, "write": 1, "money": 2}


def finished_runs(audit_path: Path) -> dict[str, str]:
    """{title: time of its last finished run} from the audit log."""
    last: dict[str, str] = {}
    try:
        lines = audit_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return last
    for text in lines:
        try:
            line = json.loads(text)
        except ValueError:
            continue
        if line.get("status") == "finished" and line.get("mode") in COUNTED_MODES and line.get("title"):
            when = str(line.get("time") or "")
            if when >= last.get(line["title"], ""):
                last[line["title"]] = when
    return last


def eligible(flow: dict[str, Any]) -> bool:
    workflow = flow.get("workflow") or {}
    return workflow.get("status") == "approved" and workflow.get("engine") == "ie"


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " và " + names[-1]


def card(raw: dict[str, Any], listed: dict[str, Any], last_run: str, today: date | None = None) -> dict[str, Any]:
    """What a card shows besides the flow itself: a plain sentence, the inputs by their friendly names, counts, last run, an example to ask."""
    workflow = raw.get("workflow") or {}
    api = listed.get("api_nodes") or []
    labels = [str(i.get("label") or i["name"]) for i in workflow.get("inputs", [])]
    risk = max((str(s.get("risk") or "read") for s in workflow.get("steps", [])), key=lambda r: RISK_ORDER.get(r, 2), default="read")
    returns_file = any(n.get("kind") == "file" for n in raw.get("api") or [])
    start = f"Bạn nhập {_join(labels)}, " if labels else "Không cần nhập gì, "
    sentence = (start + "agent làm lại các bước đã học và " + ("lưu file kết quả về máy này. " if returns_file else "hiện dữ liệu trả về. ")
                + RISK_SENTENCE.get(risk, RISK_SENTENCE["write"]))
    inputs = [{"name": i["name"], "label": str(i.get("label") or i["name"]), "format": (raw.get("input_formats") or {}).get(i["name"]) or ""}
              for i in workflow.get("inputs", [])]
    example = slots.example_sentence(str(raw.get("title") or ""), [{**i, "type": next((x.get("type") for x in workflow.get("inputs", []) if x["name"] == i["name"]), None)} for i in inputs],
                                     today or date.today())
    return {"summary": sentence, "input_labels": labels, "steps_n": len(api) or int(listed.get("step_count") or 0),
            "calls_n": sum(int(n.get("call_count") or 0) for n in api), "last_run": last_run, "example": example,
            "returns_file": returns_file, "risk_max": risk}
