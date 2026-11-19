"""What the Assistant may choose from: the approved agents of this PC, described without any value (design 2.1)."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

RISK_ORDER = {"read": 0, "write": 1, "money": 2}
MAX_LABELS = 8
LONG_DIGITS = re.compile(r"\d{6,}")


def fold(text: str) -> str:
    plain = unicodedata.normalize("NFD", (text or "").replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in plain if unicodedata.category(c) != "Mn").lower()


def sanitize_label(text: Any) -> str:
    """A label from a page or a title is data, not an instruction: one line, short, no long numbers."""
    one = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", str(text or "")).split())[:60]
    return LONG_DIGITS.sub("#", one)


def input_class(item: dict[str, Any]) -> str | None:
    """The kind of value a parameter takes, from its declared class or, failing that, from its name and label."""
    declared = item.get("value_class") or item.get("class")
    if declared and declared != "unclassified":
        return str(declared)
    words = fold(f"{item.get('name', '')} {item.get('label', '')}").replace("_", " ")
    if re.search(r"so tien|amount|\bsotien\b", words):
        return "amount"
    if re.search(r"tai khoan|\bstk\b|account|\bcif\b|cccd|cmnd|dien thoai|phone", words):
        return "account_number"
    return None


def risk_max(workflow: dict[str, Any]) -> str:
    risks = [str(s.get("risk") or "read") for s in workflow.get("steps", [])]
    return max(risks, key=lambda r: RISK_ORDER.get(r, 2), default="read")


def build_catalog(flows: list[dict[str, Any]], habit_runs: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Approved agents of the Internet Explorer engine, coded w1..wn. The default value of a parameter is never part of it."""
    entries: list[dict[str, Any]] = []
    for flow in flows:
        workflow = flow.get("workflow") or {}
        if workflow.get("status") != "approved" or workflow.get("engine") != "ie":
            continue
        title = sanitize_label(flow.get("title"))
        labels = [sanitize_label((s.get("target") or {}).get("label") or s.get("title")) for s in workflow.get("steps", [])]
        entries.append({
            "ref": f"w{len(entries) + 1}", "title": title, "risk_max": risk_max(workflow),
            "inputs": [{"name": i["name"], "label": sanitize_label(i.get("label") or i["name"]), "class": input_class(i),
                        "required": i.get("default") is None, "has_default": i.get("default") is not None} for i in workflow.get("inputs", [])],
            "step_labels": [x for x in labels if x][:MAX_LABELS], "keywords": [],
            "habit_runs": int((habit_runs or {}).get(flow.get("title") or "", 0)), "_flow_title": flow.get("title"),
            # what only this PC uses to fill inputs from the sentence: the type, and the format of the example the teller recorded (never sent)
            "_local_inputs": [{"name": i["name"], "label": str(i.get("label") or i["name"]), "type": i.get("type"),
                               "format": (flow.get("input_formats") or {}).get(i["name"])} for i in workflow.get("inputs", [])],
        })
    return entries


def for_server(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The entries as sent: without our private keys; at most 20."""
    return [{k: v for k, v in e.items() if not k.startswith("_")} for e in entries[:20]]


def vocabulary(entries: list[dict[str, Any]]) -> set[str]:
    words: set[str] = set()
    for entry in entries:
        text = " ".join([entry["title"], *entry["step_labels"], *[i["label"] for i in entry["inputs"]]])
        words.update(re.findall(r"[a-z0-9]+", fold(text)))
    return words
