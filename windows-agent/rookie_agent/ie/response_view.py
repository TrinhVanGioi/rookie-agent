"""Task 7.4: what a request sent again got back, made short enough to read on one node of the canvas.

JSON becomes key-value pairs (and a table for a list of records), a GWT-RPC answer (`//OK[...]`) the readable strings of its string
table, HTML or XML the cells of its tables and its text. It is shown on the teller's PC only: never written, never sent.
"""

from __future__ import annotations

import html.parser
import json
import re
from typing import Any

MAX_LINES = 50
MAX_CELL = 200
_GWT_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')
_CLASS_NAME = re.compile(r"^[\w$]+(\.[\w$]+)+(/\d+)?$|^\[L|^java\.")


def kind_of(text: str) -> str:
    head = text.lstrip()[:20]
    if head.startswith(("//OK", "//EX")):
        return "gwt"
    if head.startswith(("{", "[")):
        return "json"
    if head.startswith("<"):
        return "html" if re.match(r"<(!doctype html|html|table|div|body)", head, re.IGNORECASE) else "xml"
    return "text" if head else "empty"


def _cut(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text if len(text) <= MAX_CELL else text[:MAX_CELL] + "…"


def _flatten(value: Any, path: str, pairs: list[list[str]]) -> None:
    if len(pairs) >= MAX_LINES:
        return
    if isinstance(value, dict):
        for key, inner in value.items():
            _flatten(inner, f"{path}.{key}" if path else str(key), pairs)
    elif isinstance(value, list) and value and not all(isinstance(x, dict) for x in value):
        pairs.append([path, _cut(", ".join(str(x) for x in value[:20]))])
    elif isinstance(value, list):
        return            # a list of records is shown as a table
    else:
        pairs.append([path or "giá trị", _cut(value)])


def _table(value: Any) -> list[list[str]]:
    """The first list of records found, as rows (headers first)."""
    stack = [value]
    while stack:
        item = stack.pop(0)
        if isinstance(item, list) and item and all(isinstance(x, dict) for x in item):
            headers = list(dict.fromkeys(k for row in item[:MAX_LINES] for k in row))[:20]
            return [headers] + [[_cut(row.get(h, "")) for h in headers] for row in item[:MAX_LINES]]
        if isinstance(item, dict):
            stack.extend(item.values())
    return []


class _Cells(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.text: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(_cut("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._cell is not None:
            self._cell.append(data)
        elif data.strip():
            self.text.append(_cut(data))


def summarize(text: str) -> dict[str, Any]:
    """`{kind, pairs: [[key, value]], rows: [[...]], lines: [...], size}`: at most MAX_LINES of each."""
    kind = kind_of(text)
    view: dict[str, Any] = {"kind": kind, "pairs": [], "rows": [], "lines": [], "size": len(text)}
    if kind == "json":
        try:
            data = json.loads(text)
        except ValueError:
            view["kind"] = kind = "text"
        else:
            _flatten(data, "", view["pairs"])
            view["rows"] = _table(data)
            return view
    if kind == "gwt":
        # the string table is the last array of the answer: readable values (names, numbers, messages) among Java class names
        strings = []
        for raw in _GWT_STRING.findall(text):
            try:
                value = json.loads(f'"{raw}"')
            except ValueError:
                value = raw
            if value and not _CLASS_NAME.match(value):
                strings.append(_cut(value))
        view["lines"] = list(dict.fromkeys(strings))[:MAX_LINES]
        if text.lstrip().startswith("//EX"):
            view["lines"].insert(0, "Máy chủ báo lỗi (//EX)")
        return view
    if kind in ("html", "xml"):
        cells = _Cells()
        try:
            cells.feed(text)
        except Exception:  # noqa: BLE001  a broken page still shows what could be read
            pass
        view["rows"] = cells.rows[:MAX_LINES]
        view["lines"] = cells.text[:MAX_LINES]
        return view
    view["lines"] = [_cut(line) for line in text.splitlines() if line.strip()][:MAX_LINES]
    return view
