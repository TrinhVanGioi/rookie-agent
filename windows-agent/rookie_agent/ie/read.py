"""What the screen shows after an action, and which part of it changed (tasks 4.31 and 4.32).

The page recorder (`page_recorder.js`) reads every frame of the page: the tables of data, the label-value pairs, the messages. This
module parses what it hands over, finds the region that changed between two looks, and leaves out what changes by itself (a clock):

- the full values stay in memory on the teller's PC (the panel "Agent đã thấy"); nothing here writes to disk;
- what leaves the PC is only the structure (kind, headers, number of rows), built elsewhere (CLAUDE.md rules 1 and 2).
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

Key = tuple[str, str, str]  # (frame, kind, name)
ALL = "*"                   # name of "every message of this frame" in the set of what changes by itself


def parse(raw_frames: list[str]) -> list[dict[str, Any]]:
    """The frames as the page reported them. A frame whose answer is not valid is left out; the rest is kept."""
    frames: list[dict[str, Any]] = []
    for raw in raw_frames:
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            frame = json.loads(raw)
        except ValueError:
            continue
        if isinstance(frame, dict) and frame.get("frame") is not None:
            frame.setdefault("tables", [])
            frame.setdefault("fields", [])
            frame.setdefault("messages", [])
            frames.append(frame)
    return frames


def _items(frames: list[dict[str, Any]]) -> dict[Key, str]:
    """Everything the screen shows, each with a signature of its content."""
    found: dict[Key, str] = {}
    for frame in frames:
        name = str(frame.get("frame") or "top")
        for index, table in enumerate(frame.get("tables") or []):
            key = (name, "table", str(table.get("id") or f"t{index}"))
            found[key] = json.dumps([table.get("headers"), table.get("rows")], ensure_ascii=False, sort_keys=True)
        for field in frame.get("fields") or []:
            found[(name, "field", str(field.get("label")))] = str(field.get("value"))
        for message in frame.get("messages") or []:
            found[(name, "message", str(message.get("text")))] = str(message.get("level"))
    return found


def volatile(first: list[dict[str, Any]], second: list[dict[str, Any]]) -> set[Key]:
    """What differs between two looks at a screen at rest: it changes by itself (a clock), so it is never a result."""
    a, b = _items(first), _items(second)
    found = {key for key in a.keys() | b.keys() if a.get(key) != b.get(key) and key[1] != "message"}
    # The text of a message is its identity, so a clock written as a message is a new message every second: when a frame shows the
    # same number of messages in both looks but not the same texts, the messages of that frame keep changing by themselves.
    for name in {key[0] for key in a.keys() | b.keys() if key[1] == "message"}:
        texts_a = {key for key in a if key[0] == name and key[1] == "message"}
        texts_b = {key for key in b if key[0] == name and key[1] == "message"}
        if texts_a != texts_b and len(texts_a) == len(texts_b):
            found.add((name, "message", ALL))
    return found


def changed(previous: list[dict[str, Any]], current: list[dict[str, Any]], leave_out: set[Key] | None = None) -> list[dict[str, Any]]:
    """What is on the screen now and was not there, or was different, in the previous look."""
    before, after = _items(previous), _items(current)
    skip = leave_out or set()
    result = []
    for key, signature in after.items():
        if key in skip or (key[1] == "message" and (key[0], "message", ALL) in skip):
            continue
        if before.get(key) != signature:
            result.append({"frame": key[0], "kind": key[1], "name": key[2]})
    return result


def region(changes: list[dict[str, Any]]) -> list[str]:
    """The frames that hold the change, in order of first appearance."""
    seen: list[str] = []
    for change in changes:
        if change["frame"] not in seen:
            seen.append(change["frame"])
    return seen


def describe(frames: list[dict[str, Any]]) -> str:
    """What the agent saw, in a few plain words (for the panel and the log). Values are not repeated here except messages."""
    parts: list[str] = []
    for frame in frames:
        name = frame.get("frame") or "top"
        for table in frame.get("tables") or []:
            parts.append(f"khung «{name}»: bảng {table.get('row_count', len(table.get('rows') or []))} dòng, {len(table.get('headers') or [])} cột")
        if frame.get("fields"):
            parts.append(f"khung «{name}»: {len(frame['fields'])} ô thông tin")
        for message in frame.get("messages") or []:
            kind = "lỗi" if message.get("level") == "error" else "thông báo"
            parts.append(f"khung «{name}»: {kind} «{message.get('text')}»")
    return "; ".join(parts) if parts else "không thấy dữ liệu nào trên màn hình"


# ---- the screen as data the agent can call (an object, key-value pairs, a list of rows) ------------------------------------------

class NoSuchData(LookupError):
    """The path names nothing on the screen, or names more than one thing. Nothing is guessed."""


def slug(text: Any) -> str:
    """`Số tài khoản:` -> `so_tai_khoan`. The name a value is called by in a flow."""
    plain = unicodedata.normalize("NFD", str(text or "").replace("đ", "d").replace("Đ", "D"))
    plain = "".join(c for c in plain if unicodedata.category(c) != "Mn").lower()
    name = re.sub(r"[^a-z0-9]+", "_", plain).strip("_")
    if not name:
        return "gia_tri"
    return name if name[0].isalpha() else f"p_{name}"


def model(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """The screen as an object: per frame, `fields` (key-value), `tables` (columns and a list of row objects), and the `messages`."""
    result: dict[str, Any] = {"frames": {}, "messages": []}
    for frame in frames:
        name = str(frame.get("frame") or "top")
        fields = {slug(f.get("label")): str(f.get("value")) for f in frame.get("fields") or []}
        tables: dict[str, Any] = {}
        for index, table in enumerate(frame.get("tables") or []):
            columns = [slug(h) for h in table.get("headers") or []]
            rows = [{columns[i]: str(cell) for i, cell in enumerate(row) if i < len(columns)} for row in table.get("rows") or []]
            tables[slug(table.get("id") or f"t{index}")] = {"columns": columns, "rows": rows, "row_count": int(table.get("row_count") or len(rows))}
        result["frames"][name] = {"fields": fields, "tables": tables}
        for message in frame.get("messages") or []:
            result["messages"].append({"frame": name, "level": str(message.get("level") or "info"), "text": str(message.get("text") or "")})
    return result


def paths(data: dict[str, Any]) -> dict[str, str]:
    """Every value of the screen by path. A short name (`so_tai_khoan`, `grid.0.so_tk`) is there only when it names exactly one value."""
    long: dict[str, str] = {}
    short: dict[str, list[str]] = {}

    def add(full: str, shorts: list[str], value: str) -> None:
        long[full] = value
        for name in shorts:
            short.setdefault(name, []).append(full)

    for frame, content in data["frames"].items():
        for key, value in content["fields"].items():
            add(f"{frame}.fields.{key}", [key], value)
        for table_id, table in content["tables"].items():
            for index, row in enumerate(table["rows"]):
                for column, value in row.items():
                    add(f"{frame}.tables.{table_id}.rows.{index}.{column}", [f"{table_id}.{index}.{column}"] + ([f"{table_id}.{column}"] if len(table["rows"]) == 1 else []), value)
    for index, message in enumerate(data["messages"]):
        add(f"message.{index}", [f"message.{index}"], message["text"])
        add(f"message.{index}.level", [f"message.{index}.level"], message["level"])
    found = dict(long)
    for name, owners in short.items():
        if len(owners) == 1 and name not in found:
            found[name] = long[owners[0]]
    return found


def lookup(found: dict[str, str], path: str) -> str:
    if path not in found:
        raise NoSuchData(path)
    return found[path]


def listing(data: dict[str, Any], variable: str = "ten_bien") -> list[dict[str, str]]:
    """What the panel shows: each value with the path to call it by and the placeholder to put in a step."""
    items = []
    for path, value in paths(data).items():
        parts = path.split(".")
        if len(parts) > 1 and parts[1] in ("fields", "tables"):
            continue                       # the long form is for programs; people see the short form
        kind = "message" if path.startswith("message.") else ("cell" if "." in path else "field")
        items.append({"kind": kind, "path": path, "value": value, "placeholder": "{" + variable + "." + path + "}"})
    return items
