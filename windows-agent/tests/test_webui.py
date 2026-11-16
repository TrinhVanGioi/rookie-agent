import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from rookie_agent import diagnose
from rookie_agent.diagnose import JavaInstall, JavaUser
from rookie_agent.selectors import Element, Step
from rookie_agent.server_client import ServerError
from rookie_agent.webui.core import Core, slug, summarize_events
from rookie_agent.webui.server import make_handler


class FakeSession:
    def __init__(self, titles=("Mock TPSS",)):
        self.titles = list(titles)
        self.recorder = None

    def windows(self):
        return [(i, t) for i, t in enumerate(self.titles, start=1)]

    def wait_for_window(self, title_part="", timeout=20.0):
        for hwnd, title in self.windows():
            if title_part in title:
                return hwnd, title
        raise RuntimeError("none")

    def attach(self, recorder):
        self.recorder = recorder

    def detach(self):
        recorder, self.recorder = self.recorder, None
        return recorder

    def call(self, task):
        class Bridge:
            dll_path = "C:/x/WindowsAccessBridge-32.dll"

        return task(Bridge())


class FakeServer:
    def __init__(self, url):
        self.url = url
        self.sessions = []

    def health(self):
        if "bad" in self.url:
            raise ServerError(f"Không kết nối được máy chủ {self.url}")
        return {"ok": True}

    def post_session(self, session_id, engine, events):
        self.sessions.append(session_id)

    def learn(self, workflow_id, session_ids, title=None):
        return {
            "workflow": {"title": title, "inputs": [{"name": "so_tai_khoan"}], "steps": [
                {"action": "fill", "risk": "read", "mode": "auto", "target": {"label": "Số tài khoản"}},
                {"action": "click", "risk": "read", "mode": "auto", "target": {"label": "Tra cứu"}},
            ]},
            "warnings": [],
        }


def make_core(tmp_path, session=None, **overrides):
    session = session or FakeSession()
    parts = dict(
        home=tmp_path, open_session=lambda: session, own_bits=32, dll_info=lambda: ("dll", None),
        installs=lambda: [JavaInstall(tmp_path, "jre1.8.0_91", 32, None)],
        users=lambda: [JavaUser(1, "iexplore.exe", 32)], switched_on=lambda: True, server_client=FakeServer,
    )
    parts.update(overrides)
    return Core(**parts), session


def record_one(core, session, number="0123456789"):
    assert core.dispatch("POST", "/api/record/start", {"window": "Mock"})[0] == 200
    element = Element("text", "Số tài khoản", (Step("frame", 0), Step("text", 0)), "Mock TPSS")
    session.recorder.text_changed(element, number, True)
    session.recorder.focus_lost(element)
    session.recorder.clicked(Element("push button", "Tra cứu", (Step("frame", 0), Step("push button", 1)), "Mock TPSS"))
    return core.dispatch("POST", "/api/record/stop", {"name": "lần 1"})


def test_check_reports_the_state_of_the_pc(tmp_path):
    core, _ = make_core(tmp_path)
    status, report = core.dispatch("GET", "/api/check", {})
    assert status == 200 and report["summary"] == "ok" and report["wanted_bits"] == 32


def test_check_says_when_the_agent_is_the_wrong_bitness(tmp_path):
    core, _ = make_core(tmp_path, own_bits=64)
    _, report = core.dispatch("GET", "/api/check", {})
    assert report["summary"] == "bad" and report["wanted_bits"] == 32


def test_recording_never_keeps_the_typed_account_number(tmp_path):
    core, session = make_core(tmp_path)
    status, reply = record_one(core, session, "0123456789")
    assert status == 200 and reply["events"] >= 2
    files = list((tmp_path / "sessions").glob("*.json"))
    assert len(files) == 1
    assert "0123456789" not in files[0].read_text(encoding="utf-8")
    assert reply["typed_values_kept"] == 0
    assert any("Số tài khoản" in step for step in reply["steps"])


def test_record_start_without_a_java_window_explains(tmp_path):
    core, _ = make_core(tmp_path, session=FakeSession(titles=()))
    status, reply = core.dispatch("POST", "/api/record/start", {})
    assert status == 400 and "Không thấy cửa sổ Java" in reply["error"]


def test_record_start_without_the_bridge_explains(tmp_path):
    def broken():
        raise RuntimeError("Không tìm thấy WindowsAccessBridge-32.dll")

    core, _ = make_core(tmp_path, open_session=broken)
    status, reply = core.dispatch("POST", "/api/record/start", {})
    assert status == 400 and "WindowsAccessBridge" in reply["error"]


def test_learning_needs_two_recordings_and_a_name(tmp_path):
    core, session = make_core(tmp_path)
    record_one(core, session)
    assert core.dispatch("POST", "/api/learn", {"ids": ["only-one"], "title": "x"})[0] == 400
    ids = [core.store.listing()[0]["id"]] * 2
    assert core.dispatch("POST", "/api/learn", {"ids": ids, "title": ""})[0] == 400


def test_learning_uploads_then_shows_steps_in_plain_words(tmp_path):
    core, session = make_core(tmp_path)
    record_one(core, session)
    first = core.store.listing()[0]["id"]
    record_one(core, session)
    ids = [row["id"] for row in core.store.listing()]
    status, reply = core.dispatch("POST", "/api/learn", {"ids": ids, "title": "Vấn tin tài khoản"})
    assert status == 200
    assert reply["steps"][0]["text"] == "Nhập vào «Số tài khoản»"
    assert reply["steps"][0]["risk"] == "chỉ xem"
    assert core.store.load(first)["uploaded"] is True


def test_server_check_reports_a_server_that_is_down(tmp_path):
    core, _ = make_core(tmp_path)
    status, reply = core.dispatch("POST", "/api/server/check", {"url": "http://bad:1"})
    assert status == 200 and reply["ok"] is False and "Không kết nối" in reply["message"]
    assert core.dispatch("POST", "/api/server/check", {"url": "ftp://x"})[0] == 400


def test_enable_bridge_without_jabswitch_explains(tmp_path):
    core, _ = make_core(tmp_path)
    status, reply = core.dispatch("POST", "/api/enable-bridge", {})
    assert status == 400 and "jabswitch" in reply["error"]


def test_switch_bits_calls_the_relauncher_only_when_needed(tmp_path):
    asked = []
    core, _ = make_core(tmp_path, own_bits=64, relauncher=asked.append)
    assert core.dispatch("POST", "/api/switch-bits", {})[1] == {"switched": True, "bits": 32}
    assert asked == [32]
    same, _ = make_core(tmp_path, own_bits=32, relauncher=asked.append)
    assert same.dispatch("POST", "/api/switch-bits", {})[1] == {"switched": False}


def test_diagnostics_file_holds_no_typed_values(tmp_path):
    core, session = make_core(tmp_path)
    record_one(core, session, "0123456789")
    status, reply = core.dispatch("POST", "/api/diagnostics", {})
    assert status == 200
    text = open(reply["path"], encoding="utf-8").read()
    assert "0123456789" not in text and json.loads(text)["check"]["summary"] == "ok"


def test_unknown_route_and_unexpected_error(tmp_path):
    core, _ = make_core(tmp_path)
    assert core.dispatch("GET", "/api/nothing", {})[0] == 404
    core.store.put = lambda *a: (_ for _ in ()).throw(OSError("disk"))
    assert core.dispatch("POST", "/api/server/check", {"url": "http://x"})[0] == 500


def test_slug_and_summary_helpers():
    assert slug("Vấn tin tài khoản") == "van-tin-tai-khoan"
    assert summarize_events([{"type": "click", "target": {"label": "OK"}}])["steps"] == ["Bấm «OK»"]


# ---- HTTP: only this PC's own page may call the agent ---------------------------------------------


@pytest.fixture
def http(tmp_path):
    core, _ = make_core(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), lambda *a: None)
    port = server.server_address[1]
    server.RequestHandlerClass = make_handler(core, port, lambda: None)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()
    server.server_close()


def call(port, path, method="GET", headers=None, body=b""):
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body or None, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=5) as reply:
            return reply.status, reply.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_page_and_state_are_served(http):
    status, page = call(http, "/")
    assert status == 200 and "Rookie Agent" in page.decode("utf-8")
    status, body = call(http, "/api/state")
    assert status == 200 and json.loads(body)["bits"] == 32


def test_another_host_name_is_refused(http):
    status, _ = call(http, "/api/state", headers={"Host": "evil.example"})
    assert status == 403


def test_post_needs_our_header_and_our_origin(http):
    assert call(http, "/api/recordings/delete", "POST", body=b"{}")[0] == 403
    assert call(http, "/api/recordings/delete", "POST", {"X-Rookie": "1", "Origin": "http://evil.example"}, b"{}")[0] == 403
    ok = {"X-Rookie": "1", "Origin": f"http://localhost:{http}", "Content-Type": "application/json"}
    assert call(http, "/api/recordings/delete", "POST", ok, b'{"id":"x"}')[0] == 200


def test_an_empty_recording_is_not_saved(tmp_path):
    core, _ = make_core(tmp_path)
    core.dispatch("POST", "/api/record/start", {"window": "Mock"})
    status, reply = core.dispatch("POST", "/api/record/stop", {})
    assert status == 400 and "Chưa ghi được" in reply["error"]
    assert core.store.listing() == []


def test_the_icon_that_hands_over_to_another_bitness_still_opens_the_browser(monkeypatch, tmp_path):
    """Clicking the desktop icon on a PC with 32-bit Java: the 32-bit copy must open the page, not start silently."""
    import subprocess

    from rookie_agent.webui import server

    commands = []
    monkeypatch.setattr(subprocess, "Popen", lambda command, **kw: commands.append(command))
    monkeypatch.setattr(server, "runtime_python", lambda bits: tmp_path / f"py{bits}.exe")
    server.relaunch(32, 8765, start_server=False, open_browser=True)
    server.relaunch(32, 8765, start_server=True, open_browser=False)
    assert "--no-browser" not in commands[0]
    assert "--no-browser" in commands[1]


def test_a_learned_flow_is_kept_and_listed_for_the_flow_tab(tmp_path):
    core, session = make_core(tmp_path)
    assert core.dispatch("GET", "/api/flows", {}) == (200, {"flows": []})
    record_one(core, session)
    record_one(core, session)
    ids = [row["id"] for row in core.store.listing()]
    core.dispatch("POST", "/api/learn", {"ids": ids, "title": "Vấn tin tài khoản"})
    status, reply = core.dispatch("GET", "/api/flows", {})
    assert status == 200 and len(reply["flows"]) == 1
    flow = reply["flows"][0]
    assert flow["title"] == "Vấn tin tài khoản"
    assert flow["steps"][0]["text"] == "Nhập vào «Số tài khoản»"
    assert flow["steps"][0]["risk_key"] == "read" and flow["steps"][0]["mode_key"] in ("auto", "review", "approve")
    # learning the same title again replaces the flow instead of piling up copies
    core.dispatch("POST", "/api/learn", {"ids": ids, "title": "Vấn tin tài khoản"})
    assert len(core.dispatch("GET", "/api/flows", {})[1]["flows"]) == 1
