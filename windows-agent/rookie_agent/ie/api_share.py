"""The API nodes of a flow as the server may keep them (task 10.3; docs/design.md 13).

The full templates stay on this PC. What goes up:
- only the fields in FIELDS (never the recorded answer, its shape or anything added later);
- every piece of url, body and headers that looks like data masked as `•••`: three digits or more, a space inside, `+` or an
  encoded space, a letter outside ASCII (raw or percent-encoded), or longer than 40 characters. A customer name that came from an
  answer and was not turned into a link would otherwise be in the template as it was. Marks `⟦…⟧` and names of services stay;
- a link found by the text around it goes without that text (it is a piece of an answer).

The server checks with the same rule (server/app/api_nodes.py). A node whose template was masked cannot have its template edited
on the server; when the PC takes a version edited on the server, the full templates are taken back from this PC by node id (task 10.7).
"""

from __future__ import annotations

import re
from typing import Any

FIELDS = ("id", "step_id", "group", "group_label", "label", "kind", "via", "file", "dialog", "frame", "method", "url", "headers", "body",
          "links", "risk", "complete", "unresolved", "ms")
MASK = "•••"
_SPLIT = re.compile(r"""([|&=,;:"'{}\[\]<>()\\\r\n\t/?])""")
_MARK = re.compile(r"(⟦[^⟧]*⟧|•••)")


def _looks_like_data(piece: str) -> bool:
    text = piece.strip()
    if not text:
        return False
    return (len(re.findall(r"\d", text)) >= 3 or re.search(r"\s|\+|%20|%[89A-Fa-f][0-9A-Fa-f]", text) is not None
            or any(ord(c) > 127 for c in text) or len(text) > 40)


def mask_text(text: str) -> tuple[str, int]:
    """`text` with each piece that looks like data replaced by •••, and how many were."""
    count = 0
    out: list[str] = []
    for part in _SPLIT.split(text or ""):
        if _SPLIT.fullmatch(part):
            out.append(part)
            continue
        pieces = _MARK.split(part)
        for index, piece in enumerate(pieces):
            if index % 2 == 0 and _looks_like_data(piece):
                lead = piece[: len(piece) - len(piece.lstrip())]
                trail = piece[len(piece.rstrip()):]
                pieces[index] = lead + MASK + trail
                count += 1
        out.append("".join(pieces))
    return "".join(out), count


def _link(rule: dict[str, Any]) -> dict[str, Any]:
    if "before" in rule or "after" in rule:
        return {"from": rule.get("from"), "text": True}
    return {k: v for k, v in rule.items() if k in ("from", "json", "gwt", "whole")}


_RANK = {"read": 0, "write": 1, "money": 2}


def merge(local: list[dict[str, Any]], server: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A version edited on the admin page, made runnable on this PC (task 10.7): the order, groups, labels, risk and Duyệt come from the
    server; the full templates, links and the shape of the answer of a recorded node come from this PC, matched by node id.

    - A node the server could see whole (`masked` 0) takes the server's templates (they may have been edited there).
    - A node masked on the way up keeps this PC's templates (the server could not change them).
    - A node added on the server has no recorded answer: the twin answers it empty.
    - A recorded node this PC does not have (learned on another PC) cannot be sent from here: it is marked incomplete.
    - Risk only goes up. A node the server dropped is dropped."""
    mine = {n["id"]: n for n in local}
    out = []
    for node in server:
        here = mine.get(node["id"])
        if node.get("added") or here is None:
            made = {**node, "answer": "", "shape": None}
            if not node.get("added") and node.get("masked"):
                made["complete"] = False      # its full template is on the PC that recorded it
            out.append(made)
            continue
        made = dict(here)
        for key in ("group", "group_label", "label", "step_id"):
            if key in node:
                made[key] = node[key]
        if _RANK.get(str(node.get("risk")), 0) > _RANK.get(str(here.get("risk")), 0):
            made["risk"] = node["risk"]
        if node.get("mode"):
            made["mode"] = node["mode"]
        if not node.get("masked"):
            for key in ("method", "url", "headers", "body"):
                if key in node:
                    made[key] = node[key]
            if "unresolved" in node:
                made["unresolved"] = list(node["unresolved"])
        out.append(made)
    return out


def for_server(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for node in nodes:
        sent = {k: node[k] for k in FIELDS if k in node}
        masked = 0
        for key in ("url", "headers", "body"):
            if key in sent:
                sent[key], count = mask_text(str(sent[key]))
                masked += count
        sent["links"] = {name: _link(rule) for name, rule in (node.get("links") or {}).items()}
        sent["masked"] = masked
        out.append(sent)
    return out
