"""Task 11.9: the MCP server for Genie Codie: five tools, no tool to approve, no value out, one key one run, a total time limit,
an audit line per call, a clear answer when the page is closed; the same over HTTP with a token, only from allowed addresses."""

from __future__ import annotations

import json
import threading
import time
import urllib.request

import pytest

from rookie_agent.mcp import server


class Page:
    """The local page (http://127.0.0.1:8765) as the tools see it."""

    def __init__(self, run_states=("running", "finished")):
        self.calls, self.audit, self.states = [], [], list(run_states)

    def __call__(self, method, path, body=None, **_):
        self.calls.append((method, path, body))
        if path == "/api/mcp/audit":
            self.audit.append(body)
            return {"ok": True}
        if path == "/api/flows":
            return {"flows": [{"title": "Sao kê", "approved": True, "has_api": True, "input_fields": [{"name": "so_tai_khoan", "label": "Số tài khoản"}],
                               "steps": [{"risk_key": "read"}], "api_nodes": [{"risk": "read"}]},
                              {"title": "Nháp", "approved": False, "input_fields": [], "steps": []}]}
        if path == "/api/assistant/plan":
            return {"plan_id": "p1", "state": "ready", "message": "Sẵn sàng", "workflow": {"title": "Sao kê"},
                    "inputs": [{"name": "so_tai_khoan", "label": "Số tài khoản", "value": "0123456789"}], "questions": [], "candidates": []}
        if path == "/api/windows":
            return {"ie": [{"id": 7, "title": "TouchPoint"}]}
        if path == "/api/assistant/run":
            return {"started": True}
        if path == "/api/run/status":
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            return {"state": state, "title": "Sao kê", "steps": [{"id": "g1", "status": "done", "detail": "Đã gửi 0123456789"}],
                    "ask": {"kind": "approve", "risk": "write", "step_id": "g2", "label": "NGUYEN VAN AN"} if state == "waiting_approval" else None,
                    "result": {"status": "finished", "message": "Xong", "view": {"rows": [["NGUYEN VAN AN"]]}} if state == "finished" else None,
                    "details": {"g1": {"requests": [{"file": {"name": "Sao kê-20261120.pdf", "saved": True}, "view": "NGUYEN VAN AN"}]}}}
        if path == "/api/run/stop":
            return {"stopped": True}
        raise AssertionError(path)


def call(tools, name, args=None):
    reply = server.handle(tools, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}})
    return reply["result"]


def test_five_tools_each_with_a_vietnamese_description_and_a_schema_and_none_to_approve():
    tools = server.handle(server.Tools(Page()), {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    assert [t["name"] for t in tools] == ["list_flows", "plan_from_sentence", "start_run", "get_run_status", "stop_run"]
    assert all(t["description"] and t["inputSchema"]["type"] == "object" for t in tools)
    assert not any("decide" in json.dumps(t) or "duyet" in t["name"] for t in tools)


def test_only_approved_flows_are_listed_and_no_value_goes_out():
    page = Page()
    tools = server.Tools(page)
    flows = call(tools, "list_flows")["structuredContent"]["flows"]
    assert [f["title"] for f in flows] == ["Sao kê"] and flows[0]["inputs"] == [{"name": "so_tai_khoan", "label": "Số tài khoản"}]
    plan = call(tools, "plan_from_sentence", {"text": "xuất sao kê tài khoản 0123456789"})["structuredContent"]
    assert plan["inputs"] == [{"name": "so_tai_khoan", "label": "Số tài khoản", "filled": True}]
    status = call(tools, "get_run_status")
    text = json.dumps(status, ensure_ascii=False)
    assert "0123456789" not in json.dumps(plan) and "0123456789" not in text and "NGUYEN" not in text
    assert all("0123456789" not in json.dumps(a) for a in page.audit) and page.audit[1]["input_names"] == ["so_tai_khoan"]


def test_the_same_key_never_runs_twice():
    page = Page(run_states=("finished",))
    tools = server.Tools(page)
    first = call(tools, "start_run", {"plan_id": "p1", "idempotency_key": "codie-0001"})["structuredContent"]
    again = call(tools, "start_run", {"plan_id": "p1", "idempotency_key": "codie-0001"})["structuredContent"]
    assert first["started"] and again["repeated"] is True
    assert [c for c in page.calls if c[1] == "/api/assistant/run"] == [("POST", "/api/assistant/run", {"plan_id": "p1", "window": "ie-tab:7"})]


def test_a_step_that_writes_waits_for_a_person_and_the_tool_says_so():
    tools = server.Tools(Page(run_states=("waiting_approval",)))
    status = call(tools, "get_run_status")["structuredContent"]
    assert status["state"] == "waiting_for_human" and status["waiting_for"]["risk"] == "write" and "NGUYEN" not in json.dumps(status)


def test_a_run_past_its_total_time_is_stopped_and_the_audit_says_timeout():
    page = Page(run_states=("waiting_approval",))
    tools = server.Tools(page, run_timeout=0.3)
    call(tools, "start_run", {"plan_id": "p1", "idempotency_key": "codie-0002"})
    tools.watch.join(5)
    assert ("POST", "/api/run/stop", {}) in page.calls
    assert any(a["status"] == "timeout" for a in page.audit)


def test_a_checker_only_looks():
    tools = server.Tools(Page(), role="checker")
    assert call(tools, "start_run", {"plan_id": "p1", "idempotency_key": "codie-0003"})["isError"] is True
    assert call(tools, "get_run_status")["isError"] is False


def test_the_page_closed_is_said_plainly_and_nothing_hangs():
    def closed(*_a, **_k):
        raise server.PageClosed(server.NOT_OPEN)

    result = call(server.Tools(closed), "list_flows")
    assert result["isError"] and "Trang quản lý chưa mở" in result["structuredContent"]["error"]


def test_over_http_a_token_and_an_allowed_address_are_needed():
    token = "t" * 32
    http = server.make_http(server.Tools(Page()), 0, token, {"127.0.0.1"}, host="127.0.0.1")
    threading.Thread(target=http.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{http.server_address[1]}/mcp"
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()

    def post(headers):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=body, method="POST", headers=headers), timeout=5) as reply:
                return reply.status, json.loads(reply.read())
        except urllib.error.HTTPError as error:
            return error.code, None

    assert post({"Content-Type": "application/json"})[0] == 401
    status, reply = post({"Content-Type": "application/json", "Authorization": "Bearer " + token})
    assert status == 200 and len(reply["result"]["tools"]) == 5
    http.shutdown()
    with pytest.raises(SystemExit):
        server.make_http(server.Tools(Page()), 0, "short", {"127.0.0.1"})


def test_the_audit_route_of_the_page_keeps_names_only(tmp_path):
    from test_webui import make_core

    core, _ = make_core(tmp_path)
    core.dispatch("POST", "/api/mcp/audit", {"tool": "start_run", "status": "ok", "title": "Sao kê", "input_names": ["so_tai_khoan", "0123456789", "Bad Name"],
                                             "idempotency_key": "codie-0001", "value": "0123456789"})
    line = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert line["mode"] == "mcp" and line["input_names"] == ["so_tai_khoan"] and "0123456789" not in json.dumps(line)
