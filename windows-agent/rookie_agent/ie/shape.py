"""Gate 9 (task 9.4): the shape of an answer, without one value of it, and a fake answer made from that shape.

When a recording stops, each answer becomes a skeleton: its structure stays (JSON keys and types, the Java class names of a GWT-RPC
string table, the tags and attribute names of a page) and every value becomes a mask of its form (`9` a digit, `A` a capital
letter, `a` another letter; spaces and punctuation as they are). The skeleton is kept on this PC with the flow (rule 1); the twin
(`fake`) builds a concrete synthetic answer from it, the same one for the same inputs, so the links of a flow (`⟦l1⟧`: a JSON path,
a place in a GWT string table, the text before a value) still find a value in it. Nothing here is sent anywhere.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from typing import Any

from rookie_agent.ie import response_view

MAX_MASK = 200
_CLASS_LIKE = re.compile(r"^\[*L?[a-z][\w$]*(\.[\w$]+){2,};?(/\d+)?$")
KEEP_ATTRS = {"id", "class", "name", "type", "for", "colspan", "rowspan", "method"}
_TAG = re.compile(r"<!--.*?-->|<![^>]*>|<[^>]*>", re.DOTALL)
_ATTR = re.compile(r"""([\w:.-]+)(\s*=\s*)("[^"]*"|'[^']*'|[^\s>"']+)""")
_RAW_TEXT_TAGS = ("script", "style")


def mask(value: str) -> str:
    """The form of a text: digits 9, capital letters A, other letters a; everything else (space, punctuation) as it is."""
    out = []
    for ch in value[:MAX_MASK]:
        out.append("9" if ch.isdigit() else ("A" if ch.isupper() else "a") if ch.isalpha() else ch)
    return "".join(out)


def _number_mask(value: Any) -> dict[str, Any]:
    return {"t": "n", "m": re.sub(r"\d", "9", repr(value)), "f": isinstance(value, float)}


# ---- JSON -------------------------------------------------------------------------------------------------------------------

def _json_shape(data: Any) -> Any:
    if isinstance(data, dict):
        return {"t": "o", "v": {str(k): _json_shape(v) for k, v in data.items()}}
    if isinstance(data, list):
        return {"t": "l", "v": [_json_shape(x) for x in data]}
    if isinstance(data, bool) or data is None:
        return {"t": "b" if isinstance(data, bool) else "z", "v": data}
    if isinstance(data, (int, float)):
        return _number_mask(data)
    return {"t": "s", "m": mask(str(data))}


# ---- GWT-RPC ----------------------------------------------------------------------------------------------------------------

def _gwt_shape(text: str) -> dict[str, Any] | None:
    head = text.lstrip()
    try:
        data = json.loads(head[4:])
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    table_at = max((i for i, x in enumerate(data) if isinstance(x, list)), default=-1)
    if table_at < 0:
        return None
    table = data[table_at]
    stream = []
    for at, item in enumerate(data):
        if at == table_at:
            stream.append({"t": "table"})
        elif isinstance(item, int) and not isinstance(item, bool) and abs(item) > len(table) and at < table_at:
            stream.append({"t": "n", "m": re.sub(r"\d", "9", str(item)), "f": False})   # an amount, not a reference to the table
        else:
            stream.append({"t": "k", "v": item})
    strings = [{"t": "k", "v": s} if isinstance(s, str) and _CLASS_LIKE.match(s) else {"t": "s", "m": mask(str(s))} for s in table]
    return {"head": head[:4], "stream": stream, "strings": strings}


# ---- HTML, XML and text -----------------------------------------------------------------------------------------------------

def _mask_tag(tag: str) -> str:
    if tag.startswith("<!--"):
        return "<!-- -->"
    if tag.startswith(("<!", "<?")):
        return tag

    def one(match: re.Match[str]) -> str:
        name, eq, raw = match.groups()
        if name.lower() in KEEP_ATTRS:
            return match.group(0)
        quote = raw[0] if raw[0] in "\"'" else '"'
        return f"{name}{eq}{quote}{mask(raw.strip(chr(34) + chr(39)))}{quote}"

    return _ATTR.sub(one, tag)


def _segments(text: str, markup: bool) -> list[list[Any]]:
    """[(start, end, literal?)] over the text: tags are literal (their attribute values masked), the text between them a mask."""
    spans: list[list[Any]] = []
    if not markup:
        spans.append([0, len(text), False])
    else:
        position = 0
        for tag in _TAG.finditer(text):
            if tag.start() > position:
                spans.append([position, tag.start(), False])
            spans.append([tag.start(), tag.end(), True])
            position = tag.end()
        if position < len(text):
            spans.append([position, len(text), False])
    return spans


def _text_shape(text: str, markup: bool, rules: list[dict[str, Any]]) -> list[list[str]]:
    from rookie_agent.ie import replay

    group = [-1] * len(text)       # one number per run of characters that is shaped as a unit
    literal = [False] * len(text)
    for gid, (start, end, lit) in enumerate(_segments(text, markup)):
        for i in range(start, end):
            group[i], literal[i] = gid, lit
    gid = len(text) + 1
    for rule in rules:            # a «before … after» link: the text before and the one char after stay as they are, the value is a mask
        if "before" not in rule:
            continue
        value = replay.take_value(text, rule)
        if not value:
            continue
        at = text.find(rule["before"]) + len(rule["before"])
        for i in range(at - len(rule["before"]), at):
            group[i], literal[i] = gid, True
        gid += 1
        for i in range(at, at + len(value)):
            group[i], literal[i] = gid, False
        gid += 1
        group[at + len(value)], literal[at + len(value)] = gid, True
        gid += 1
    out: list[list[str]] = []
    i = 0
    while i < len(text):
        j = i
        while j < len(text) and group[j] == group[i]:
            j += 1
        chunk = text[i:j]
        if literal[i]:
            out.append(["l", _mask_tag(chunk) if chunk.startswith("<") and len(chunk) > 1 and chunk.endswith(">") else chunk])
        else:
            lead, core = chunk[:len(chunk) - len(chunk.lstrip())], chunk.strip()
            trail = chunk[len(lead) + len(core):]
            if lead:
                out.append(["l", lead])
            if core:
                out.append(["m", mask(core)])
            if trail:
                out.append(["l", trail])
        i = j
    return out


def shape(text: str, rules: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The skeleton of an answer. `rules` are the links (`replay.locate_value` rules) later requests take values from: a
    «before … after» rule keeps the text around its value so that it finds the value again in the fake answer."""
    rules = rules or []
    kind = response_view.kind_of(text)
    if kind == "json":
        try:
            return {"v": 1, "kind": "json", "body": _json_shape(json.loads(text))}
        except ValueError:
            kind = "text"
    if kind == "gwt":
        body = _gwt_shape(text)
        if body is not None:
            return {"v": 1, "kind": "gwt", "body": body}
        kind = "text"
    if kind in ("html", "xml"):
        return {"v": 1, "kind": kind, "body": _text_shape(text, True, rules)}
    return {"v": 1, "kind": "text" if kind != "empty" else "empty", "body": _text_shape(text, False, rules) if kind != "empty" else []}


# ---- the fake answer --------------------------------------------------------------------------------------------------------

class _Maker:
    def __init__(self, inputs: dict[str, str], seed: str) -> None:
        self.base = json.dumps([sorted((str(k), str(v)) for k, v in inputs.items()), str(seed)], ensure_ascii=False)

    def rng(self, where: str) -> random.Random:
        return random.Random(int(hashlib.sha256((self.base + "|" + where).encode("utf-8")).hexdigest()[:16], 16))

    def text(self, pattern: str, where: str) -> str:
        rng, out = self.rng(where), []
        for ch in pattern:
            if ch == "9":
                out.append(str(rng.randrange(10)))
            elif ch == "A":
                out.append(chr(65 + rng.randrange(26)))
            elif ch == "a":
                out.append(chr(97 + rng.randrange(26)))
            else:
                out.append(ch)
        return "".join(out)

    def number(self, node: dict[str, Any], where: str) -> Any:
        value = self.text(node["m"], where)
        body = value.lstrip("-")
        if len(body) > 1 and body[0] == "0" and body[1] != ".":       # no leading zero in a number of more than one digit
            value = value[:len(value) - len(body)] + "1" + body[1:]
        try:
            return float(value) if node["f"] else int(value)
        except ValueError:
            return 0


def _json_fake(node: dict[str, Any], maker: _Maker, where: str) -> Any:
    kind = node["t"]
    if kind == "o":
        return {k: _json_fake(v, maker, f"{where}/{k}") for k, v in node["v"].items()}
    if kind == "l":
        return [_json_fake(v, maker, f"{where}/{i}") for i, v in enumerate(node["v"])]
    if kind in ("b", "z"):
        return node["v"]
    if kind == "n":
        return maker.number(node, where)
    return maker.text(node["m"], where)


def fake(skeleton: dict[str, Any], inputs: dict[str, str] | None = None, seed: str = "") -> str:
    """A concrete synthetic answer of the skeleton: the same text for the same `inputs` and `seed`, never a real value."""
    maker = _Maker(inputs or {}, seed)
    kind, body = skeleton["kind"], skeleton["body"]
    if kind == "json":
        return json.dumps(_json_fake(body, maker, ""), ensure_ascii=False)
    if kind == "gwt":
        def piece(node: dict[str, Any], where: str) -> Any:
            if node["t"] == "k":
                return node["v"]
            if node["t"] == "n":
                return maker.number(node, where)
            return maker.text(node["m"], where)

        stream = []
        for i, node in enumerate(body["stream"]):
            stream.append([piece(s, f"t{j}") for j, s in enumerate(body["strings"])] if node["t"] == "table" else piece(node, f"s{i}"))
        return body["head"] + json.dumps(stream, ensure_ascii=False, separators=(",", ":"))
    out = []
    for i, (how, text) in enumerate(body):
        out.append(text if how == "l" else maker.text(text, f"seg{i}"))
    return "".join(out)
