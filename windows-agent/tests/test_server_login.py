"""Task 10.1, the agent's side: log in to the server once, keep only the token, send it with every call."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from rookie_agent import server_client
from rookie_agent.server_client import ServerClient, ServerError


def make_core(*a, **k):
    from test_webui import make_core as real    # sibling module (tests/ has no package: the server has one named `tests`)
    return real(*a, **k)


class Handler(BaseHTTPRequestHandler):
    seen: list[tuple[str, str, str | None]] = []

    def log_message(self, *_):
        pass

    def _reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        Handler.seen.append(("GET", self.path, self.headers.get("Authorization")))
        if self.path == "/health":
            return self._reply(200, {"status": "ok"})
        if self.headers.get("Authorization") != "Bearer tok-123":
            return self._reply(401, {"detail": "Chưa đăng nhập hoặc phiên đăng nhập đã hết hạn. Đăng nhập lại."})
        return self._reply(200, {"workflows": []})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        Handler.seen.append(("POST", self.path, self.headers.get("Authorization")))
        if self.path == "/auth/login":
            if body == {"username": "gdv1", "password": "bi-mat", "client": "agent"}:
                return self._reply(200, {"user": {"name": "gdv1", "display": "GDV Một", "unit": "CN Hà Nội", "roles": ["maker"]},
                                         "token": "tok-123", "expires_at": 1})
            return self._reply(401, {"detail": "Sai tên đăng nhập hoặc mật khẩu."})
        if self.path == "/auth/logout":
            return self._reply(200, {"ok": True})
        if self.path == "/auth/handoff":
            return self._reply(200, {"code": "one-time"} if self.headers.get("Authorization") == "Bearer tok-123" else {"code": None})
        return self._reply(404, {"detail": "?"})


@pytest.fixture
def server():
    Handler.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_the_client_sends_the_token_and_the_exchange_log_never_shows_the_password_or_the_token(server):
    client = ServerClient(server)
    reply = client.login("gdv1", "bi-mat")
    assert reply["token"] == "tok-123"
    client.token = reply["token"]
    assert client._call("GET", "/workflows") == {"workflows": []}
    assert Handler.seen[-1] == ("GET", "/workflows", "Bearer tok-123")
    shown = json.dumps(server_client.exchanges(), ensure_ascii=False)
    assert "bi-mat" not in shown and "tok-123" not in shown


def test_the_page_logs_in_keeps_the_token_not_the_password_and_learning_sends_it(tmp_path, server):
    core, _ = make_core(tmp_path, server_client=ServerClient)
    core.store.put("server_url", server)
    status, reply = core.dispatch("POST", "/api/server/login", {"username": "gdv1", "password": "bi-mat"})
    assert status == 200 and reply["user"]["display"] == "GDV Một"
    settings = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert "bi-mat" not in settings and "tok-123" in settings
    assert core.dispatch("GET", "/api/state", {})[1]["server_user"] == "GDV Một"
    core._server()._call("GET", "/workflows")
    assert Handler.seen[-1][2] == "Bearer tok-123"

    status, _ = core.dispatch("POST", "/api/server/logout", {})
    assert status == 200 and "tok-123" not in (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert core.dispatch("GET", "/api/state", {})[1]["server_user"] is None


def test_a_wrong_password_is_said_in_vietnamese_and_nothing_is_kept(tmp_path, server):
    core, _ = make_core(tmp_path, server_client=ServerClient)
    core.store.put("server_url", server)
    status, reply = core.dispatch("POST", "/api/server/login", {"username": "gdv1", "password": "sai"})
    assert status == 400 and "Sai tên đăng nhập hoặc mật khẩu" in reply["error"]
    assert core.store.get("server_token") is None


def test_the_admin_page_opens_on_the_flow_signed_in_with_a_one_time_code(tmp_path, server):
    core, _ = make_core(tmp_path, server_client=ServerClient)
    core.store.put("server_url", server)
    status, reply = core.dispatch("POST", "/api/admin/open", {"workflow_id": "sao-ke"})
    assert status == 200 and reply["url"] == server + "/admin/?flow=sao-ke"                 # not signed in: no code
    core.dispatch("POST", "/api/server/login", {"username": "gdv1", "password": "bi-mat"})
    reply = core.dispatch("POST", "/api/admin/open", {"workflow_id": "sao-ke"})[1]
    assert reply["url"] == server + "/admin/?flow=sao-ke&code=one-time"
    assert core.dispatch("POST", "/api/admin/open", {"workflow_id": "../x"})[1]["url"] == server + "/admin/?code=one-time"


def test_a_server_that_asks_for_a_login_says_so(server):
    with pytest.raises(ServerError, match="Đăng nhập lại"):
        ServerClient(server)._call("GET", "/workflows")
