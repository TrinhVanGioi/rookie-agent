"""Gate 7: a learned flow run by its requests, simulated on the canvas (docs/design.md 6.3).

When a recording stops, the requests the page made become templates: what the teller typed is replaced by a mark of the event that
typed it (never kept as a value). When the flow is learned, each mark becomes the step's own value (`{name}` of an input, or the
plain text the step always types) and the templates are put under the step that made them. A simulated run sends them again from
inside the teller's IE page (the page's own session; no cookie is read) and shows what came back. Only read-only steps are sent.
"""

from __future__ import annotations

import re
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Callable

from rookie_agent.ie import response_view

MIN_TYPED = 3           # a shorter typed value could be found by chance in a request: it is left as it is
OPEN, CLOSE = "⟦", "⟧"   # ⟦e7⟧ at the stop, ⟦cif⟧ after learning: never mistaken for the braces of a JSON body
_MARK = re.compile(OPEN + r"([a-z0-9_]+)" + CLOSE)
_HIDDEN = '"***"'       # what the page recorder puts in place of a password, PIN, OTP or token: such a request cannot be sent again


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


def templates(raw: list[dict[str, Any]], events: list[dict[str, Any]], requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """7.1: the requests of one recording as templates. Only lines that became events count as typed (a password never does)."""
    typed: list[tuple[str, int]] = []
    for line in raw:
        if str(line.get("kind")) not in ("input", "select"):
            continue
        value = str(line.get("value") or "")
        seq = _seq_at(events, line.get("t"), ("input", "select"))
        if seq is not None and len(value.strip()) >= MIN_TYPED:
            typed.append((value, seq))
    typed.sort(key=lambda item: -len(item[0]))     # the longest first, so a value inside another is not cut in two

    def marked(text: str) -> str:
        for value, seq in typed:
            mark = f"{OPEN}e{seq}{CLOSE}"
            for form in dict.fromkeys((value, urllib.parse.quote(value, safe=""), urllib.parse.quote_plus(value))):
                text = text.replace(form, mark)
        return text

    out: list[dict[str, Any]] = []
    for item in requests:
        url, body = str(item.get("url") or ""), str(item.get("req") or "")
        after = item.get("after") or {}
        out.append({
            "after_seq": _seq_at(events, after.get("t")),
            "frame": str(item.get("frame") or "top"), "method": str(item.get("method") or "GET").upper(),
            "url": marked(url), "headers": str(item.get("hdr") or ""), "body": marked(body),
            "complete": not item.get("cut") and _HIDDEN not in body and body != "[object]",
            "status": int(item.get("status") or 0), "kind": response_view.kind_of(str(item.get("res") or "")),
        })
    return out


def attach(workflow: dict[str, Any], events: list[dict[str, Any]], found: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """7.2: the templates of the recording put under the steps of the learned flow. An event belongs to the step that has its first
    selector; a mark becomes that step's value. A mark no step explains leaves the template unable to run (`unresolved`)."""
    step_of: dict[int, dict[str, Any]] = {}
    for event in events:
        first = ((event.get("target") or {}).get("selectors") or [None])[0]
        for step in workflow.get("steps", []):
            if first and first in ((step.get("target") or {}).get("selectors") or []) and _same_kind(event, step):
                step_of[int(event["seq"])] = step
                break

    def value_of(match: re.Match[str]) -> str:
        name = match.group(1)
        step = step_of.get(int(name[1:])) if name.startswith("e") and name[1:].isdigit() else None
        if step is None or step.get("value") is None:
            return match.group(0)
        text = str(step["value"])
        inner = re.fullmatch(r"\{([a-z][a-z0-9_]*)\}", text)
        return f"{OPEN}{inner.group(1)}{CLOSE}" if inner else text

    by_step: dict[str, list[dict[str, Any]]] = {}
    for item in found:
        step = step_of.get(item["after_seq"]) if item.get("after_seq") is not None else None
        if step is None or item["status"] >= 400 or item["status"] == 0:
            continue      # a request before any step (the page loading) or one that failed when recorded is not part of the flow
        done = {**item, "url": _MARK.sub(value_of, item["url"]), "body": _MARK.sub(value_of, item["body"])}
        names = set(_MARK.findall(done["url"] + done["body"]))
        known = {i["name"] for i in workflow.get("inputs", [])}
        done["unresolved"] = sorted(n for n in names if n not in known)
        by_step.setdefault(step["id"], []).append(done)
    return by_step


def _same_kind(event: dict[str, Any], step: dict[str, Any]) -> bool:
    return {"input": "fill", "select": "select", "click": "click", "submit": "submit"}.get(str(event.get("type"))) == step.get("action")


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


REFUSED_WORDS = re.compile(r"<input[^>]+type=[\"']?password|đăng nhập lại|session (?:has )?expired|phiên làm việc đã hết", re.IGNORECASE)


def refused(status: int, text: str) -> str:
    """Why the server did not take the request sent again, in plain words; "" when it did."""
    if status == 0:
        return "không nhận được trả lời"
    if status >= 400:
        return f"máy chủ trả mã {status}"
    head = text.lstrip()[:4]
    if head.startswith("//EX"):
        return "máy chủ GWT báo lỗi (//EX): có thể cần mã phiên hoặc mã chống giả mới"
    if REFUSED_WORDS.search(text[:20000]):
        return "máy chủ trả về trang đăng nhập: phiên đã hết, hãy đăng nhập lại trên IE"
    return ""


def simulate(workflow: dict[str, Any], by_step: dict[str, list[dict[str, Any]]], values: dict[str, str],
             send: Callable[[dict[str, Any], str, str], dict[str, Any]], controller: Any, stop: threading.Event,
             describe: Callable[[dict[str, Any]], str] = lambda step: step["id"]) -> dict[str, Any]:
    """7.5: the steps in order; a read-only step with requests sends them and shows the answer; a step that only works the screen is
    passed over; a step that writes or moves money stops the run. `send(template, url, body)` sends one request. Nothing is guessed."""
    steps_done: list[dict[str, Any]] = []
    started = time.monotonic()

    def note(step: dict[str, Any], status: str, detail: str, shown: dict[str, Any]) -> None:
        steps_done.append({"id": step["id"], "status": status, "detail": detail})
        controller.progress(step["id"], status, detail)
        controller.show(step["id"], shown)

    def end(status: str, message: str) -> dict[str, Any]:
        return {"status": status, "message": message, "steps": steps_done, "seconds": round(time.monotonic() - started, 1)}

    for step in workflow.get("steps", []):
        if stop.is_set():
            return end("stopped", f"Dừng khẩn trước bước {step['id']}.")
        found = by_step.get(step["id"], [])
        shown: dict[str, Any] = {"action": describe(step), "risk": step.get("risk"), "requests": []}
        controller.progress(step["id"], "running", "")
        if step.get("risk") != "read":
            if found:
                note(step, "refused", "bước ghi dữ liệu hoặc tiền: không chạy bằng request", shown)
                return end("refused", f"Bước {step['id']} ghi dữ liệu hoặc chuyển tiền: không chạy bằng request. "
                                      "Dùng «Chạy» trên màn hình, có bước Duyệt.")
            note(step, "skipped", "chỉ thao tác trên màn hình", shown)
            continue
        if not found:
            note(step, "skipped", "chỉ thao tác trên màn hình, không có request", shown)
            continue
        for item in found:
            if not item.get("complete") or item.get("unresolved"):
                why = ("lúc ghi request bị cắt bớt hoặc có mật khẩu/mã đã che" if not item.get("complete")
                       else "request có giá trị chưa biết lấy từ đâu: " + ", ".join(item["unresolved"]))
                shown["requests"].append({"method": item["method"], "url": item["url"], "error": why})
                note(step, "needs_help", why, shown)
                return end("needs_help", f"Bước {step['id']}: không gửi lại được ({why}). Agent dừng để hỏi bạn.")
            url, missing_url = fill_in(item["url"], values)
            body, missing_body = fill_in(item["body"], values)
            if missing_url or missing_body:
                why = "còn thiếu: " + ", ".join(sorted(set(missing_url + missing_body)))
                note(step, "needs_help", why, shown)
                return end("needs_help", f"Bước {step['id']}: {why}.")
            answer = send(item, url, body)
            sent = {"method": item["method"], "url": url, "body": body[:4000], "status": answer.get("status", 0), "ms": answer.get("ms", 0)}
            if not answer.get("ok"):
                sent["error"] = {"no_frame": "không thấy khung trang lúc ghi (trang đã đổi màn hình?)", "timeout": "quá 30 giây không có trả lời"}.get(
                    str(answer.get("error")), str(answer.get("error")))
                shown["requests"].append(sent)
                note(step, "failed", sent["error"], shown)
                return end("failed", f"Bước {step['id']}: {sent['error']}.")
            text = str(answer.get("text") or "")
            sent["view"] = response_view.summarize(text)
            why = refused(int(answer.get("status") or 0), text)
            shown["requests"].append(sent)
            if why:
                sent["error"] = why
                note(step, "needs_help", why, shown)
                return end("needs_help", f"Bước {step['id']}: {why}. Agent dừng, không thử đoán.")
            if stop.is_set():
                note(step, "stopped", "Dừng khẩn", shown)
                return end("stopped", f"Dừng khẩn ở bước {step['id']}.")
        note(step, "done", f"{len(found)} request", shown)
    return end("finished", "Chạy mô phỏng xong.")
