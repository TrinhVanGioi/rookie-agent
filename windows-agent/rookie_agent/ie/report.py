"""A report made from the data a call returned (task 11.11).

Some screens are not a file: the server answers with data (an XML or a GWT-RPC answer) and the page puts it on the screen, field by field (the
«IN BÁO NỢ/CÓ» view of TouchPoint). There is nothing to download, so the agent makes the printable page itself, with the labels of the screen.

Learning (while recording, on the teller's PC, in memory): the values of the answer are laid beside the label-value pairs the screen showed
after the action. A pair whose value is in the answer teaches `label <- where in the answer` (an element path, a place in the GWT string
table, a JSON path). Only the label and the rule are kept, never a value (docs/design.md 4.2). Running: the rules are laid over the new answer.
"""

from __future__ import annotations

import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any

from rookie_agent.ie import files, replay, response_view

MIN_FIELDS = 3            # fewer matches than this is not a report: a screen that shares a word or two with an answer
MIN_VALUE = 2             # a value shorter than this matches too much (a «0», a «1»)
CONTAIN_MIN = 4           # a value is taken to be inside a formatted one («10944» in «10,944.00») from this length
LABEL_MAX = 60
# only an action that prints or exports makes a page to print: a look-up shows its answer on the screen and needs none
PRINT_WORDS = re.compile(r"(?<!\w)(in|xuất|tải|báo cáo|báo nợ|báo có|sao kê|chứng từ|export|print|download|report|statement)(?!\w)", re.IGNORECASE)


def _norm(text: Any) -> str:
    plain = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return re.sub(r"[\s.,:;/\\\-_]+", "", plain)


def _json_leaves(value: Any, path: tuple[Any, ...] = ()) -> list[tuple[dict[str, Any], str]]:
    out: list[tuple[dict[str, Any], str]] = []
    if isinstance(value, dict):
        for key, inner in value.items():
            out += _json_leaves(inner, path + (key,))
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            out += _json_leaves(inner, path + (index,))
    elif value is not None and not isinstance(value, bool):
        out.append(({"json": list(path)}, str(value)))
    return out


def _xml_leaves(answer: str) -> list[tuple[dict[str, Any], str]]:
    root = replay._xml_root(answer)
    if root is None:
        return []
    out: list[tuple[dict[str, Any], str]] = []

    def walk(element: ET.Element, path: list[str]) -> None:
        children = list(element)
        if not children:
            text = (element.text or "").strip()
            if text:
                out.append(({"xml": path}, text))
            return
        count, seen = Counter(replay._local(c.tag) for c in children), Counter()
        for child in children:
            name = replay._local(child.tag)
            seen[name] += 1
            walk(child, path + [f"{name}[{seen[name]}]" if count[name] > 1 else name])

    walk(root, [replay._local(root.tag)])
    return out


def candidates(answer: str) -> list[tuple[dict[str, Any], str]]:
    """Every value of an answer with the rule that finds it again (`replay.take_value`): XML, GWT-RPC and JSON answers; others have none."""
    kind = response_view.kind_of(answer)
    if kind == "xml":
        found = _xml_leaves(answer)
    elif kind == "gwt":
        found = [({"gwt": i}, s) for i, s in enumerate(replay._gwt_strings(answer)) if s and not response_view._CLASS_NAME.match(s)]
    elif kind == "json":
        try:
            found = _json_leaves(json.loads(answer))
        except ValueError:
            found = []
    else:
        found = []
    return [(rule, value) for rule, value in found if len(value.strip()) >= MIN_VALUE]


SMALL_TABLE = 8           # rows (header included) up to which a table may be a form laid out in cells, not a table of data


def _table_pairs(table: dict[str, Any]) -> list[tuple[str, str]]:
    """A small table read both ways: a header row over one row of values (header = label), and a form of label, value, label, value… on each
    line. Both are offered; a pair that does not match the answer is dropped by `match`."""
    headers = [str(h or "") for h in table.get("headers") or []]
    rows = [[str(c or "") for c in row] for row in table.get("rows") or []]
    pairs: list[tuple[str, str]] = []
    if len(rows) == 1 and headers:
        pairs += list(zip(headers, rows[0]))
    if len(rows) + 1 <= SMALL_TABLE:
        for line in ([headers] if headers else []) + rows:
            if 2 <= len(line) <= 8 and len(line) % 2 == 0:
                pairs += [(line[i], line[i + 1]) for i in range(0, len(line), 2)]
    return pairs


def screen_pairs(entry: dict[str, Any]) -> list[tuple[str, str]]:
    """The label-value pairs of what an action changed on the screen: the `fields` the reader found, and the small tables (see `_table_pairs`)."""
    changed = {(c["frame"], c["kind"], str(c["name"])) for c in entry.get("changed") or []}
    pairs: list[tuple[str, str]] = []
    for frame in entry.get("frames") or []:
        name = str(frame.get("frame") or "top")
        for field in frame.get("fields") or []:
            if (name, "field", str(field.get("label"))) in changed:
                pairs.append((str(field.get("label") or ""), str(field.get("value") or "")))
        for index, table in enumerate(frame.get("tables") or []):
            if (name, "table", str(table.get("id") or f"t{index}")) in changed:
                pairs += _table_pairs(table)
    return [(label.strip(), value.strip()) for label, value in pairs if label.strip() and value.strip()]


def _label_ok(label: str) -> bool:
    return 0 < len(label) <= LABEL_MAX and len(re.findall(r"\d", label)) <= 2       # a label with digits is more likely data than a label


def match(cands: list[tuple[dict[str, Any], str]], pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """The fields of a screen that the answer holds, in the order of the screen: `{label, rule}`; each value of the answer once."""
    used: set[int] = set()
    found: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    data = {_norm(value) for _, value in cands}
    for label, shown in pairs:
        # a «label» that is itself a value of the answer, or only digits, is data read as a label (a name in the first column of a table of
        # data): never kept, a label is a word of the form and a value is the customer's
        if not _label_ok(label) or label in seen_labels or _norm(label) in data or not re.search(r"[^\W\d_]", label):
            continue
        wanted = _norm(shown)
        if len(wanted) < MIN_VALUE:
            continue
        pick = next((i for i, (_, value) in enumerate(cands) if i not in used and _norm(value) == wanted), None)
        if pick is None:      # a formatted value on the screen (an amount with separators, a date): the value of the answer is inside it
            pick = next((i for i, (_, value) in enumerate(cands)
                         if i not in used and len(_norm(value)) >= CONTAIN_MIN and _norm(value) in wanted), None)
        if pick is not None:
            used.add(pick)
            seen_labels.add(label)
            found.append({"label": label, "rule": cands[pick][0]})
    return found


def learn(requests: list[dict[str, Any]], seen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For each answer of a recording that a screen then showed field by field: `{request, title, fields: [{label, rule}]}`. Nothing but
    labels and rules (no value). `requests` are the raw ones of the session (their answers are in memory), `seen` what the screen showed."""
    maps: list[dict[str, Any]] = []
    for index, item in enumerate(requests):
        answer = str(item.get("res") or "")
        if not answer or item.get("status") and int(item["status"]) >= 400:
            continue
        title = str((item.get("after") or {}).get("label") or "Báo cáo")[:80]
        if not PRINT_WORDS.search(title):
            continue
        cands = candidates(answer)
        if len(cands) < MIN_FIELDS:
            continue
        moment = int(item.get("t") or 0)
        best: list[dict[str, Any]] = []
        for entry in seen:
            if entry.get("provisional") or int(entry.get("t") or 0) < moment - 200:
                continue
            fields = match(cands, screen_pairs(entry))
            if len(fields) > len(best):
                best = fields
        if len(best) >= MIN_FIELDS:
            maps.append({"request": index, "title": title, "fields": best})
    return maps


def fill(spec: dict[str, Any], answer: str) -> list[tuple[str, str]]:
    """`(label, value)` for the fields of a report spec, from this run's answer; a field the answer does not have is left out."""
    out: list[tuple[str, str]] = []
    for field in spec.get("fields") or []:
        value = replay.take_value(answer, field["rule"]) if isinstance(field.get("rule"), dict) else None
        if value:
            out.append((str(field["label"]), value))
    return out


def attach(nodes: list[dict[str, Any]], maps: list[dict[str, Any]] | None) -> None:
    """The report specs of a recording put on the nodes of its flow (a node is `a<index of the request>`)."""
    by_id = {n["id"]: n for n in nodes}
    for one in maps or []:
        node = by_id.get(f"a{one.get('request')}")
        if node is not None and one.get("fields"):
            node["report"] = {"title": one.get("title") or "Báo cáo", "fields": one["fields"]}
