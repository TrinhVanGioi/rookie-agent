"""The MCP tools and the two transports (see rookie_agent/mcp/__init__.py)."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

PROTOCOL = "2025-06-18"
PAGE = "http://127.0.0.1:8765"
NOT_OPEN = "Trang quản lý chưa mở. Chạy `python -m rookie_agent web` (hoặc bấm biểu tượng Rookie Agent) rồi thử lại."
STATES = {"running": "running", "waiting_approval": "waiting_for_human", "waiting_review": "waiting_for_human", "waiting_pick": "waiting_for_human",
          "waiting_read": "waiting_for_human", "finished": "finished", "failed": "failed", "stopped": "stopped", "rejected": "stopped",
          "refused": "failed", "needs_help": "waiting_for_human", "idle": "idle"}
ROLES = {"list_flows": ("maker", "checker"), "plan_from_sentence": ("maker",), "start_run": ("maker",), "get_run_status": ("maker", "checker"),
         "stop_run": ("maker", "checker")}

TOOLS = [
    {"name": "list_flows", "description": "Liệt kê các quy trình đã được duyệt trên máy giao dịch viên: tên, các ô cần nhập, mức rủi ro cao nhất. Không trả giá trị nào.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "plan_from_sentence", "description": "Hiểu một câu tiếng Việt (ví dụ «xuất sao kê tài khoản X từ ngày A đến ngày B»): chọn quy trình, điền ô, nói còn thiếu gì. Không chạy gì.",
     "inputSchema": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 500}}, "additionalProperties": False}},
    {"name": "start_run", "description": "Chạy một thẻ đã sẵn sàng (plan_id từ plan_from_sentence). Bước ghi dữ liệu hoặc tiền luôn dừng chờ người bấm Duyệt trên trang; công cụ này không duyệt được.",
     "inputSchema": {"type": "object", "required": ["plan_id", "idempotency_key"], "additionalProperties": False,
                     "properties": {"plan_id": {"type": "string", "minLength": 1}, "idempotency_key": {"type": "string", "pattern": "^[A-Za-z0-9_.:-]{8,80}$"},
                                    "window": {"type": "string", "description": "Trang IE để chạy (ie-tab:<id>); bỏ trống khi chỉ mở một trang TouchPoint."}}}},
    {"name": "get_run_status", "description": "Trạng thái lần chạy: running, waiting_for_human (chờ người Duyệt hoặc cần người giúp), finished, failed, stopped; kèm các bước (tên, trạng thái).",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "stop_run", "description": "Dừng khẩn lần chạy đang chạy. Luôn được phép.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]


class PageClosed(RuntimeError):
    pass


def page_call(method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 20.0, base: str = PAGE) -> dict[str, Any]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-Rookie": "1"}
    request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return json.loads(reply.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8", "replace")).get("error")
        except (ValueError, AttributeError):
            detail = None
        raise RuntimeError(detail or f"Trang quản lý trả lỗi {error.code}") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise PageClosed(NOT_OPEN) from None


class Tools:
    """The five tools. `call` is the page (method, path, body) -> dict; tests give a fake one."""

    def __init__(self, call: Callable[..., dict[str, Any]] = page_call, role: str | None = None, run_timeout: float | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.call = call
        self.role = (role or os.environ.get("ROOKIE_MCP_ROLE") or "maker").strip().lower()
        self.run_timeout = float(run_timeout if run_timeout is not None else os.environ.get("ROOKIE_MCP_RUN_TIMEOUT") or 900)
        self.clock = clock
        self.keys: dict[str, dict[str, Any]] = {}           # idempotency_key -> the first answer
        self.lock = threading.Lock()
        self.watch: threading.Thread | None = None

    def audit(self, tool: str, status: str, started: float, title: str = "", names: list[str] | None = None, key: str = "") -> None:
        try:
            self.call("POST", "/api/mcp/audit", {"tool": tool, "status": status, "seconds": round(self.clock() - started, 2), "title": title,
                                                 "input_names": names or [], "idempotency_key": key})
        except Exception:  # noqa: BLE001  an audit line that cannot be written never hides the answer
            pass

    # ---- the tools ------------------------------------------------------------------------------------------------------

    def list_flows(self, _: dict[str, Any]) -> dict[str, Any]:
        rows = self.call("GET", "/api/flows").get("flows") or []
        order = {"read": 0, "write": 1, "money": 2}
        out = []
        for flow in rows:
            if not flow.get("approved"):
                continue
            risks = [str(s.get("risk_key") or "read") for s in flow.get("steps") or []] + [str(n.get("risk") or "read") for n in flow.get("api_nodes") or []]
            out.append({"title": flow.get("title"), "inputs": [{"name": i.get("name"), "label": i.get("label")} for i in flow.get("input_fields") or []],
                        "max_risk": max(risks, key=lambda r: order.get(r, 2), default="read"), "returns_by_request": bool(flow.get("has_api"))})
        return {"flows": out}

    def plan_from_sentence(self, args: dict[str, Any]) -> dict[str, Any]:
        card = self.call("POST", "/api/assistant/plan", {"text": str(args.get("text") or "")})
        workflow = card.get("workflow") or {}
        return {"plan_id": card.get("plan_id"), "state": card.get("state"), "message": card.get("message"),
                "flow": workflow.get("title") if isinstance(workflow, dict) else workflow,
                "inputs": [{"name": i.get("name"), "label": i.get("label"), "filled": bool(i.get("value"))} for i in card.get("inputs") or []],
                "questions": list(card.get("questions") or []),
                "candidates": [c.get("title") for c in card.get("candidates") or [] if isinstance(c, dict)]}

    def _window(self, given: str) -> str:
        if given:
            return given
        tabs = self.call("GET", "/api/windows").get("ie") or []
        if len(tabs) != 1:
            raise RuntimeError("Đang mở " + str(len(tabs)) + " trang Internet Explorer: cho biết chạy trên trang nào (window = ie-tab:<id>).")
        return f"ie-tab:{tabs[0]['id']}"

    def start_run(self, args: dict[str, Any]) -> dict[str, Any]:
        key = str(args.get("idempotency_key") or "")
        with self.lock:
            if key in self.keys:
                return {**self.keys[key], "repeated": True}       # the same key never runs twice
        reply = self.call("POST", "/api/assistant/run", {"plan_id": str(args.get("plan_id") or ""), "window": self._window(str(args.get("window") or ""))})
        answer = {"started": bool(reply.get("started", True)), "message": "Đã bắt đầu. Hỏi get_run_status để biết tiến độ; bước cần Duyệt chờ người bấm trên trang."}
        with self.lock:
            self.keys[key] = answer
        self._watch(key)
        return answer

    def _watch(self, key: str) -> None:
        """The total time limit: past it, the run is stopped (Dừng khẩn) and the audit says timeout."""
        started = self.clock()

        def watch() -> None:
            while self.clock() - started < self.run_timeout:
                time.sleep(min(2.0, max(0.05, self.run_timeout / 50)))
                try:
                    state = self.call("GET", "/api/run/status").get("state")
                except Exception:  # noqa: BLE001
                    return
                if state not in ("running", "waiting_approval", "waiting_review", "waiting_pick", "waiting_read"):
                    return
            try:
                self.call("POST", "/api/run/stop", {})
            finally:
                self.audit("start_run", "timeout", started, key=key)

        self.watch = threading.Thread(target=watch, name="mcp-run-timeout", daemon=True)
        self.watch.start()

    def get_run_status(self, _: dict[str, Any]) -> dict[str, Any]:
        state = self.call("GET", "/api/run/status")
        result = state.get("result") or {}
        ask = state.get("ask") or None
        out = {"state": STATES.get(str(result.get("status") or state.get("state")), str(state.get("state"))), "title": state.get("title"),
               "steps": [{"id": s.get("id"), "status": s.get("status")} for s in state.get("steps") or []]}
        if ask:
            out["waiting_for"] = {"kind": ask.get("kind"), "risk": ask.get("risk"), "step": ask.get("step_id") or ask.get("id"),
                                  "message": "Chờ giao dịch viên hoặc kiểm soát viên bấm trên trang quản lý."}
        if result:
            out["result"] = {"status": result.get("status"), "message": str(result.get("message") or "")[:300]}
            files = [r["file"]["name"] for d in (state.get("details") or {}).values() for r in (d or {}).get("requests") or [] if (r.get("file") or {}).get("saved")]
            if files:
                out["result"]["files"] = files        # the name only: the file stays on this PC
        return out

    def stop_run(self, _: dict[str, Any]) -> dict[str, Any]:
        self.call("POST", "/api/run/stop", {})
        return {"stopped": True}

    # ---- one call ------------------------------------------------------------------------------------------------------

    def run_tool(self, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        started = self.clock()
        if name not in ROLES:
            return {"error": f"Không có công cụ {name}."}, True
        if self.role not in ROLES[name]:
            self.audit(name, "forbidden", started)
            return {"error": f"Vai trò {self.role} không được dùng {name}."}, True
        try:
            result = getattr(self, name)(args or {})
        except PageClosed as error:
            self.audit(name, "page_closed", started)
            return {"error": str(error)}, True
        except Exception as error:  # noqa: BLE001  the message is the page's, already in Vietnamese and without values
            self.audit(name, "error", started)
            return {"error": str(error)[:300]}, True
        names = [i.get("name") for i in result.get("inputs") or [] if isinstance(i, dict) and i.get("name")] if name == "plan_from_sentence" else []
        self.audit(name, "ok", started, title=str(result.get("flow") or result.get("title") or ""), names=names, key=str((args or {}).get("idempotency_key") or ""))
        return result, False


def handle(tools: Tools, message: dict[str, Any]) -> dict[str, Any] | None:
    """One JSON-RPC message in, its answer out (None for a notification)."""
    method, ident = message.get("method"), message.get("id")
    if ident is None:
        return None
    if method == "initialize":
        result: Any = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {"listChanged": False}},
                       "serverInfo": {"name": "rookie-agent", "version": "1"},
                       "instructions": "Gọi các quy trình đã học trên máy giao dịch viên. Không duyệt được bước ghi hay tiền: người bấm Duyệt trên trang."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        content, failed = tools.run_tool(str(params.get("name") or ""), params.get("arguments") or {})
        result = {"content": [{"type": "text", "text": json.dumps(content, ensure_ascii=False)}], "structuredContent": content, "isError": failed}
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"Không có phương thức {method}"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def serve_stdio(tools: Tools) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            reply: dict[str, Any] | None = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON không hợp lệ"}}
        else:
            reply = handle(tools, message)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def make_http(tools: Tools, port: int, token: str, allowed: set[str], host: str = "0.0.0.0") -> ThreadingHTTPServer:
    if len(token) < 24:
        raise SystemExit("ROOKIE_MCP_TOKEN phải dài ít nhất 24 ký tự.")

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict[str, Any] | None) -> None:
            data = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            if self.client_address[0] not in allowed:
                return self._send(403, {"error": "Địa chỉ này không được phép."})
            if self.path != "/mcp" or self.headers.get("Authorization") != "Bearer " + token:
                return self._send(401, {"error": "Thiếu hoặc sai mã truy cập."})
            try:
                message = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 100_000)).decode("utf-8"))
            except ValueError:
                return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON không hợp lệ"}})
            reply = handle(tools, message)
            self._send(202 if reply is None else 200, reply)

        def log_message(self, *args: Any) -> None:
            pass

    return ThreadingHTTPServer((host, port), Handler)


def main(argv: list[str]) -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="rookie_agent mcp")
    parser.add_argument("--http", type=int, default=0, help="nghe HTTP ở cổng này thay vì stdio (Codie ở máy khác)")
    parser.add_argument("--allow", default="127.0.0.1", help="các địa chỉ được gọi, cách nhau bằng dấu phẩy")
    options = parser.parse_args(argv)
    tools = Tools()
    if options.http:
        server = make_http(tools, options.http, os.environ.get("ROOKIE_MCP_TOKEN", ""), {a.strip() for a in options.allow.split(",") if a.strip()})
        server.serve_forever()
    else:
        serve_stdio(tools)
