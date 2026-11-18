"""The Assistant on the server: rank the approved workflows a teller's sentence may mean (Gate 5, see docs/assistant-design.md).

The request is already masked on the teller's PC: values are slots `{s1}`, words outside the closed vocabulary are `#`. The model, if
any, may only answer with codes of the catalog and parameter names of the catalog; `check_plan_reply` throws away anything else and
the rule-based answer is used. Nothing here decides risk or mode, and nothing here runs anything.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.llm.base import assert_masked

MAX_CANDIDATES = 3
SLOT = re.compile(r"\{s\d+\}")
STOP = frozenset("tra cho toi giup hay lam xem can muon mot cua va la o tai voi nhe a oi ban em anh chi".split())
SYNONYMS = {"tk": ["tai", "khoan"], "stk": ["so", "tai", "khoan"], "sd": ["so", "du"]}
# a slot class fits a parameter whose class is one of these
FITS = {"number": {"account_number", "cif_number", "id_number", "phone", "unclassified", "number", None},
        "amount": {"amount", "unclassified", None}}


def fold(text: str) -> str:
    plain = unicodedata.normalize("NFD", (text or "").replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in plain if unicodedata.category(c) != "Mn").lower()


def tokens(text: str) -> list[str]:
    out: list[str] = []
    for word in re.findall(r"[a-z0-9#]+", fold(SLOT.sub(" ", text or ""))):
        out.extend(SYNONYMS.get(word, [word]))
    return out


def score(text: str, entry: dict[str, Any]) -> float:
    """How well a sentence fits one workflow, from 0 to 1. Plain word matching: it works offline."""
    content = [t for t in tokens(text) if t not in STOP and t != "#"]
    keys = set(tokens(entry.get("title", "")))
    for label in entry.get("step_labels", []):
        keys.update(tokens(label))
    keys.update(fold(k) for k in entry.get("keywords", []))
    if not content or not keys:
        return 0.0
    matched = [t for t in content if t in keys]
    if not matched:
        return 0.0
    precision = len(matched) / len(content)
    title_keys = set(tokens(entry.get("title", "")))
    recall = len(title_keys & set(matched)) / len(title_keys) if title_keys else 0.0
    return round(min(1.0, precision * (0.8 + 0.2 * min(1.0, recall * 2))), 3)


def fit_slots(request: dict[str, Any], entry: dict[str, Any]) -> dict[str, str]:
    """Which parameter gets which slot: only when exactly one parameter fits the class. Two fitting ones are left to the teller."""
    mapping: dict[str, str] = {}
    taken: set[str] = set()
    for slot in request.get("slots", []):
        fitting = [i["name"] for i in entry.get("inputs", []) if i.get("class") in FITS.get(slot["class"], set()) and i["name"] not in taken]
        if len(fitting) == 1:
            mapping[slot["id"]] = fitting[0]
            taken.add(fitting[0])
    return mapping


def rule_plan(request: dict[str, Any]) -> dict[str, Any]:
    ranked = sorted(((score(request["text"], e), e) for e in request["catalog"]), key=lambda pair: (-pair[0], -pair[1].get("habit_runs", 0)))
    candidates = [{"ref": e["ref"], "confidence": s, "slots": fit_slots(request, e)} for s, e in ranked[:MAX_CANDIDATES] if s > 0]
    return {"schema_version": 1, "method": "rule", "fallback_reason": None, "candidates": candidates, "chain": [], "llm": {"calls": []}}


def check_request(request: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(request, dict) or request.get("schema_version") != 1:
        return ["Yêu cầu không đúng dạng."]
    if not isinstance(request.get("text"), str) or not isinstance(request.get("slots"), list) or not isinstance(request.get("catalog"), list):
        return ["Yêu cầu thiếu text, slots hoặc catalog."]
    if len(request["text"]) > 400:
        problems.append("Câu quá dài.")
    for entry in request["catalog"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("ref"), str) or not isinstance(entry.get("title"), str):
            problems.append("Một mục catalog sai dạng.")
            break
    try:
        assert_masked(request)
    except ValueError as error:
        problems.append(str(error))
    return problems


def check_plan_reply(request: dict[str, Any], reply: Any) -> list[str]:
    """What the model may say: refs and parameter names that were sent, slots that were sent, at most 3, `chain` empty."""
    if not isinstance(reply, dict) or not isinstance(reply.get("candidates"), list):
        return ["Trả lời không có danh sách ứng viên."]
    entries = {e["ref"]: e for e in request["catalog"]}
    slots = {s["id"]: s["class"] for s in request["slots"]}
    problems: list[str] = []
    if len(reply["candidates"]) > MAX_CANDIDATES or reply.get("chain"):
        problems.append("Quá 3 ứng viên hoặc có chuỗi.")
    for item in reply["candidates"]:
        entry = entries.get(item.get("ref")) if isinstance(item, dict) else None
        confidence = item.get("confidence") if isinstance(item, dict) else None
        if entry is None or not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            problems.append("Ứng viên sai mã hoặc sai độ tin cậy.")
            continue
        names = {i["name"]: i.get("class") for i in entry.get("inputs", [])}
        for slot_id, name in (item.get("slots") or {}).items():
            if slot_id not in slots or name not in names or names[name] not in FITS.get(slots[slot_id], set()):
                problems.append("Ghép giá trị vào tham số không hợp lệ.")
    return problems


def plan(request: dict[str, Any], client: Any = None) -> dict[str, Any]:
    """The rules always run; a model answer is used only when it passes the check, and when it disagrees with the rules both are shown."""
    ruled = rule_plan(request)
    ask = getattr(client, "plan_request", None)
    if ask is None:
        return ruled
    try:
        said = ask(request)
    except Exception as error:   # a model failing never stops the Assistant
        return {**ruled, "fallback_reason": f"Mô hình không trả lời được: {error}"[:200]}
    problems = check_plan_reply(request, said)
    if problems:
        return {**ruled, "fallback_reason": "Câu trả lời của mô hình không hợp lệ: " + problems[0]}
    top_rule = ruled["candidates"][0]["ref"] if ruled["candidates"] else None
    top_model = said["candidates"][0]["ref"] if said["candidates"] else None
    if top_rule != top_model:        # disagreement: the teller chooses between both
        merged: list[dict[str, Any]] = []
        for item in said["candidates"] + ruled["candidates"]:
            if item["ref"] not in {m["ref"] for m in merged}:
                merged.append({**item, "confidence": min(item["confidence"], 0.79)})
        return {**said, "candidates": merged[:MAX_CANDIDATES], "method": "llm", "fallback_reason": None}
    return {**said, "method": "llm", "fallback_reason": None}
