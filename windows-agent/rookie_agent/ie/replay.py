"""Gates 7 and 8: a learned flow as a chain of API calls, run on the canvas like an n8n workflow (docs/design.md 6.3, 6.4).

When a recording stops, every request the page made (XHR, a form sent, a frame that loaded a page) becomes a template:
- what the teller typed is replaced by a mark of the event that typed it (`⟦e7⟧`), never kept;
- a value that an earlier answer gave (a customer id, a session or anti-forgery token) is replaced by a link (`⟦l1⟧`) that says
  which answer and where in it (a JSON path, a place in a GWT string table, or the text just before it), never the value;
- a token that no answer explains is hidden (`***`) and the request is known as one that cannot be sent again.
When the flow is learned, the templates become API nodes in order, each named after the action that made it ("Bấm «Tìm kiếm» →
POST /tp/find"), its typed marks turned into the step's value (`⟦cif⟧` of an input, or the plain text a step always types).
A run sends them from inside the teller's signed-in IE page (its own session; no cookie is read), fills each link from the answer
just received, and shows what came back. Only read-only nodes are sent; signing in is never replayed. Nothing is guessed.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Callable

from rookie_agent.ie import files, response_view, shape as shaper

MIN_TYPED = 3           # a shorter typed value could be found by chance in a request: it is left as it is
MIN_LINKED = 4
OPEN, CLOSE = "⟦", "⟧"   # ⟦e7⟧, ⟦l1⟧, ⟦cif⟧: never mistaken for the braces of a JSON body
_MARK = re.compile(OPEN + r"([a-z0-9_]+)" + CLOSE)
_HIDDEN = '"***"'
_TOKEN_CANDIDATE = re.compile(r"[A-Za-z0-9_\-.~%+/]{4,}={0,2}")
_TOKEN_KEY = re.compile(r"((?:token|secret|csrf|xsrf|nonce)[a-z_]*[\"']?\s*[:=]\s*)(\"(?:[^\"\\]|\\.)*\"|'[^']*'|[^&,}\s|]*)", re.IGNORECASE)
_JWT = re.compile(r"^eyJ[\w-]+\.[\w-]+\.[\w-]*$")   # looks like a dotted Java name, but is a bearer token
_CLASS_LIKE = re.compile(r"^[a-z][\w$]*(\.[\w$]+){2,}(/\d+)?$")
POLLING = 3             # the same request this many times or more is the page polling: not part of the flow unless a later one needs it


def _iso(milliseconds: int) -> str:
    moment = datetime.fromtimestamp(milliseconds / 1000.0, tz=timezone.utc)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


REACT_MS = 400     # a page answers a press or an Enter at once: a call sent this little before a press belongs to that press


def _stamp_ms(event: dict[str, Any]) -> float | None:
    from datetime import datetime

    try:
        return datetime.fromisoformat(str(event.get("ts")).replace("Z", "+00:00")).timestamp() * 1000
    except ValueError:
        return None


def _press_right_after(events: list[dict[str, Any]], sent: Any, after_seq: int | None) -> int | None:
    """The press (click, Enter) a call was sent for, when the page's own handler ran before the recorder's: the page's onkeydown of a
    field runs before the recorder hears the key, so the call is sent a few milliseconds before the press is recorded."""
    if not sent:
        return None
    for event in events:
        if event.get("type") not in ("click", "submit") or (after_seq is not None and int(event["seq"]) <= after_seq):
            continue
        at = _stamp_ms(event)
        if at is not None and 0 <= at - int(sent) <= REACT_MS:
            return int(event["seq"])
    return None


def _last_action_before(events: list[dict[str, Any]], sent: Any) -> int | None:
    """The last action done at or before the moment a call was sent, by the clock. The order the lines were read in is not that: each
    frame has its own queue and the queues are read one after the other."""
    if not sent:
        return None
    best, best_at = None, None
    for event in events:
        at = _stamp_ms(event)
        if at is not None and at <= int(sent) and (best_at is None or at >= best_at):
            best, best_at = int(event["seq"]), at
    return best


def _seq_at(events: list[dict[str, Any]], moment: Any, kinds: tuple[str, ...] = ()) -> int | None:
    if not moment:
        return None
    stamp = _iso(int(moment))
    for event in events:
        if event.get("ts") == stamp and (not kinds or event.get("type") in kinds):
            return int(event["seq"])
    return None


# ---- where a value sits in an answer, and how to take it again from a new answer --------------------------------------

def _json_path(data: Any, wanted: str, path: tuple[Any, ...] = ()) -> tuple[Any, ...] | None:
    if isinstance(data, dict):
        for key, inner in data.items():
            found = _json_path(inner, wanted, path + (key,))
            if found is not None:
                return found
    elif isinstance(data, list):
        for index, inner in enumerate(data):
            found = _json_path(inner, wanted, path + (index,))
            if found is not None:
                return found
    elif data is not None and not isinstance(data, bool) and str(data) == wanted:
        return path
    return None


def _gwt_strings(text: str) -> list[str]:
    """The string table of a GWT-RPC answer (`//OK[..., ["a","b"], 0, 7]`), in order."""
    start = text.rfind(",[")
    end = text.rfind("]", 0, text.rfind("]"))
    if not text.lstrip().startswith("//OK") or start < 0 or end <= start:
        return []
    try:
        table = json.loads(text[start + 1:end + 1])
    except ValueError:
        return []
    return [str(x) for x in table] if isinstance(table, list) else []


def locate_value(answer: str, value: str) -> dict[str, Any] | None:
    """Where `value` is in `answer`, as a rule that finds it again in another answer of the same kind (never the value itself)."""
    kind = response_view.kind_of(answer)
    if kind == "json":
        try:
            path = _json_path(json.loads(answer), value)
        except ValueError:
            path = None
        if path is not None:
            return {"json": list(path)}
    if kind == "gwt":
        strings = _gwt_strings(answer)
        if value in strings:
            return {"gwt": strings.index(value)}
    if answer.strip() == value:                       # the answer is the bare value (a token service answers just the token)
        return {"whole": True}
    found = re.search(r"(?<![A-Za-z0-9])" + re.escape(value) + r"(?![A-Za-z0-9])", answer)
    if not found:
        return None
    before = answer[max(0, found.start() - 16):found.start()]
    after = answer[found.end():found.end() + 1]
    if not before or not after:
        return None
    return {"before": before, "after": after}


def take_value(answer: str, rule: dict[str, Any]) -> str | None:
    """The value a rule of `locate_value` points at in a new answer; None when it is not there (the run then stops and asks)."""
    if "json" in rule:
        try:
            data: Any = json.loads(answer)
        except ValueError:
            return None
        for key in rule["json"]:
            try:
                data = data[key]
            except (KeyError, IndexError, TypeError):
                return None
        return None if isinstance(data, (dict, list)) or data is None else str(data)
    if "gwt" in rule:
        strings = _gwt_strings(answer)
        return strings[rule["gwt"]] if 0 <= rule["gwt"] < len(strings) else None
    if "whole" in rule:
        return answer.strip() or None
    start = answer.find(rule["before"])
    if start < 0:
        return None
    start += len(rule["before"])
    end = answer.find(rule["after"], start)
    return answer[start:end] if end > start else None


# ---- 7.1 and 8.1 to 8.3: the requests of one recording as templates -------------------------------------------------

def file_facts(found: Any) -> dict[str, Any] | None:
    """What a recording keeps of an answer that was a file: that it was one, its content type, its size and a pattern of its name (digits and
    words already masked by the page's recorder). Never a byte, a text or a shape. `guess`: the page showed no document for the request, so
    it is taken as a download; the run decides by what really comes back."""
    if not isinstance(found, dict):
        return None
    try:
        size = max(0, int(found.get("size") or 0))
    except (TypeError, ValueError):
        size = 0
    return {"ctype": str(found.get("ctype") or "")[:80], "size": size, "name": str(found.get("name") or "")[:80], "guess": bool(found.get("guess"))}


_AUTH_HEADER = re.compile(r"^((?:proxy-)?authorization:)(.*)$", re.IGNORECASE | re.MULTILINE)


def templates(raw: list[dict[str, Any]], events: list[dict[str, Any]], requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only lines that became events count as typed (a password never does). Answers are read here, in memory, and never kept."""
    typed: list[tuple[str, int]] = []
    for line in raw:
        if str(line.get("kind")) not in ("input", "select"):
            continue
        value = str(line.get("value") or "")
        seq = _seq_at(events, line.get("t"), ("input", "select"))
        if seq is not None and len(value.strip()) >= MIN_TYPED:
            typed.append((value, seq))
    typed.sort(key=lambda item: -len(item[0]))     # the longest first, so a value inside another is not cut in two
    typed_values = {value for value, _ in typed}

    def marked(text: str) -> str:
        # a typed value only where it stands alone: not inside a longer word or number (a typed account number that happens to be part of
        # the GWT strong name, a class name or another number must not turn that constant into a mark)
        for value, seq in typed:
            mark = f"{OPEN}e{seq}{CLOSE}"
            for form in dict.fromkeys((value, urllib.parse.quote(value, safe=""), urllib.parse.quote_plus(value))):
                text = re.sub(r"(?<![A-Za-z0-9])" + re.escape(form) + r"(?![A-Za-z0-9])", lambda _m: mark, text)
        return text

    out: list[dict[str, Any]] = []
    for index, item in enumerate(requests):
        url, body = marked(str(item.get("url") or "")), marked(str(item.get("req") or ""))
        headers = str(item.get("hdr") or "")
        links: dict[str, dict[str, Any]] = {}
        # a value of this request that an earlier answer gave: the latest such answer is its source
        for text_name in ("url", "body", "headers"):
            text = {"url": url, "body": body, "headers": headers}[text_name]
            scan = text.split("?", 1)[1] if text_name == "url" and "?" in text else ("" if text_name == "url" else text)
            for candidate in dict.fromkeys(_TOKEN_CANDIDATE.findall(scan)):
                value = urllib.parse.unquote_plus(candidate)
                if (len(value) < MIN_LINKED or value in typed_values or OPEN in value or (_CLASS_LIKE.match(value) and not _JWT.match(value))
                        or not (any(c.isdigit() for c in value) or len(value) >= 16)):
                    continue
                for source in range(index - 1, -1, -1):
                    if requests[source].get("file"):
                        continue                        # a file is not read for values: it is the customer's document
                    rule = locate_value(str(requests[source].get("res") or ""), value)
                    if rule:
                        name = f"l{len(links) + 1}"
                        links[name] = {"from": source, **rule}
                        text = re.sub(r"(?<![A-Za-z0-9])" + re.escape(candidate) + r"(?![A-Za-z0-9])", f"{OPEN}{name}{CLOSE}", text)
                        break
            url, body, headers = (text, body, headers) if text_name == "url" else (url, text, headers) if text_name == "body" else (url, body, text)
        # a token no answer explains is not kept: the request then cannot be sent again
        hidden = False

        def hide(match: re.Match[str]) -> str:
            nonlocal hidden
            if OPEN in match.group(2) or match.group(2) in ('""', "''", ""):
                return match.group(0)
            hidden = True
            return match.group(1) + _HIDDEN

        body, url, headers = _TOKEN_KEY.sub(hide, body), _TOKEN_KEY.sub(hide, url), _TOKEN_KEY.sub(hide, headers)
        # a bearer token (Authorization) that no earlier answer explains is not kept either (a token service's answer gives it, or the request cannot be sent again)

        def hide_auth(match: re.Match[str]) -> str:
            nonlocal hidden
            if OPEN in match.group(2) or match.group(2).strip() in ("", "***"):
                return match.group(0)
            hidden = True
            return match.group(1) + "***"

        headers = _AUTH_HEADER.sub(hide_auth, headers)
        after = item.get("after") or {}
        file = file_facts(item.get("file"))
        after_seq = _seq_at(events, after.get("t"))
        if item.get("t"):
            by_clock = _last_action_before(events, item.get("t"))
            after_seq = by_clock if by_clock is not None else (after_seq if after_seq is not None and after.get("t") and int(after["t"]) <= int(item["t"]) else None)
        pressed = _press_right_after(events, item.get("t"), after_seq)
        out.append({
            "index": index, "after_seq": pressed if pressed is not None else after_seq, "kind": str(item.get("kind") or "xhr"),
            "frame": str(item.get("frame") or "top"), "method": str(item.get("method") or "GET").upper(),
            "url": url, "headers": headers, "body": body, "links": links,
            "complete": not item.get("cut") and not hidden and "***" not in body and body != "[object]",
            "status": int(item.get("status") or 0), "answer": "file" if file else response_view.kind_of(str(item.get("res") or "")),
            "ms": int(item.get("ms") or 0), **({"file": file} if file else {}),
            **({"target": "dialog"} if item.get("target") == "dialog" else {}),
        })
    for index, item in enumerate(out):   # task 9.4: the answer's skeleton (no value), made so that the links to it still find a value
        rules = [rule for other in out for rule in other["links"].values() if rule["from"] == index]
        if item.get("file"):
            item["shape"] = {"v": 1, "kind": "file", "body": None}    # the twin answers a file with a placeholder; nothing of the real one is kept
            continue
        try:
            item["shape"] = shaper.shape(str(requests[index].get("res") or ""), rules)
        except Exception:  # noqa: BLE001  a template without a skeleton only means no twin run for it
            item["shape"] = None
    return out


# ---- 8.4: the flow as API nodes --------------------------------------------------------------------------------------

def _same_kind(event: dict[str, Any], step: dict[str, Any]) -> bool:
    return {"input": "fill", "select": "select", "click": "click", "submit": "submit"}.get(str(event.get("type"))) == step.get("action")


def build_api(workflow: dict[str, Any], events: list[dict[str, Any]], found: list[dict[str, Any]],
              describe: Callable[[dict[str, Any]], str] = lambda step: step["id"]) -> list[dict[str, Any]]:
    """The templates of one recording as the nodes of the flow, in the order they were sent."""
    step_of: dict[int, dict[str, Any]] = {}
    for event in events:
        first = ((event.get("target") or {}).get("selectors") or [None])[0]
        for step in workflow.get("steps", []):
            if first and first in ((step.get("target") or {}).get("selectors") or []) and _same_kind(event, step):
                step_of[int(event["seq"])] = step
                break

    def value_of(match: re.Match[str]) -> str:
        name = match.group(1)
        if not (name.startswith("e") and name[1:].isdigit()):
            return match.group(0)
        step = step_of.get(int(name[1:]))
        if step is None or step.get("value") is None:
            return match.group(0)
        inner = re.fullmatch(r"\{([a-z][a-z0-9_]*)\}", str(step["value"]))
        return f"{OPEN}{inner.group(1)}{CLOSE}" if inner else str(step["value"])

    from rookie_agent.ie import clean

    asking = clean.polling(found)                  # rule 0 of ie/clean.py: the page polling by itself (a keep-alive with a time in it too)
    known = {i["name"] for i in workflow.get("inputs", [])}
    nodes: list[dict[str, Any]] = []
    group_count, last_step = 0, object()
    for item in found:
        if item["status"] >= 400 or (item["status"] == 0 and item["kind"] == "xhr"):
            continue                                   # failed when recorded: not part of the flow
        if item["index"] in asking:
            continue                                   # the page polling by itself
        step = step_of.get(item["after_seq"]) if item.get("after_seq") is not None else None
        url, body, headers = (_MARK.sub(value_of, item[k]) for k in ("url", "body", "headers"))
        path = url.split("?", 1)[0]
        step_id = step["id"] if step else None
        if step_id != last_step:                       # one step (or one screen opening) is one group: the calls it fired in a row
            group_count += 1
            last_step = step_id
        node = {
            "id": f"a{item['index']}", "step_id": step_id, "kind": "file" if item.get("file") else item["kind"],
            "via": item["kind"], **({"file": item["file"]} if item.get("file") else {}),
            **({"dialog": True} if item.get("target") == "dialog" else {}),     # the address of a dialog (showModalDialog): a message box of the page as likely as a file
            "group": f"g{group_count}", "group_label": describe(step) if step else "Mở màn hình",
            "label": f"{describe(step) if step else 'Mở màn hình'} → {item['method']} {path[-60:]}",
            "frame": item["frame"], "method": item["method"], "url": url, "headers": headers, "body": body,
            "links": {name: {**rule, "from": f"a{rule['from']}"} for name, rule in item.get("links", {}).items()},
            # risk: the step's, as the Learner decided it; a screen opening only reads
            "risk": (step or {}).get("risk", "read"), "complete": item["complete"], "answer": item.get("answer", ""),
            "ms": item.get("ms", 0), "shape": item.get("shape"),
        }
        names = set(_MARK.findall(url + body + headers))
        node["unresolved"] = sorted(n for n in names if n not in known and n not in node["links"])
        nodes.append(node)
    kept = {n["id"] for n in nodes}
    for node in nodes:                                 # a link to an answer that is not in the flow cannot be filled
        node["unresolved"] += sorted(name for name, rule in node["links"].items() if rule["from"] not in kept)
    return nodes


_RISK_RANK = {"read": 0, "write": 1, "money": 2}


def call_name(node: dict[str, Any]) -> str:
    """`POST /touchpoint/TPClassLoader`: the call as a person names it (no host, no query)."""
    path = re.sub(r"^[A-Za-z][A-Za-z0-9+.\-]*://[^/]*", "", str(node.get("url") or "").split("?", 1)[0])
    return f"{node.get('method', '')} {path[-60:]}".strip()


def _group_label(node: dict[str, Any]) -> str:
    if node.get("group_label"):
        return str(node["group_label"])
    label = str(node.get("label") or "")          # a flow saved before groups: "Bấm «X» → POST /path", the step's name is before the arrow
    return label.rsplit(" → ", 1)[0] if " → " in label else (label or "Mở màn hình")


def groups_of(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The steps of the flow: one step is ONE node that fires its batch of calls (docs/design.md 6.4). Calls with the same `group` form a
    step; a flow saved before groups existed has none, so consecutive calls of the same step (or of no step, the screen opening) are
    grouped here. Each: {id, step_id, label, risk, calls (node ids, in order), ms}."""
    groups: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    derived: set[str] = set()
    for node in nodes:
        explicit = node.get("group")
        current = groups[-1] if groups else None
        if explicit is not None:
            group = by_id.get(str(explicit))
            if group is not None and group["id"] in derived:     # an id made here for an older call is not the one a newer call names
                group = None
        else:
            group = current if current is not None and current["id"] in derived and current["step_id"] == node.get("step_id") else None
        if group is None:
            gid = str(explicit) if explicit is not None else f"g{len(groups) + 1}"
            while gid in by_id:
                gid += "_"
            group = {"id": gid, "step_id": node.get("step_id"), "label": _group_label(node), "risk": "read", "calls": [], "ms": 0}
            groups.append(group)
            by_id[gid] = group
            if explicit is None:
                derived.add(gid)
        group["calls"].append(node["id"])
        group["ms"] += int(node.get("ms") or 0)
        if _RISK_RANK.get(str(node.get("risk")), 0) > _RISK_RANK[group["risk"]]:
            group["risk"] = str(node["risk"])
        if node.get("mode") == "approve":     # task 10.7: a Duyệt added on the admin page before a read step
            group["approve"] = True
    return groups


# ---- 8.5: the run ----------------------------------------------------------------------------------------------------

def fill_in(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    """The marks of a template replaced by this run's values; the names that have no value are returned."""
    missing: list[str] = []

    def put(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in values and values[name] != "":
            return str(values[name])
        missing.append(name)
        return match.group(0)

    return _MARK.sub(put, text), missing


TWIN_BANNER = "BẢN SAO – không gửi hệ thống thật"
REFUSED_WORDS = re.compile(r"<input[^>]+type=[\"']?password|đăng nhập lại|session (?:has )?expired|phiên làm việc đã hết", re.IGNORECASE)


def refused(status: int, text: str) -> str:
    """Why the server did not take the request sent again, in plain words; "" when it did."""
    if status == 0:
        return "không nhận được trả lời"
    if status >= 400:
        return f"máy chủ trả mã {status}"
    if text.lstrip()[:4].startswith("//EX"):
        return "máy chủ GWT báo lỗi (//EX): có thể cần mã phiên hoặc mã chống giả mới"
    if REFUSED_WORDS.search(text[:20000]):
        return "máy chủ trả về trang đăng nhập: phiên đã hết, hãy đăng nhập lại trên IE"
    return ""


def _sign_in_steps(workflow: dict[str, Any]) -> set[str]:
    from rookie_agent.runner import is_manual

    steps = workflow.get("steps", [])
    login_end = next((i for i, s in enumerate(steps) if is_manual(s)), -1)
    ids = {s["id"] for s in steps[:login_end + 1]}
    if login_end >= 0 and login_end + 1 < len(steps) and steps[login_end + 1].get("action") == "click":
        ids.add(steps[login_end + 1]["id"])
    return ids


def align_template(template: str, live: str, name: str) -> str | None:
    """The value of mark `name` in `live`, a body the page really sent, by laying the template over it: the literal text must be equal, every
    mark stands for any text (lazy), both ends anchored. None when the body is not the one this template made."""
    names: list[str] = []
    parts: list[str] = []
    last = 0
    for match in _MARK.finditer(template):
        parts.append(re.escape(template[last:match.start()]))
        parts.append("(.*?)")
        names.append(match.group(1))
        last = match.end()
    parts.append(re.escape(template[last:]))
    if name not in names:
        return None
    found = re.fullmatch("".join(parts), live, re.DOTALL)
    if not found:
        return None
    value = found.group(names.index(name) + 1)
    return value if value else None


def _live_value(node: dict[str, Any], name: str, peek: Callable[[dict[str, Any]], list[str]] | None) -> str | None:
    """The value of link `name` as the live page sends it now: the newest of its last bodies for this node's path that fits the template."""
    if peek is None or OPEN + name + CLOSE not in node.get("body", ""):
        return None
    try:
        bodies = peek(node)
    except Exception:  # noqa: BLE001
        return None
    for live in reversed(list(bodies or [])):
        value = align_template(node["body"], str(live), name)
        if value is not None:
            return value
    return None


LIVE_SESSION = "phiên đang mở của trang IE"
NEED_LIVE = ("Hãy bấm Ghi rồi Dừng ngay một lần trên màn hình này (bật «Ghi yêu cầu»), hoặc thao tác mở màn hình một lần, "
             "để agent thấy mã phiên đang dùng; rồi Chạy lại.")


def run_api(workflow: dict[str, Any], nodes: list[dict[str, Any]], values: dict[str, str],
            send: Callable[[dict[str, Any], str, str, str], dict[str, Any]], controller: Any, stop: threading.Event,
            twin: bool = False, role: str = "maker",
            peek: Callable[[dict[str, Any]], list[str]] | None = None, read_rules: dict[str, Any] | None = None,
            confirmed: dict[str, Any] | None = None, remember: Callable[[str], None] | None = None,
            save_file: Callable[[bytes, str, str], dict[str, Any]] | None = None) -> dict[str, Any]:
    """The nodes in order. Each node: its inputs (what the teller typed, values linked from the answers before), the request sent
    from the teller's page, the answer. A node of the sign-in is passed over (the open page's session is used); a node that writes
    or moves money stops the run; anything missing or refused stops it and asks. `send(node, url, headers, body)` sends one.
    `twin=True` (Gate 9): `send` answers from a fake, nothing leaves the PC; a node that writes or moves money then waits for the
    person's Duyệt (never automatic) and goes on after it. In a `role` "checker" stage a stage with no such node still waits at its last one.
    `peek(node)` (real run only): the last bodies the live page sent to the node's path; a value that came from the sign-in answer is taken
    from the one that fits the node's template (the session the page uses now), never stored.
    A real run refuses a step that is not read, except a `write` step that is so only by default (no rule of `read_rules`, the "ie" section
    of config/risk-rules.json, matched it; `ie/read_rules.py`): the teller is asked «chỉ xem?» once (`controller.confirm_read`); «Chỉ xem»
    is kept by `remember(step_id)` and in `confirmed` ({step_id: ...}, the flow's own record) so a later run sends without asking. Money,
    a step an explicit rule matched, no rules, no `confirm_read`, any other answer: refused, nothing remembered.
    An answer that is a file (`answer["file"] = {data, ctype, disposition}`) is written by `save_file(data, ctype, disposition)` -> {name, path} on
    this PC and shown only as its name and size; a twin run saves nothing. A node that was a file and now answers a page or text stops."""
    groups = groups_of(nodes)
    steps_by_id = {s["id"]: s for s in workflow.get("steps", [])}
    confirmed = dict(confirmed or {})
    by_id = {n["id"]: n for n in nodes}
    done: list[dict[str, Any]] = []
    answers: dict[str, str] = {}                       # this run's answers, in memory only, for the links of the next calls
    started = time.monotonic()
    sign_in = _sign_in_steps(workflow)
    simulated_ms = 0
    last_id = next((g["id"] for g in reversed(groups) if g["step_id"] not in sign_in), None)
    asks = any(g["risk"] != "read" for g in groups if g["step_id"] not in sign_in)

    def note(group: dict[str, Any], status: str, detail: str, shown: dict[str, Any]) -> None:
        done.append({"id": group["id"], "status": status, "detail": detail})
        controller.progress(group["id"], status, detail)
        controller.show(group["id"], shown)

    def end(status: str, message: str) -> dict[str, Any]:
        result = {"status": status, "message": message, "steps": done, "seconds": round(time.monotonic() - started, 1)}
        if twin:
            result.update(twin=True, simulated_ms=simulated_ms)
        return result

    for group in groups:
        label = group["label"]
        if stop.is_set():
            return end("stopped", f"Dừng khẩn trước «{label}».")
        calls = [by_id[c] for c in group["calls"]]
        shown: dict[str, Any] = {"action": label, "risk": group["risk"], "requests": [], "inputs": [], "calls": len(calls)}
        if group["step_id"] in sign_in:
            twin_answered = False
            for node in calls:
                if twin and node.get("shape"):
                    # The twin answers the sign-in from its fake too (nothing is sent, the password is never used), so a value
                    # the next calls take from the sign-in answer (a session id) exists in the twin run.
                    answers[node["id"]] = str(send(node, node["url"], node["headers"], node["body"]).get("text") or "")
                    twin_answered = True
            note(group, "skipped", "đăng nhập: bản sao tự trả lời giả để có giá trị cho bước sau, không gửi gì" if twin_answered
                 else "đăng nhập: dùng phiên đang mở của trang IE", shown)
            continue
        controller.progress(group["id"], "running", "")
        if twin:
            shown["twin"] = TWIN_BANNER
        # every call of the step is listed from the start: those sent get their status and time, the others stay «chưa gửi»
        real_calls = [c for c in calls if c.get("kind") != "screen"]
        shown["requests"] = [{"method": c["method"], "url": c["url"], "state": NOT_SENT} for c in real_calls]
        slot = {c["id"]: i for i, c in enumerate(real_calls)}
        if group["risk"] == "read" and group.get("approve") and not twin:
            # a read step someone put under Duyệt on the admin page (task 10.7): the person says yes before anything is sent
            step = {"id": group["id"], "risk": "read", "action": "approve", "target": {"label": label}}
            if not controller.approve(step, groups.index(group), len(groups)):
                note(group, "rejected" if not stop.is_set() else "stopped", "người duyệt không đồng ý" if not stop.is_set() else "Dừng khẩn", shown)
                return end("stopped", f"«{label}» không được Duyệt: dừng, chưa gửi gì.")
        if twin and (group["risk"] != "read" or group.get("approve") or (role == "checker" and not asks and group["id"] == last_id)):
            step = {"id": group["id"], "risk": group["risk"] if group["risk"] != "read" else "write", "action": "approve", "target": {"label": label}}
            if not controller.approve(step, groups.index(group), len(groups)):      # one Duyệt for the whole step
                note(group, "rejected" if not stop.is_set() else "stopped", "người duyệt không đồng ý" if not stop.is_set() else "Dừng khẩn", shown)
                return end("stopped", f"«{label}» không được Duyệt: dừng (bản sao, chưa có gì gửi đi).")
        elif group["risk"] != "read" and _by_default(group, steps_by_id, read_rules):
            if group["step_id"] in confirmed:
                shown["confirmed_read"] = str((confirmed[group["step_id"]] or {}).get("at") or "")
            else:
                ask = getattr(controller, "confirm_read", None)
                answered = bool(ask(steps_by_id[group["step_id"]], groups.index(group), len(groups), [{"method": c["method"], "name": call_name(c)} for c in real_calls])) if ask else False
                if not answered or stop.is_set():
                    note(group, "refused" if not stop.is_set() else "stopped", "người dùng không xác nhận là chỉ xem: không gửi" if not stop.is_set() else "Dừng khẩn", shown)
                    if stop.is_set():
                        return end("stopped", f"Dừng khẩn trước «{label}».")
                    return end("refused", f"«{label}» có thể thay đổi dữ liệu: không gửi bằng request. Dùng «Chạy trên màn hình», có bước Duyệt.")
                if remember is not None:
                    remember(group["step_id"])
                confirmed[group["step_id"]] = {}
                shown["confirmed_read"] = "vừa xác nhận"
        elif group["risk"] != "read":
            note(group, "refused", "ghi dữ liệu hoặc tiền: không gửi bằng request", shown)
            return end("refused", f"«{label}» ghi dữ liệu hoặc chuyển tiền: không chạy bằng request. Dùng «Chạy trên màn hình», có bước Duyệt.")
        for node in calls:                              # nothing of the batch is sent while one of its calls cannot be
            if not node.get("complete") or node.get("unresolved"):
                why = ("lúc ghi request bị cắt bớt, hoặc có mật khẩu/mã chống giả không rõ nguồn" if not node.get("complete")
                       else "có giá trị chưa biết lấy từ đâu: " + ", ".join(node["unresolved"]))
                if node["id"] in slot:
                    shown["requests"][slot[node["id"]]]["error"] = why
                note(group, "needs_help", f"{call_name(node)}: {why}", shown)
                return end("needs_help", f"«{label}», lời gọi {call_name(node)}: không gửi lại được ({why}). Agent dừng để hỏi bạn.")
        group_ms = 0
        for node in calls:
            ref = call_name(node)
            here = dict(values)
            for name, rule in node.get("links", {}).items():
                value = take_value(answers.get(rule["from"], ""), rule)
                source = by_id.get(rule["from"])
                where = source["label"] if source is not None else rule["from"]
                from_sign_in = value is None and source is not None and source.get("step_id") in sign_in and not twin
                live = _live_value(node, name, peek) if from_sign_in else None
                if live is not None:
                    here[name] = live
                    _add_input(shown, name, LIVE_SESSION)
                    continue
                if from_sign_in:
                    why = (f"giá trị «{name}» lấy từ trả lời lúc đăng nhập («{where}»), mà lần chạy thật không đăng nhập lại "
                           "(dùng phiên đang mở, không gửi mật khẩu). Hãy Ghi lại khi đã đăng nhập sẵn: đăng nhập trước, mở màn hình cần làm, "
                           "rồi mới bấm Ghi; sau đó Học lại. Hoặc dùng «Chạy thử trên bản sao». " + NEED_LIVE.rstrip("."))
                    note(group, "needs_help", f"{ref}: {why}", shown)
                    return end("needs_help", f"«{label}», lời gọi {ref}: {why}.")
                if value is None:
                    why = f"không lấy được giá trị từ trả lời của «{where}»"
                    note(group, "needs_help", f"{ref}: {why}", shown)
                    return end("needs_help", f"«{label}», lời gọi {ref}: {why}. Agent dừng, không thử đoán.")
                here[name] = value
                _add_input(shown, name, where)
            for name in sorted(set(_MARK.findall(node["url"] + node["body"] + node["headers"])) - set(node.get("links", {}))):
                _add_input(shown, name, "GDV nhập")
            url, m1 = fill_in(node["url"], here)
            body, m2 = fill_in(node["body"], here)
            headers, m3 = fill_in(node["headers"], here)
            if m1 or m2 or m3:
                why = "còn thiếu: " + ", ".join(sorted(set(m1 + m2 + m3)))
                note(group, "needs_help", f"{ref}: {why}", shown)
                return end("needs_help", f"«{label}», lời gọi {ref}: {why}.")
            if twin and node.get("kind") == "screen":
                simulated_ms += int(node.get("ms") or 0)
                group_ms += int(node.get("ms") or 0)
                shown["screen"] = True
                continue
            answer = send(node, url, headers, body)
            simulated_ms += int(answer.get("ms") or 0)
            group_ms += int(answer.get("ms") or 0)
            sent: dict[str, Any] = {"method": node["method"], "url": url, "body": body[:4000], "status": answer.get("status", 0), "ms": answer.get("ms", 0)}
            shown["requests"][slot[node["id"]]] = sent
            if not answer.get("ok"):
                sent["error"] = {"no_frame": "không thấy khung trang lúc ghi (trang đã đổi màn hình?)", "timeout": "quá 30 giây không có trả lời",
                                 "too_big": f"file lớn hơn {files.MAX_MB} MB, không lưu"}.get(str(answer.get("error")), str(answer.get("error")))
                note(group, "failed", f"{ref}: {sent['error']}", shown)
                return end("failed", f"«{label}», lời gọi {ref}: {sent['error']}.")
            received = answer.get("file")
            if received is not None:
                # The answer is a file (a report as PDF): kept on this PC only, never read as text, never shown, never linked from.
                size = len(received.get("data") or b"")
                if size > files.MAX_BYTES:
                    sent["error"] = f"file lớn hơn {files.MAX_MB} MB, không lưu"
                    note(group, "failed", f"{ref}: {sent['error']}", shown)
                    return end("failed", f"«{label}», lời gọi {ref}: {sent['error']}.")
                if twin:
                    sent["file"] = {"name": "BẢN SAO – file giả, không lưu", "size": size, "size_text": files.size_text(size), "saved": False, "twin": True}
                else:
                    try:
                        saved = save_file(received["data"], str(received.get("ctype") or ""), str(received.get("disposition") or "")) if save_file else None
                    except OSError as error:
                        saved = None
                        sent["error"] = f"không lưu được file: {error}"
                    if saved is None:
                        sent["error"] = sent.get("error") or "không có chỗ lưu file"
                        note(group, "failed", f"{ref}: {sent['error']}", shown)
                        return end("failed", f"«{label}», lời gọi {ref}: {sent['error']}.")
                    sent["file"] = {"name": saved["name"], "path": saved["path"], "size": size, "size_text": files.size_text(size), "saved": True}
                answers[node["id"]] = ""
                continue
            text = str(answer.get("text") or "")
            answers[node["id"]] = text
            sent["view"] = response_view.summarize(text)
            if node.get("dialog"):
                # a dialog the page opened that shows a page (TouchPoint's own message box: Đồng ý, Hủy) is not a file this flow must get: skipped, nothing of it shown
                sent.pop("view", None)
                sent["skipped"] = "hộp thoại của trang, không phải file: bỏ qua"
                continue
            why = "" if twin else refused(int(answer.get("status") or 0), text)
            if not why and node.get("kind") == "file":
                why = "máy chủ trả về trang hoặc chữ chứ không phải file (có thể sai tiêu chí, hoặc báo cáo chưa sẵn sàng)"
            if why:
                sent["error"] = why
                note(group, "needs_help", f"{ref}: {why}", shown)
                return end("needs_help", f"«{label}», lời gọi {ref}: {why}. Agent dừng, không thử đoán.")
        if twin and shown.get("screen"):
            note(group, "done", f"màn hình · {group_ms} ms (mô phỏng)", shown)
        elif len(real_calls) == 1:
            only = shown["requests"][0]
            made = only.get("file")
            note(group, "done", (f"{'file giả (bản sao)' if made.get('twin') else 'đã lưu file'} · {made['size_text']} · {only.get('ms', 0)} ms" if made
                                 else f"{only.get('status')} · {only.get('ms', 0)} ms"), shown)
        else:
            note(group, "done", f"{len(real_calls)} lời gọi · {group_ms} ms", shown)
    return end("finished", "Chạy xong.")


NOT_SENT = "chưa gửi"


def _by_default(group: dict[str, Any], steps: dict[str, dict[str, Any]], rules: dict[str, Any] | None) -> bool:
    """A step of a real run that is `write` only because no rule matched it (never money, never an explicit write rule)."""
    from rookie_agent.ie import read_rules

    step = steps.get(group["step_id"]) if group["step_id"] is not None else None
    return group["risk"] == "write" and step is not None and read_rules.write_by_default(step, rules)


def _add_input(shown: dict[str, Any], name: str, source: str) -> None:
    item = {"name": name, "from": source}
    if item not in shown["inputs"]:
        shown["inputs"].append(item)
