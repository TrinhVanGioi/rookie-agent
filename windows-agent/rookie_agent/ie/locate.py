"""Which element of an Internet Explorer page does a step mean? (docs/runner-ie-design.md 7)

Pure functions, no page, no LLM. The recorder writes several selectors for one element (id, name, label, position); at
run time each is looked up in the page and the sets of elements found are weighed here as evidence. The runner acts only
on enough evidence, and otherwise stops and asks the teller: it never picks one of several look-alikes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Enough evidence to act: reading is harmless, writing and money need stronger proof.
THRESHOLD = {"read": 0.8, "write": 0.9, "money": 0.9}
STRONG = ("id", "name", "label")
BASE = {"id": 1.0, "name": 0.9, "label": 0.8}
INTERSECT_SCORE = 0.8
POSITION_ONLY_SCORE = 0.5
AGREE_BONUS = 0.1
DISAGREE_PENALTY = 0.2

_POS = re.compile(r"^([a-z0-9]+)\[(\d+)\]$")


def parse_selector(selector: str):
    """`frame=<path>|id=x` and the like -> (kind, frame, value, n); a selector without `frame=` has frame None.
    kind is id, name, label or pos (then value is the tag and n the position). Anything else -> None."""
    text = (selector or "").strip()
    frame = None
    if text.startswith("frame="):
        frame, bar, text = text[len("frame="):].partition("|")
        if not bar or not frame:
            return None
    for kind in ("id", "name", "label"):
        if text.startswith(kind + "="):
            value = text[len(kind) + 1:]
            return (kind, frame, value, None) if value else None
    found = _POS.match(text)
    if found:
        return ("pos", frame, found.group(1), int(found.group(2)))
    return None


def group_selectors(selectors: list[str]):
    """The selectors of one step as (frame, [(kind, value, n)]). Every test is looked up in one frame: the frame of the
    first selector that names one ("top" when none does); a selector of another frame is left out."""
    parsed = [p for p in (parse_selector(s) for s in selectors) if p is not None]
    frame = next((p[1] for p in parsed if p[1]), "top")
    return frame, [(kind, value, n) for kind, f, value, n in parsed if f in (None, frame)]


@dataclass
class Probe:
    """One selector looked up in the page: its kind and the elements (by uid) that matched."""

    kind: str
    matches: list[int]


@dataclass
class Result:
    state: str  # ok, not_found, ambiguous, low_confidence
    uid: int | None = None
    how: str | None = None
    score: float = 0.0
    counts: list[int] = field(default_factory=list)


def choose(probes: list[Probe], elements: dict[int, dict], want: str, risk: str) -> Result:
    """`elements[uid]` says whether the element is a `field` and/or `press`able; `want` is field, press or any."""
    counts = [len(p.matches) for p in probes]
    if not any(counts):
        return Result("not_found", counts=counts)

    uid = how = own = None
    score = 0.0
    for index, probe in enumerate(probes):  # a strong selector that points at exactly one element
        if probe.kind in STRONG and len(probe.matches) == 1:
            uid, how, own, score = probe.matches[0], probe.kind, index, BASE[probe.kind]
            break
    if uid is None:
        filled = [set(p.matches) for p in probes if p.matches]
        common = set.intersection(*filled)
        if len(filled) >= 2 and len(common) == 1:  # a duplicate id told apart by the position
            uid, how, score = next(iter(common)), "intersect", INTERSECT_SCORE
        else:
            by_position = [i for i, p in enumerate(probes) if p.kind == "pos" and len(p.matches) == 1]
            if by_position and not any(p.matches for p in probes if p.kind in STRONG):
                own = by_position[0]
                uid, how, score = probes[own].matches[0], "pos", POSITION_ONLY_SCORE
    if uid is None:
        return Result("ambiguous", counts=counts)

    for index, probe in enumerate(probes):  # the other selectors vote (an intersection has no chosen selector: no vote)
        if how != "intersect" and index != own and probe.matches:
            score += AGREE_BONUS if uid in probe.matches else -DISAGREE_PENALTY
    score = round(min(1.0, max(0.0, score)), 2)

    info = elements.get(uid, {})
    if (want == "field" and not info.get("field")) or (want == "press" and not info.get("press")):
        score = 0.0
    if score < THRESHOLD.get(risk, THRESHOLD["write"]):
        return Result("low_confidence", uid, how, score, counts)
    return Result("ok", uid, how, score, counts)
