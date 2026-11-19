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

from rookie_agent.ie import response_view, shape as shaper

MIN_TYPED = 3           # a shorter typed value could be found by chance in a request: it is left as it is
MIN_LINKED = 4
OPEN, CLOSE = "⟦", "⟧"   # ⟦e7⟧, ⟦l1⟧, ⟦cif⟧: never mistaken for the braces of a JSON body
_MARK = re.compile(OPEN + r"([a-z0-9_]+)" + CLOSE)
_HIDDEN = '"***"'
_TOKEN_CANDIDATE = re.compile(r"[A-Za-z0-9_\-.~%+/]{4,}={0,2}")
_TOKEN_KEY = re.compile(r"((?:token|secret|csrf|xsrf|nonce)[a-z_]*[\"']?\s*[:=]\s*)(\"(?:[^\"\\]|\\.)*\"|'[^']*'|[^&,}\s|]*)", re.IGNORECASE)
_CLASS_LIKE = re.compile(r"^[a-z][\w$]*(\.[\w$]+){2,}(/\d+)?$")
POLLING = 3             # the same request this many times or more is the page polling: not part of the flow unless a later one needs it


def _iso(milliseconds: int) -> str:
    moment = datetime.fromtimestamp(milliseconds / 1000.0, tz=timezone.utc)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


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
    start = answer.find(rule["before"])
    if start < 0:
        return None
    start += len(rule["before"])
    end = answer.find(rule["after"], start)
    return answer[start:end] if end > start else None


# ---- 7.1 and 8.1 to 8.3: the requests of one recording as templates -------------------------------------------------

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
        for value, seq in typed:
            mark = f"{OPEN}e{seq}{CLOSE}"
            for form in dict.fromkeys((value, urllib.parse.quote(value, safe=""), urllib.parse.quote_plus(value))):
                text = text.replace(form, mark)
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
                if (len(value) < MIN_LINKED or value in typed_values or OPEN in value or _CLASS_LIKE.match(value)
                        or not (any(c.isdigit() for c in value) or len(value) >= 16)):
                    continue
                for source in range(index - 1, -1, -1):
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
        after = item.get("after") or {}
        out.append({
            "index": index, "after_seq": _seq_at(events, after.get("t")), "kind": str(item.get("kind") or "xhr"),
            "frame": str(item.get("frame") or "top"), "method": str(item.get("method") or "GET").upper(),
            "url": url, "headers": headers, "body": body, "links": links,
            "complete": not item.get("cut") and not hidden and "***" not in body and body != "[object]",
            "status": int(item.get("status") or 0), "answer": response_view.kind_of(str(item.get("res") or "")),
            "ms": int(item.get("ms") or 0),
        })
    for index, item in enumerate(out):   # task 9.4: the answer's skeleton (no value), made so that the links to it still find a value
        rules = [rule for other in out for rule in other["links"].values() if rule["from"] == index]
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

    needed = {link["from"] for item in found for link in item.get("links", {}).values()}
    signature = [(t["method"], t["url"], t["body"]) for t in found]
    known = {i["name"] for i in workflow.get("inputs", [])}
    nodes: list[dict[str, Any]] = []
    for item in found:
        if item["status"] >= 400 or (item["status"] == 0 and item["kind"] == "xhr"):
            continue                                   # failed when recorded: not part of the flow
        if signature.count((item["method"], item["url"], item["body"])) >= POLLING and item["index"] not in needed:
            continue                                   # the page polling by itself
        step = step_of.get(item["after_seq"]) if item.get("after_seq") is not None else None
        url, body, headers = (_MARK.sub(value_of, item[k]) for k in ("url", "body", "headers"))
        path = url.split("?", 1)[0]
        node = {
            "id": f"a{item['index']}", "step_id": step["id"] if step else None, "kind": item["kind"],
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


def run_api(workflow: dict[str, Any], nodes: list[dict[str, Any]], values: dict[str, str],
            send: Callable[[dict[str, Any], str, str, str], dict[str, Any]], controller: Any, stop: threading.Event,
            twin: bool = False, role: str = "maker") -> dict[str, Any]:
    """The nodes in order. Each node: its inputs (what the teller typed, values linked from the answers before), the request sent
    from the teller's page, the answer. A node of the sign-in is passed over (the open page's session is used); a node that writes
    or moves money stops the run; anything missing or refused stops it and asks. `send(node, url, headers, body)` sends one.
    `twin=True` (Gate 9): `send` answers from a fake, nothing leaves the PC; a node that writes or moves money then waits for the
    person's Duyệt (never automatic) and goes on after it. In a `role` "checker" stage a stage with no such node still waits at its last one."""
    done: list[dict[str, Any]] = []
    answers: dict[str, str] = {}                       # this run's answers, in memory only, for the links of the next nodes
    started = time.monotonic()
    sign_in = _sign_in_steps(workflow)
    simulated_ms = 0
    last_id = next((n["id"] for n in reversed(nodes) if n.get("step_id") not in sign_in), None)
    asks = any(n["risk"] != "read" for n in nodes if n.get("step_id") not in sign_in)

    def note(node: dict[str, Any], status: str, detail: str, shown: dict[str, Any]) -> None:
        done.append({"id": node["id"], "status": status, "detail": detail})
        controller.progress(node["id"], status, detail)
        controller.show(node["id"], shown)

    def end(status: str, message: str) -> dict[str, Any]:
        result = {"status": status, "message": message, "steps": done, "seconds": round(time.monotonic() - started, 1)}
        if twin:
            result.update(twin=True, simulated_ms=simulated_ms)
        return result

    for node in nodes:
        if stop.is_set():
            return end("stopped", f"Dừng khẩn trước «{node['label']}».")
        shown: dict[str, Any] = {"action": node["label"], "risk": node["risk"], "requests": [], "inputs": []}
        if node.get("step_id") in sign_in:
            if twin and node.get("shape"):
                # The twin answers the sign-in from its fake too (nothing is sent, the password is never used), so a value
                # the next calls take from the sign-in answer (a session id) exists in the twin run.
                answers[node["id"]] = str(send(node, node["url"], node["headers"], node["body"]).get("text") or "")
                note(node, "skipped", "đăng nhập: bản sao tự trả lời giả để có giá trị cho bước sau, không gửi gì", shown)
            else:
                note(node, "skipped", "đăng nhập: dùng phiên đang mở của trang IE", shown)
            continue
        controller.progress(node["id"], "running", "")
        if twin:
            shown["twin"] = TWIN_BANNER
        if twin and (node["risk"] != "read" or (role == "checker" and not asks and node["id"] == last_id)):
            step = {"id": node["id"], "risk": node["risk"] if node["risk"] != "read" else "write", "action": "approve", "target": {"label": node["label"]}}
            if not controller.approve(step, nodes.index(node), len(nodes)):
                note(node, "rejected" if not stop.is_set() else "stopped", "người duyệt không đồng ý" if not stop.is_set() else "Dừng khẩn", shown)
                return end("stopped", f"«{node['label']}» không được Duyệt: dừng (bản sao, chưa có gì gửi đi).")
        elif node["risk"] != "read":
            note(node, "refused", "ghi dữ liệu hoặc tiền: không gửi bằng request", shown)
            return end("refused", f"«{node['label']}» ghi dữ liệu hoặc chuyển tiền: không chạy bằng request. Dùng «Chạy trên màn hình», có bước Duyệt.")
        if not node.get("complete") or node.get("unresolved"):
            why = ("lúc ghi request bị cắt bớt, hoặc có mật khẩu/mã chống giả không rõ nguồn" if not node.get("complete")
                   else "có giá trị chưa biết lấy từ đâu: " + ", ".join(node["unresolved"]))
            shown["requests"].append({"method": node["method"], "url": node["url"], "error": why})
            note(node, "needs_help", why, shown)
            return end("needs_help", f"«{node['label']}»: không gửi lại được ({why}). Agent dừng để hỏi bạn.")
        here = dict(values)
        for name, rule in node.get("links", {}).items():
            value = take_value(answers.get(rule["from"], ""), rule)
            where = next((n["label"] for n in nodes if n["id"] == rule["from"]), rule["from"])
            source = next((n for n in nodes if n["id"] == rule["from"]), None)
            if value is None and source is not None and source.get("step_id") in sign_in and not twin:
                why = (f"giá trị «{name}» lấy từ trả lời lúc đăng nhập («{where}»), mà lần chạy thật không đăng nhập lại "
                       "(dùng phiên đang mở, không gửi mật khẩu). Hãy Ghi lại khi đã đăng nhập sẵn: đăng nhập trước, mở màn hình cần làm, "
                       "rồi mới bấm Ghi; sau đó Học lại. Hoặc dùng «Chạy thử trên bản sao»")
                note(node, "needs_help", why, shown)
                return end("needs_help", f"«{node['label']}»: {why}.")
            if value is None:
                why = f"không lấy được giá trị từ trả lời của «{where}»"
                note(node, "needs_help", why, shown)
                return end("needs_help", f"«{node['label']}»: {why}. Agent dừng, không thử đoán.")
            here[name] = value
            shown["inputs"].append({"name": name, "from": where})
        for name in sorted(set(_MARK.findall(node["url"] + node["body"] + node["headers"])) - set(node.get("links", {}))):
            shown["inputs"].append({"name": name, "from": "GDV nhập"})
        url, m1 = fill_in(node["url"], here)
        body, m2 = fill_in(node["body"], here)
        headers, m3 = fill_in(node["headers"], here)
        if m1 or m2 or m3:
            why = "còn thiếu: " + ", ".join(sorted(set(m1 + m2 + m3)))
            note(node, "needs_help", why, shown)
            return end("needs_help", f"«{node['label']}»: {why}.")
        if twin and node.get("kind") == "screen":
            simulated_ms += int(node.get("ms") or 0)
            shown["screen"] = True
            note(node, "done", f"màn hình · {node.get('ms') or 0} ms (mô phỏng)", shown)
            continue
        answer = send(node, url, headers, body)
        simulated_ms += int(answer.get("ms") or 0)
        sent: dict[str, Any] = {"method": node["method"], "url": url, "body": body[:4000], "status": answer.get("status", 0), "ms": answer.get("ms", 0)}
        shown["requests"].append(sent)
        if not answer.get("ok"):
            sent["error"] = {"no_frame": "không thấy khung trang lúc ghi (trang đã đổi màn hình?)", "timeout": "quá 30 giây không có trả lời"}.get(
                str(answer.get("error")), str(answer.get("error")))
            note(node, "failed", sent["error"], shown)
            return end("failed", f"«{node['label']}»: {sent['error']}.")
        text = str(answer.get("text") or "")
        answers[node["id"]] = text
        sent["view"] = response_view.summarize(text)
        why = "" if twin else refused(int(answer.get("status") or 0), text)
        if why:
            sent["error"] = why
            note(node, "needs_help", why, shown)
            return end("needs_help", f"«{node['label']}»: {why}. Agent dừng, không thử đoán.")
        note(node, "done", f"{answer.get('status')} · {answer.get('ms', 0)} ms", shown)
    return end("finished", "Chạy xong.")
