"""Mask a sentence on this PC before anything leaves it (design 3): values become slots, words outside the closed vocabulary become `#`."""

from __future__ import annotations

import re
from typing import Any

from rookie_agent.assistant.catalog import fold

# Words every sentence about the job uses; names of people are never among them.
FUNCTION_WORDS = frozenset("""tra cho toi giup hay lam xem can muon mot cua va la o tai voi nhe so du tk stk tien chuyen
khoan van tin tai khoan kiem tim doi chieu bao cao khach hang cif thong sau den tu ve""".split())
AMOUNT = re.compile(r"\b\d+(?:[.,]\d+)*\s*(?:trieu|tr|ty|nghin|ngan|k|dong|d|vnd)\b|\b\d{1,3}(?:[.,]\d{3})+\b", re.IGNORECASE)
NUMBER = re.compile(r"\b\d{6,}\b")
MAX_TEXT = 300


def extract_slots(text: str) -> tuple[str, list[dict[str, str]], dict[str, str]]:
    """The sentence with `{s1}` in place of each value, the slot list (id and class only) and the values (stay in memory)."""
    folded = fold(text)[:MAX_TEXT]
    found: list[tuple[int, int, str]] = []
    for match in AMOUNT.finditer(folded):
        found.append((match.start(), match.end(), "amount"))
    for match in NUMBER.finditer(folded):
        if not any(a <= match.start() < b for a, b, _ in found):
            found.append((match.start(), match.end(), "number"))
    found.sort()
    out, slots, values, cursor = [], [], {}, 0
    for start, end, kind in found:
        out.append(folded[cursor:start])
        slot_id = f"s{len(slots) + 1}"
        out.append(" {" + slot_id + "} ")
        slots.append({"id": slot_id, "class": kind})
        values[slot_id] = folded[start:end].strip() if kind == "amount" else text_digits(text, folded, start, end)
        cursor = end
    out.append(folded[cursor:])
    return "".join(out), slots, values


def text_digits(original: str, folded: str, start: int, end: int) -> str:
    return re.sub(r"\D", "", folded[start:end])


def amount_digits(value: str) -> str:
    """'5 trieu' -> 5000000, '5.000.000' -> 5000000; anything else is left for the teller to type."""
    match = re.match(r"(\d+(?:[.,]\d+)*)\s*([a-z]*)$", value.strip())
    if not match:
        return ""
    number, unit = match.groups()
    unit_factor = {"trieu": 10**6, "tr": 10**6, "ty": 10**9, "nghin": 10**3, "ngan": 10**3, "k": 10**3, "": 1, "dong": 1, "d": 1, "vnd": 1}.get(unit)
    if unit_factor is None:
        return ""
    if unit_factor == 1 and re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", number):
        return re.sub(r"\D", "", number)
    try:
        return str(int(round(float(number.replace(",", ".")) * unit_factor)))
    except ValueError:
        return ""


def mask_text(text: str, vocabulary: set[str]) -> str:
    """Keep slots and words of the closed vocabulary; every other word becomes `#`."""
    known = vocabulary | FUNCTION_WORDS
    out: list[str] = []
    for word in text.split():
        word = word.strip(".,?!;:\"'()")
        if not word:
            continue
        out.append(word if re.fullmatch(r"\{s\d+\}", word) or word in known else "#")
    return " ".join(out)


def prepare(text: str, vocabulary: set[str]) -> dict[str, Any]:
    with_slots, slots, values = extract_slots(text)
    return {"text": mask_text(" ".join(with_slots.split()), vocabulary), "slots": slots, "values": values}
