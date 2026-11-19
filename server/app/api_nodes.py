"""The API nodes of a flow on the server (task 10.3; docs/design.md 13).

The PC masks every template piece that looks like data before sending (windows-agent/rookie_agent/ie/api_share.py). The server checks
with the same rule and refuses a node that still has one: a customer name, a number, a date must not be kept here. The rule:
a piece between delimiters (outside the marks ⟦…⟧ and •••) looks like data when it has three digits or more, a space inside, `+` or an
encoded space, a letter outside ASCII (raw or percent-encoded), or more than 40 characters.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.schemas import SchemaError, validate_api_nodes

_SPLIT = re.compile(r"""([|&=,;:"'{}\[\]<>()\\\r\n\t/?])""")
_MARK = re.compile(r"(⟦[^⟧]*⟧|•••)")


def _looks_like_data(piece: str) -> bool:
    text = piece.strip()
    if not text:
        return False
    return (len(re.findall(r"\d", text)) >= 3 or re.search(r"\s|\+|%20|%[89A-Fa-f][0-9A-Fa-f]", text) is not None
            or any(ord(c) > 127 for c in text) or len(text) > 40)


def data_pieces(text: str) -> int:
    count = 0
    for part in _SPLIT.split(text or ""):
        if _SPLIT.fullmatch(part):
            continue
        count += sum(1 for index, piece in enumerate(_MARK.split(part)) if index % 2 == 0 and _looks_like_data(piece))
    return count


def check(nodes: Any) -> None:
    """Raises SchemaError (a message safe to show) when the nodes do not match the schema or a template still looks like it has data."""
    validate_api_nodes(nodes)
    for node in nodes:
        for key in ("url", "headers", "body"):
            if data_pieces(str(node.get(key) or "")):
                raise SchemaError(f"Nút «{node['label']}»: {key} có đoạn giống dữ liệu (số, tên, ngày). Thay bằng ô nhập ⟦tên⟧.")


def digest(nodes: list[dict[str, Any]] | None) -> str | None:
    if nodes is None:
        return None
    canonical = json.dumps(nodes, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
