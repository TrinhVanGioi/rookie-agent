import json
import time
from pathlib import Path
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

    def learn(self, workflow_id, session_ids, title=None, traces=None):
        FakeServer.last_traces = traces
        extra = getattr(FakeServer, "extra", {})
        return {**extra, 
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


def test_learning_starts_the_bundled_server_when_it_is_not_running(tmp_path):
    started = []
    core, session = make_core(tmp_path, server_starter=lambda: started.append(1) or "http://localhost:8000")
    record_one(core, session)
    ids = [core.store.listing()[0]["id"]]
    assert core.dispatch("POST", "/api/learn", {"ids": ids, "title": "Vấn tin"})[0] == 200 and started
    def broken():
        raise RuntimeError("Máy chủ không bật được. Xem server.log")
    core._server_starter = broken
    status, reply = core.dispatch("POST", "/api/learn", {"ids": ids, "title": "Vấn tin"})
    assert status == 400 and "server.log" in reply["error"]


def test_learning_needs_a_recording_and_a_name(tmp_path):
    core, session = make_core(tmp_path)
    record_one(core, session)
    assert core.dispatch("POST", "/api/learn", {"ids": [], "title": "x"})[0] == 400
    ids = [core.store.listing()[0]["id"]]
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
    assert len(flow["step_ids"]) == len(flow["steps"])                       # the canvas lights a node by the id of the step running
    # learning the same title again replaces the flow instead of piling up copies
    core.dispatch("POST", "/api/learn", {"ids": ids, "title": "Vấn tin tài khoản"})
    assert len(core.dispatch("GET", "/api/flows", {})[1]["flows"]) == 1


# ---- web pages in Internet Explorer ----------------------------------------------------------------------------

class FakeIeBridge:
    def __init__(self, tabs=({"id": 1, "title": "TouchPoint"},), after_stop=()):
        self._tabs, self.after_stop, self.started = list(tabs), list(after_stop), None

    def tabs(self):
        return list(self._tabs)

    def probe(self, tab_id):
        return {"frames": [{"name": "main", "mode": 5, "inputs": 3}] * 5, "inputs": 40, "buttons": 6, "objects": 0}

    attached = 5

    def start_recording(self, tab_id, requests=False):
        self.started = tab_id
        self.hooked = requests
        return {"frames": 5, "attached": self.attached}

    def poll(self):
        return []

    def stop_recording(self):
        return list(self.after_stop)


def ie_line(kind, t, **fields):
    base = {"t": t, "kind": kind, "frame": "desktopFrame/main", "title": "Main", "tag": "button", "type": "button", "id": "b", "name": "", "label": "XEM", "pos": 0, "value": None}
    base.update(fields)
    return base


def ie_core(tmp_path, bridge=None, **overrides):
    bridge = bridge or FakeIeBridge()
    core, _ = make_core(tmp_path, ie_bridge=lambda: bridge, **overrides)
    return core, bridge


def test_ie_tabs_are_offered_next_to_java_windows(tmp_path):
    core, _ = ie_core(tmp_path)
    assert "Internet Explorer: TouchPoint" in core.dispatch("GET", "/api/windows", {})[1]["windows"]


def test_recording_an_ie_tab_saves_a_session_with_engine_ie_and_no_secret(tmp_path):
    lines = [ie_line("input", 1000, tag="input", type="text", id="txtCustomerId", label="Mã khách hàng", value="0123456789"),
             ie_line("input", 1100, tag="input", type="password", id="pw", label="Mật khẩu", value="TOPSECRET"),
             ie_line("click", 2000)]
    core, bridge = ie_core(tmp_path, FakeIeBridge(after_stop=lines))
    assert core.dispatch("POST", "/api/record/start", {"window": "Internet Explorer: TouchPoint"})[0] == 200
    assert bridge.started == 1
    assert core.dispatch("GET", "/api/state", {})[1]["recording"] is True
    status, reply = core.dispatch("POST", "/api/record/stop", {"name": "vấn tin lần 1"})
    assert status == 200 and reply["steps"] == ["Nhập vào «Mã khách hàng»", "Bấm «XEM»"] and reply["typed_values_kept"] == 0
    document = core.store.load(reply["id"])
    assert document["engine"] == "ie" and all(e["engine"] == "ie" for e in document["events"])
    assert "0123456789" not in json.dumps(document) and "TOPSECRET" not in json.dumps(document)
    assert core.dispatch("GET", "/api/state", {})[1]["recording"] is False


def test_an_ie_recording_with_nothing_done_is_refused_like_any_other(tmp_path):
    core, _ = ie_core(tmp_path)
    core.dispatch("POST", "/api/record/start", {"window": "Internet Explorer: TouchPoint"})
    assert core.dispatch("POST", "/api/record/stop", {})[0] == 400


def test_a_tab_that_is_gone_is_explained_in_plain_words(tmp_path):
    core, _ = ie_core(tmp_path, FakeIeBridge(tabs=()))
    status, reply = core.dispatch("POST", "/api/record/start", {"window": "Internet Explorer: TouchPoint"})
    assert status == 400 and "Internet Explorer" in reply["error"]


def test_the_machine_check_reports_the_ie_page_and_drops_java_noise(tmp_path):
    core, _ = make_core(tmp_path, session=FakeSession(titles=()), ie_bridge=lambda: FakeIeBridge(), installs=lambda: [], users=lambda: [], switched_on=lambda: True)
    status, report = core.dispatch("GET", "/api/check", {})
    assert status == 200 and report["summary"] == "ok"
    assert report["items"][0]["title"].startswith("Đọc được trang trong Internet Explorer") and "5 khung" in report["items"][0]["detail"]
    assert all("Java" not in entry["title"] for entry in report["items"])


def test_a_recorded_ie_session_is_sent_to_the_server_as_engine_ie(tmp_path):
    sent = []

    class Server(FakeServer):
        def post_session(self, session_id, engine, events, **extra):
            sent.append(engine)

    core, _ = ie_core(tmp_path, FakeIeBridge(after_stop=[ie_line("click", 2000)]), server_client=Server)
    for _ in range(2):
        core.dispatch("POST", "/api/record/start", {"window": "Internet Explorer: TouchPoint"})
        core.dispatch("POST", "/api/record/stop", {})
    ids = [row["id"] for row in core.store.listing()]
    assert core.dispatch("POST", "/api/learn", {"ids": ids, "title": "Xem"})[0] == 200
    assert sent == ["ie", "ie"]


def test_a_page_the_recorder_could_not_get_into_is_explained_not_silently_empty(tmp_path):
    bridge = FakeIeBridge()
    bridge.attached = 0
    core, _ = ie_core(tmp_path, bridge)
    status, reply = core.dispatch("POST", "/api/record/start", {"window": "Internet Explorer: TouchPoint"})
    assert status == 400 and "Không gắn được bộ ghi" in reply["error"]
    assert core.dispatch("GET", "/api/state", {})[1]["recording"] is False


def test_stopping_a_recording_that_caught_nothing_says_how_many_frames_listened_and_leaves_no_recording(tmp_path):
    core, _ = ie_core(tmp_path)
    core.dispatch("POST", "/api/record/start", {"window": "Internet Explorer: TouchPoint"})
    status, reply = core.dispatch("POST", "/api/record/stop", {})
    assert status == 400 and "5/5 khung" in reply["error"]
    # the page must be able to show "Bắt đầu ghi" again: the agent is no longer recording
    assert core.dispatch("GET", "/api/state", {})[1]["recording"] is False
    # and a second Stop does not pretend to know about a recording
    assert core.dispatch("POST", "/api/record/stop", {})[0] == 400


# ---- the "Kết nối" tab: connection to Codie and the log of calls -----------------------------

def test_codie_status_says_plainly_when_the_command_is_missing(tmp_path):
    core, _ = make_core(tmp_path)
    _, status = core.dispatch("GET", "/api/codie", {})
    assert status["mode"] == "rookie-design"
    if status["found"] is None:
        assert "Chưa thấy lệnh" in status["message"]


def test_a_failed_codie_test_is_told_in_plain_words_and_logged_without_content(tmp_path):
    core, _ = make_core(tmp_path)
    code, reply = core.dispatch("POST", "/api/codie/test", {"command": "no-such-codie-command-xyz", "mode": "rookie-design"})
    assert code == 200 and reply["ok"] is False and "no-such-codie-command-xyz" in reply["message"]
    _, listing = core.dispatch("GET", "/api/calls", {})
    [entry] = listing["calls"]
    assert entry["target"] == "codie" and entry["mode"] == "rookie-design" and entry["ok"] is False
    assert "Thử kết nối" in entry["note"]
    # what was typed in the tab is remembered for the next time
    assert core.dispatch("GET", "/api/codie", {})[1]["command"] == "no-such-codie-command-xyz"


def test_a_codie_test_that_works_is_logged_as_ok(tmp_path, monkeypatch):
    from rookie_agent import codie

    monkeypatch.setattr(codie, "call", lambda *a, **k: codie.CodieRun(True, 0, 2.5, result={"pong": True}))
    core, _ = make_core(tmp_path)
    _, reply = core.dispatch("POST", "/api/codie/test", {"command": "codie", "mode": "rookie-design"})
    assert reply["ok"] is True and "2.5 giây" in reply["message"]
    assert core.dispatch("GET", "/api/calls", {})[1]["calls"][0]["ok"] is True


def test_a_working_marker_without_the_pong_is_not_a_connection(tmp_path, monkeypatch):
    from rookie_agent import codie

    monkeypatch.setattr(codie, "call", lambda *a, **k: codie.CodieRun(True, 0, 1.0, result={"other": 1}))
    core, _ = make_core(tmp_path)
    _, reply = core.dispatch("POST", "/api/codie/test", {})
    assert reply["ok"] is False


def test_inspecting_a_screen_says_what_the_page_holds_and_which_frame_cannot_be_read(tmp_path):
    core, bridge = ie_core(tmp_path)
    title = "Internet Explorer: " + bridge.tabs()[0]["title"]
    bridge.probe = lambda tab_id: {
        "frames": [{"name": "main", "mode": 5, "inputs": 2, "counts": {"select": 3, "input": 2, "button": 1}, "controls": []}],
        "inputs": 2, "buttons": 1, "objects": 0, "unreadable": ["frame 'role' not readable: Access is denied"]}
    code, reply = core.dispatch("POST", "/api/ie/inspect", {"window": title})
    assert code == 200
    text = "\n".join(reply["summary"])
    assert "3 ô chọn" in text and "KHÔNG đọc được" in text and "khác tên miền" in text
    assert Path(reply["path"]).is_file()


def test_inspecting_a_plugin_screen_without_html_fields_says_so(tmp_path):
    core, bridge = ie_core(tmp_path)
    bridge.probe = lambda tab_id: {"frames": [{"name": "m", "counts": {"object": 1}}], "inputs": 0, "buttons": 0, "objects": 1, "unreadable": []}
    _, reply = core.dispatch("POST", "/api/ie/inspect", {"window": "Internet Explorer: " + bridge.tabs()[0]["title"]})
    assert "plugin" in "\n".join(reply["summary"])


def test_inspecting_needs_an_ie_page_chosen(tmp_path):
    core, _ = ie_core(tmp_path)
    assert core.dispatch("POST", "/api/ie/inspect", {"window": "Mock"})[0] == 400


def test_inspecting_says_where_the_fields_are_and_whether_they_are_on_screen(tmp_path):
    core, bridge = ie_core(tmp_path)
    bridge.probe = lambda tab_id: {"frames": [
        {"name": "rhidden", "size": "0x0", "counts": {"select": 3}, "controls": [
            {"tag": "select", "id": "currentRole", "visible": False}, {"tag": "button", "id": "btnSelect", "visible": False}]},
        {"name": "rtop", "size": "800x600", "counts": {}, "controls": []}], "unreadable": []}
    _, reply = core.dispatch("POST", "/api/ie/inspect", {"window": "Internet Explorer: " + bridge.tabs()[0]["title"]})
    text = "\n".join(reply["summary"])
    assert "«rhidden» có 2 ô/nút (0 đang hiện trên màn hình, 2 bị ẩn); kích thước khung 0x0" in text and "rtop" not in text


def test_the_last_trace_is_readable_on_screen_with_a_count_per_frame(tmp_path):
    core, _ = make_core(tmp_path)
    assert core.dispatch("GET", "/api/trace/last", {})[0] == 400  # nothing recorded yet
    trace = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "examples" / "valid" / "trace-ie-login.json").read_text(encoding="utf-8"))
    (tmp_path / "traces").mkdir()
    (tmp_path / "traces" / "s-1.trace.json").write_text(json.dumps(trace), encoding="utf-8")
    code, reply = core.dispatch("GET", "/api/trace/last", {})
    text = "\n".join(reply["lines"])
    assert code == 200 and "Số hành động theo khung: -: 2, main: 4, top: 4" in text
    assert "click" in text and "Vai tro" in text and "(enter)" in text and "[user_id]" in text
    assert "TOPSECRET" not in text
    (tmp_path / "traces" / "s-1.reach.txt").write_text("10:00:01 window 1 frame='rhidden' host=x ready=complete mode=5 listen=attachEvent | window 1 frame='' host=x ready=complete mode=5 listen=none inject_error=Access is denied", encoding="utf-8")
    text = chr(10).join(core.dispatch("GET", "/api/trace/last", {})[1]["lines"])
    assert "Bộ ghi đã gắn vào các khung" in text and "frame='rhidden' host=x ready=complete mode=5 listen=attachEvent" in text and "inject_error=Access is denied" in text


# ---- the screen to record follows the page when its title changes (sign in -> home), no refresh needed ----

def test_the_list_gives_each_ie_tab_with_its_id_so_the_choice_survives_a_new_title(tmp_path):
    core, bridge = ie_core(tmp_path)
    _, listing = core.dispatch("GET", "/api/windows", {})
    assert listing["ie"] == [{"id": 1, "title": "TouchPoint"}]
    bridge._tabs = [{"id": 1, "title": "TouchPoint - Home"}]          # the page changed after the sign in
    assert core.dispatch("GET", "/api/windows", {})[1]["ie"] == [{"id": 1, "title": "TouchPoint - Home"}]


def test_recording_starts_on_the_tab_chosen_even_after_its_title_changed(tmp_path):
    core, bridge = ie_core(tmp_path)
    bridge._tabs = [{"id": 1, "title": "TouchPoint - Home"}]
    assert core.dispatch("POST", "/api/record/start", {"window": "ie-tab:1"})[0] == 200
    assert bridge.started == 1


def test_a_stale_title_still_finds_the_only_ie_page_but_never_guesses_among_several(tmp_path):
    core, bridge = ie_core(tmp_path)
    bridge._tabs = [{"id": 1, "title": "TouchPoint - Home"}]
    assert core.dispatch("POST", "/api/record/start", {"window": "Internet Explorer: TouchPoint - Sign in"})[0] == 200
    core.dispatch("POST", "/api/record/stop", {})
    bridge._tabs = [{"id": 1, "title": "TouchPoint - Home"}, {"id": 2, "title": "Other page"}]
    status, reply = core.dispatch("POST", "/api/record/start", {"window": "Internet Explorer: TouchPoint - Sign in"})
    assert status == 400 and "Tải lại" in reply["error"]


def test_a_tab_that_is_gone_says_so_in_plain_words(tmp_path):
    core, bridge = ie_core(tmp_path)
    status, reply = core.dispatch("POST", "/api/record/start", {"window": "ie-tab:9"})
    assert status == 400 and "Không thấy" in reply["error"]


# ---- task 4.31: what the agent saw on the screen, for the teller's eyes only ----

def test_the_panel_shows_what_the_screen_held_after_the_last_action_and_it_is_never_written_to_disk(tmp_path):
    core, bridge = ie_core(tmp_path)
    assert core.dispatch("GET", "/api/seen", {})[1]["last"] is None
    core.dispatch("POST", "/api/record/start", {"window": "ie-tab:1"})
    session = core._ie_session
    session.seen.append({"t": 1, "after": {"kind": "click", "id": "btnFind", "label": "TIM KIEM"}, "summary": "bảng 1 dòng",
                         "region": ["main"], "changed": [{"frame": "main", "kind": "table", "name": "grid"}],
                         "frames": [{"frame": "main", "tables": [{"id": "grid", "headers": ["So TK"], "rows": [["0123456789"]], "row_count": 1}],
                                     "fields": [], "messages": []}]})
    _, shown = core.dispatch("GET", "/api/seen", {})
    assert shown["recording"] is True and shown["last"]["frames"][0]["tables"][0]["rows"] == [["0123456789"]]
    core.dispatch("POST", "/api/record/stop", {})
    assert core.dispatch("GET", "/api/seen", {})[1]["recording"] is False       # still there after the recording, in memory
    on_disk = "".join(p.read_text(encoding="utf-8", errors="ignore") for p in tmp_path.rglob("*") if p.is_file())
    assert "0123456789" not in on_disk


# ---- task 4.35: the requests the page made, full request and response, for the teller's eyes only ----

def test_the_panel_lists_the_requests_with_what_was_sent_and_received_and_none_of_it_is_written_to_disk(tmp_path):
    core, bridge = ie_core(tmp_path)
    assert core.dispatch("GET", "/api/requests", {})[1]["requests"] == []
    core.dispatch("POST", "/api/record/start", {"window": "ie-tab:1"})
    core._ie_session.requests.append({"t": 1, "frame": "main", "method": "POST", "url": "/api/find?acct=0123456789", "status": 200, "ms": 41,
                                      "req": '{"account":"0123456789"}', "res": '{"name":"NGUYEN VAN A"}', "after": {"kind": "click", "label": "TIM KIEM", "id": "btnFind"}})
    _, shown = core.dispatch("GET", "/api/requests", {})
    assert shown["requests"][0]["res"] == '{"name":"NGUYEN VAN A"}' and shown["requests"][0]["status"] == 200
    core.dispatch("POST", "/api/record/stop", {})
    assert len(core.dispatch("GET", "/api/requests", {})[1]["requests"]) == 1           # still there after the recording, in memory
    on_disk = "".join(p.read_text(encoding="utf-8", errors="ignore") for p in tmp_path.rglob("*") if p.is_file())
    for secret in ("0123456789", "NGUYEN"):
        assert secret not in on_disk


# ---- tasks 4.42 to 4.44: running a learned flow from the page, with the card the person decides on ----

class RunBridge(FakeIeBridge):
    """An IE bridge that can be driven: a page with a field, a button, and a screen that can be read."""

    def __init__(self):
        super().__init__(tabs=({"id": 1, "title": "Mock TPSS - Chuyen tien", "host": "localhost"},))
        self.done, self.screen = [], []

    def bind(self, tab_id):
        return {"ok": True}

    def act(self, op, selectors, value=""):
        self.done.append((op, selectors[0], value))
        return {"ok": True, "value": value} if op in ("fill", "read") else {"ok": True}

    def read(self):
        return self.screen


def run_flow_doc(status="approved"):
    return {"schema_version": 2, "engine": "ie", "id": "wf", "version": 1, "status": status,
            "inputs": [{"name": "acct", "type": "string"}],
            "steps": [{"id": "s1", "action": "fill", "value": "{acct}", "target": {"selectors": ["frame=top|id=a"], "label": "So tai khoan"}, "risk": "read", "mode": "auto"},
                      {"id": "s2", "action": "click", "target": {"selectors": ["frame=top|id=send"], "label": "Gui"}, "risk": "money", "mode": "approve"}]}


def run_core(tmp_path, status="approved"):
    bridge = RunBridge()
    core, _ = make_core(tmp_path, ie_bridge=lambda: bridge)
    core.store.put("flows", [{"title": "Chuyen tien", "inputs": ["acct"], "steps": [], "warnings": [], "learned_at": "x", "workflow": run_flow_doc(status)}])
    return core, bridge


def wait_for(core, state, seconds=5):
    import time as _t

    end = _t.monotonic() + seconds
    while _t.monotonic() < end:
        status = core.dispatch("GET", "/api/run/status", {})[1]
        if status["state"] == state:
            return status
        _t.sleep(0.02)
    raise AssertionError(f"never reached {state}: {status['state']}")


def test_a_flow_that_was_not_approved_does_not_run(tmp_path):
    core, bridge = run_core(tmp_path, status="draft")
    status, reply = core.dispatch("POST", "/api/run/start", {"title": "Chuyen tien", "inputs": {"acct": "0123456789"}, "window": "ie-tab:1", "mode": "run"})
    assert status == 400 and "Duyệt agent" in reply["error"] and bridge.done == []


def test_the_person_approves_the_flow_then_runs_it_and_decides_on_the_money_step(tmp_path):
    core, bridge = run_core(tmp_path, status="draft")
    assert core.dispatch("POST", "/api/flow/approve", {"title": "Chuyen tien"})[0] == 200
    assert core.dispatch("POST", "/api/run/start", {"title": "Chuyen tien", "inputs": {"acct": "0123456789"}, "window": "ie-tab:1", "mode": "run"})[0] == 200
    waiting = wait_for(core, "waiting_approval")
    ask = waiting["ask"]
    assert ask["step_id"] == "s2" and ask["risk"] == "money" and ask["label"] == "Gui"
    assert [d[0] for d in bridge.done] == ["fill", "fill"][:1] + [] or bridge.done[0][0] == "fill"       # the field was filled before the question
    assert not any(d[0] == "click" for d in bridge.done)                                                   # the money click waits
    wrong = core.dispatch("POST", "/api/run/decide", {"approve": True, "ask_id": "not-the-question"})
    assert wrong[0] == 400                                                                                 # only the open question can be answered
    assert core.dispatch("POST", "/api/run/decide", {"approve": True, "ask_id": ask["id"]})[0] == 200
    done = wait_for(core, "finished")
    assert any(d[0] == "click" for d in bridge.done) and done["result"]["status"] == "finished"


def test_not_approving_the_money_step_ends_the_run_without_the_click(tmp_path):
    core, bridge = run_core(tmp_path)
    core.dispatch("POST", "/api/run/start", {"title": "Chuyen tien", "inputs": {"acct": "x"}, "window": "ie-tab:1", "mode": "run"})
    ask = wait_for(core, "waiting_approval")["ask"]
    core.dispatch("POST", "/api/run/decide", {"approve": False, "ask_id": ask["id"]})
    end = wait_for(core, "rejected")
    assert not any(d[0] == "click" for d in bridge.done) and end["result"]["status"] == "rejected"


def test_the_emergency_stop_ends_a_run_that_waits_for_an_answer(tmp_path):
    core, bridge = run_core(tmp_path)
    core.dispatch("POST", "/api/run/start", {"title": "Chuyen tien", "inputs": {"acct": "x"}, "window": "ie-tab:1", "mode": "run"})
    wait_for(core, "waiting_approval")
    assert core.dispatch("POST", "/api/run/stop", {})[0] == 200
    wait_for(core, "stopped")
    assert not any(d[0] == "click" for d in bridge.done)


def test_a_trial_stops_before_the_first_step_that_writes_or_moves_money(tmp_path):
    core, bridge = run_core(tmp_path, status="draft")           # a trial needs no approval: it only reads
    core.dispatch("POST", "/api/run/start", {"title": "Chuyen tien", "inputs": {"acct": "x"}, "window": "ie-tab:1", "mode": "dry"})
    end = wait_for(core, "finished")
    assert [d[0] for d in bridge.done] == ["fill"] and "Chạy thử" in end["result"]["message"]


def test_the_card_shows_what_will_be_sent_and_what_is_on_screen_only_on_this_pc(tmp_path):
    core, bridge = run_core(tmp_path)
    bridge.screen = ['{"frame": "main", "title": "T", "tables": [{"id": "g", "headers": ["A"], "rows": [["1"]], "row_count": 1}], "fields": [], "messages": []}']
    flow = core.store.get("flows")[0]
    flow["workflow"]["steps"][1] = {"id": "s2", "action": "fill", "value": "{acct}", "target": {"selectors": ["frame=top|id=amt"], "label": "So tien"}, "risk": "write", "mode": "approve"}
    core.store.put("flows", [flow])
    core.dispatch("POST", "/api/run/start", {"title": "Chuyen tien", "inputs": {"acct": "0123456789"}, "window": "ie-tab:1", "mode": "run"})
    ask = wait_for(core, "waiting_approval")["ask"]
    assert ask["will_send"] == "0123456789" and "bảng" in ask["seen"]
    core.dispatch("POST", "/api/run/stop", {})
    wait_for(core, "stopped")
    audit = core.dispatch("GET", "/api/run/status", {})[1]["result"]
    assert "0123456789" not in str(audit)


# ---- task 4.45: the log of a run keeps what happened and who decided, never a value ----

def test_a_run_leaves_an_audit_line_with_the_decisions_and_no_value(tmp_path):
    import json as _json

    core, bridge = run_core(tmp_path)
    core.dispatch("POST", "/api/run/start", {"title": "Chuyen tien", "inputs": {"acct": "0123456789"}, "window": "ie-tab:1", "mode": "run"})
    ask = wait_for(core, "waiting_approval")["ask"]
    core.dispatch("POST", "/api/run/decide", {"approve": True, "ask_id": ask["id"]})
    wait_for(core, "finished")
    import time as _t

    end = _t.monotonic() + 3
    path = tmp_path / "audit.jsonl"
    while _t.monotonic() < end and not path.exists():
        _t.sleep(0.02)
    lines = [_json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1 and lines[0]["title"] == "Chuyen tien" and lines[0]["status"] == "finished" and lines[0]["mode"] == "run"
    assert lines[0]["decisions"] == [{"step_id": "s2", "kind": "approve", "risk": "money", "approved": True}]
    assert [s["id"] for s in lines[0]["steps"]] == ["s1", "s2"]
    assert "0123456789" not in path.read_text(encoding="utf-8")


# ---- a preview: the panel follows what the teller does, and nothing is kept ----

def test_a_preview_shows_the_steps_so_far_and_keeps_nothing_when_it_stops(tmp_path):
    core, bridge = ie_core(tmp_path)
    assert core.dispatch("POST", "/api/record/start", {"window": "ie-tab:1", "preview": True})[0] == 200
    assert core.dispatch("GET", "/api/state", {})[1]["preview"] is True
    session = core._ie_session
    session._take([ie_line("click", 1000, id="btnFind", label="TIM KIEM"), ie_line("click", 5000, id="btnOk", label="OK")])
    live = core.dispatch("GET", "/api/live", {})[1]
    assert live["recording"] and live["preview"] and live["count"] == 2 and len(live["steps"]) == 2
    again = core.dispatch("GET", "/api/live", {})[1]                  # looking does not use anything up: the same answer again
    assert again["steps"] == live["steps"]
    status, reply = core.dispatch("POST", "/api/record/stop", {"name": "khong luu"})
    assert status == 200 and reply["preview"] is True and reply["events"] == 2
    assert core.dispatch("GET", "/api/recordings", {})[1]["recordings"] == []         # no recording was saved
    assert not (tmp_path / "traces").exists() or not list((tmp_path / "traces").iterdir())   # and no trace file
    assert core.dispatch("GET", "/api/state", {})[1]["preview"] is False


def test_a_real_recording_is_unchanged_by_the_preview_option(tmp_path):
    core, bridge = ie_core(tmp_path, bridge=FakeIeBridge(after_stop=[ie_line("click", 1000, id="b", label="XEM")]))
    core.dispatch("POST", "/api/record/start", {"window": "ie-tab:1"})
    assert core.dispatch("GET", "/api/live", {})[1]["preview"] is False
    status, reply = core.dispatch("POST", "/api/record/stop", {"name": "that"})
    assert status == 200 and "preview" not in reply and len(core.dispatch("GET", "/api/recordings", {})[1]["recordings"]) == 1


# ---- the screen as data, for the panel and for the steps that call it ----

def test_the_panel_lists_the_screen_as_an_object_key_values_and_rows_with_the_name_to_call_each_by(tmp_path):
    core, bridge = ie_core(tmp_path)
    assert core.dispatch("GET", "/api/screen", {})[1]["list"] == []
    core.dispatch("POST", "/api/record/start", {"window": "ie-tab:1", "preview": True})
    core._ie_session.seen.append({"t": 1, "after": None, "summary": "", "region": [], "changed": [], "frames": [
        {"frame": "main", "title": "T", "fields": [{"label": "Số tài khoản:", "value": "0123456789"}], "messages": [],
         "tables": [{"id": "grid", "headers": ["Số TK", "Loại"], "rows": [["0123456789", "DDA"], ["9876543210", "SAV"]], "row_count": 2}]}]})
    shown = core.dispatch("GET", "/api/screen", {})[1]
    assert shown["model"]["frames"]["main"]["fields"] == {"so_tai_khoan": "0123456789"}
    assert shown["model"]["frames"]["main"]["tables"]["grid"]["rows"][1] == {"so_tk": "9876543210", "loai": "SAV"}
    placeholders = {item["placeholder"] for item in shown["list"]}
    assert "{ten_bien.so_tai_khoan}" in placeholders and "{ten_bien.grid.1.so_tk}" in placeholders
    core.dispatch("POST", "/api/record/stop", {})
    on_disk = "".join(p.read_text(encoding="utf-8", errors="ignore") for p in tmp_path.rglob("*") if p.is_file())
    assert "0123456789" not in on_disk


def test_the_card_resolves_a_value_read_from_the_screen_by_an_earlier_step(tmp_path):
    core, bridge = run_core(tmp_path)
    bridge.screen = ['{"frame": "main", "title": "T", "fields": [{"label": "So tai khoan", "value": "9002"}], "tables": [], "messages": []}']
    flow = core.store.get("flows")[0]
    flow["workflow"]["schema_version"] = 3
    flow["workflow"]["steps"] = [
        {"id": "s1", "action": "read_fields", "save_as": "kq", "risk": "read", "mode": "auto"},
        {"id": "s2", "action": "fill", "value": "{kq.so_tai_khoan}", "target": {"selectors": ["frame=top|id=amt"], "label": "So tien"}, "risk": "write", "mode": "approve"}]
    flow["workflow"]["inputs"] = []
    core.store.put("flows", [flow])
    core.store.put("ie_allow_write_on_real", True)
    core.dispatch("POST", "/api/run/start", {"title": "Chuyen tien", "inputs": {}, "window": "ie-tab:1", "mode": "run"})
    ask = wait_for(core, "waiting_approval")["ask"]
    assert ask["will_send"] == "9002"                              # the card says what will be typed, found from the screen
    core.dispatch("POST", "/api/run/stop", {})
    wait_for(core, "stopped")


# ---- learning with the model: the masked traces of the chosen recordings go with the request ----

def test_the_masked_traces_of_the_recordings_are_sent_with_the_request_and_the_way_it_was_built_is_shown(tmp_path):
    import json as _json

    core, session = make_core(tmp_path)
    ids = [record_one(core, session, number=str(i) * 10) for i in range(2)]
    ids = [r[1]["id"] for r in ids] if isinstance(ids[0], tuple) else [r["id"] for r in ids]
    (tmp_path / "traces").mkdir(exist_ok=True)
    for index, session_id in enumerate(ids):
        (tmp_path / "traces" / f"{session_id}.trace.json").write_text(_json.dumps({"trace": index}), encoding="utf-8")
    FakeServer.extra = {"method": "codie", "questions": ["Bước X đúng không?"], "llm": {"calls": [
        {"time": "10:00:00", "mode": "rookie-design", "ok": True, "seconds": 41.2, "prompt_chars": 1800, "note": "đạt kiểm chứng (lần 1)"},
        {"time": "10:00:50", "mode": "rookie-workflow", "ok": True, "seconds": 20.0, "prompt_chars": 900, "note": "đạt kiểm chứng (lần 1)"}]}}
    try:
        status, shown = core.dispatch("POST", "/api/learn", {"ids": ids, "title": "Vấn tin"})
    finally:
        FakeServer.extra = {}
    assert status == 200 and shown["method"] == "codie" and shown["questions"] == ["Bước X đúng không?"]
    assert FakeServer.last_traces == [{"trace": 0}, {"trace": 1}]                  # what was sent: the masked traces, in the order chosen
    calls = core.dispatch("GET", "/api/calls", {})[1]["calls"]
    assert [c["mode"] for c in calls][:2] == ["rookie-workflow", "rookie-design"] and calls[0]["target"] == "codie"
    assert "lỗi" not in str(calls)


def test_a_recording_without_its_trace_means_the_model_is_not_asked_and_the_old_way_runs(tmp_path):
    core, session = make_core(tmp_path)
    ids = [record_one(core, session, number=str(i) * 10) for i in range(2)]
    ids = [r[1]["id"] for r in ids] if isinstance(ids[0], tuple) else [r["id"] for r in ids]
    status, shown = core.dispatch("POST", "/api/learn", {"ids": ids, "title": "Vấn tin"})
    assert status == 200 and FakeServer.last_traces is None and shown.get("method") in (None, "rule")


def test_assistant_plan_answer_run(tmp_path):
    class Planning(FakeServer):
        def plan_request(self, payload):
            Planning.sent = payload
            return {"schema_version": 1, "method": "rule", "fallback_reason": None, "chain": [],
                    "candidates": [{"ref": "w1", "confidence": 0.9, "slots": {"s1": "so_tai_khoan"}}]}

    core, _ = make_core(tmp_path, server_client=Planning)
    flow = {"title": "Vấn tin", "workflow": {"status": "approved", "engine": "ie", "inputs": [{"name": "so_tai_khoan", "label": "Số tài khoản"}],
                                             "steps": [{"action": "click", "risk": "read", "mode": "auto", "target": {"label": "Tìm"}}]}}
    core.store.put("flows", [flow])
    seen = []
    core.run_start = lambda body, via=None: seen.append((body, via)) or {"started": True}
    status, shown = core.dispatch("POST", "/api/assistant/plan", {"text": "vấn tin 0123456789"})
    assert status == 200 and shown["state"] == "ready" and "0123456789" not in json.dumps(Planning.sent)
    assert core.dispatch("POST", "/api/assistant/run", {"plan_id": shown["plan_id"], "window": "ie-tab:1"})[0] == 200
    assert seen == [({"title": "Vấn tin", "inputs": {"so_tai_khoan": "0123456789"}, "window": "ie-tab:1", "mode": "run"}, "assistant")]
    assert core.dispatch("POST", "/api/assistant/run", {"plan_id": shown["plan_id"]})[0] == 400          # used once
    assert core.dispatch("GET", "/api/assistant/habits", {})[0] == 200


def test_assistant_run_is_audited_without_sentence_or_values(tmp_path):
    core, _ = make_core(tmp_path)
    controller = type("C", (), {"decisions": [], "steps": []})()
    core._audit({"controller": controller, "title": "Vấn tin", "mode": "run", "started": time.time(), "via": "assistant", "input_names": ["so_tai_khoan"]},
                {"status": "finished"})
    line = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert line["via"] == "assistant" and line["input_names"] == ["so_tai_khoan"] and "0123" not in json.dumps(line)


def test_index_has_assistant_tab():
    page = (Path(__file__).resolve().parents[1] / "rookie_agent" / "webui" / "index.html").read_text(encoding="utf-8")
    for needle in ('id="tabAssist"', 'id="asText"', 'id="asAsk"', 'id="asGo"', 'id="asStop"', "Dừng khẩn", "/api/assistant/plan", "/api/assistant/answer",
                   "/api/assistant/run", "/api/assistant/habits", "pollRun({ steps"):
        assert needle in page, needle


def test_lists_that_refresh_by_timer_keep_what_the_person_opened():
    page = (Path(__file__).resolve().parents[1] / "rookie_agent" / "webui" / "index.html").read_text(encoding="utf-8")
    for needle in ("requestNodes", "never rebuilt", "seenSignature", "dataSignature"):
        assert needle in page, needle


def test_window_lists_refresh_by_timer_also_while_recording():
    page = (Path(__file__).resolve().parents[1] / "rookie_agent" / "webui" / "index.html").read_text(encoding="utf-8")
    assert "if (!recording && document.activeElement" not in page            # the sign in changes the title while recording
    assert 'if (document.activeElement !== $("window")) loadWindows();' in page


def test_requests_are_recorded_by_itself_unless_the_site_once_upset_by_it(tmp_path):
    core, bridge = ie_core(tmp_path, FakeIeBridge(tabs=({"id": 1, "title": "TouchPoint", "host": "localhost"},)))
    core.dispatch("POST", "/api/record/start", {"window": "ie-tab:1"})
    assert bridge.hooked is True                                    # automatic: on
    core._ie_session.on_hook_failed("localhost")                    # the recorder stepped back on this site
    core.dispatch("POST", "/api/record/stop", {})
    assert core._hook_blocked() == {"localhost"}
    core.dispatch("POST", "/api/record/start", {"window": "ie-tab:1"})
    assert bridge.hooked is False                                   # the next time this site is recorded without the hook
    core.dispatch("POST", "/api/record/stop", {})
    (tmp_path / "request-hook-blocked-v2.json").write_text('["*"]', encoding="utf-8")
    core.dispatch("POST", "/api/record/start", {"window": "ie-tab:1"})
    assert bridge.hooked is False                                   # "*" switches the hook off for every site
    core.dispatch("POST", "/api/record/stop", {})


def test_a_page_with_no_frame_or_a_refused_recorder_says_why(tmp_path):
    bridge = FakeIeBridge()
    bridge.start_recording = lambda tab_id, requests=False: {"frames": 0, "attached": 0}
    core, _ = ie_core(tmp_path, bridge)
    code, shown = core.dispatch("POST", "/api/record/start", {"window": "ie-tab:1"})
    assert code == 400 and "Không thấy khung nào" in shown["error"]
    bridge.start_recording = lambda tab_id, requests=False: {"frames": 2, "attached": 0, "inject_error": "Access is denied."}
    code, shown = core.dispatch("POST", "/api/record/start", {"window": "ie-tab:1"})
    assert code == 400 and "Trang từ chối bộ ghi: Access is denied." in shown["error"]


def test_a_diagnosis_run_goes_to_the_bridge_without_requests_and_is_not_refused_when_nothing_is_put_in(tmp_path):
    seen = {}
    bridge = FakeIeBridge()

    def start(tab_id, requests=False, diag=""):
        seen.update(requests=requests, diag=diag)
        return {"frames": 3, "attached": 0}
    bridge.start_recording = start
    core, _ = ie_core(tmp_path, bridge)
    code, _ = core.dispatch("POST", "/api/record/start", {"window": "ie-tab:1", "diag": "none", "preview": True})
    assert code == 200 and seen == {"requests": False, "diag": "none"}
    core.dispatch("POST", "/api/record/stop", {})
    code, shown = core.dispatch("POST", "/api/record/start", {"window": "ie-tab:1", "preview": True})      # normal: the same answer is a refusal
    assert code == 400
    code, _ = core.dispatch("POST", "/api/record/start", {"window": "ie-tab:1", "diag": "rubbish", "preview": True})  # an unknown level is a normal run
    assert code == 400


def test_learning_again_goes_on_when_the_server_already_has_the_recording(tmp_path):
    class AlreadySent(FakeServer):
        def post_session(self, session_id, engine, events):
            raise ServerError("Máy chủ từ chối (409): Phiên ghi này đã được gửi", 409)

    core, session = make_core(tmp_path, server_client=AlreadySent)
    record_one(core, session)
    assert core.dispatch("POST", "/api/learn", {"ids": [core.store.listing()[0]["id"]], "title": "Vấn tin"})[0] == 200


def test_the_exchange_log_shows_what_was_sent_and_received(tmp_path):
    import http.server
    import threading

    from rookie_agent import server_client

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(409); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write('{"detail": "Phiên ghi này đã được gửi"}'.encode("utf-8"))

        def log_message(self, *args):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.handle_request, daemon=True).start()
    client = server_client.ServerClient(f"http://127.0.0.1:{httpd.server_port}")
    with pytest.raises(ServerError) as refused:
        client.post_session("s-1", "ie", [])
    httpd.server_close()
    assert refused.value.status == 409
    last = server_client.exchanges()[0]
    assert last["status"] == 409 and '"session_id": "s-1"' in last["sent"] and "đã được gửi" in last["received"]
    core, _ = make_core(tmp_path)
    assert core.dispatch("GET", "/api/server/log", {})[1]["exchanges"][0] == last


def test_the_canvas_follows_the_run():
    page = (Path(__file__).resolve().parents[1] / "rookie_agent" / "webui" / "index.html").read_text(encoding="utf-8")
    for needle in ("function paintCanvas", "paintCanvas(status)", "b.dataset.step", ".node.st-run", "@keyframes rk-pulse"):
        assert needle in page, needle


def test_an_ie_recording_keeps_its_requests_as_templates_without_what_was_typed(tmp_path):
    """Task 7.1: the search request is kept with the typed customer id replaced by a mark; the password never appears."""
    lines = [ie_line("input", 1000, tag="input", type="text", id="txtCustomerId", label="Mã khách hàng", value="0123456789"),
             ie_line("input", 1100, tag="input", type="password", id="pw", label="Mật khẩu", value="TOPSECRET"),
             ie_line("click", 2000),
             {"t": 2050, "kind": "ajax", "frame": "desktopFrame/main", "method": "POST", "url": "/tp/find?id=0123456789", "status": 200,
              "ms": 30, "req": "id=0123456789", "res": "{}", "hdr": "Content-Type:text/plain\n"}]
    core, _ = ie_core(tmp_path, FakeIeBridge(after_stop=lines))
    core.dispatch("POST", "/api/record/start", {"window": "Internet Explorer: TouchPoint"})
    status, reply = core.dispatch("POST", "/api/record/stop", {"name": "tra cứu"})
    assert status == 200 and reply["requests_kept"] == 1
    document = core.store.load(reply["id"])
    kept = document["requests"][0]
    assert kept["url"] == "/tp/find?id=⟦e0⟧" and kept["body"] == "id=⟦e0⟧" and kept["after_seq"] == 1
    assert "0123456789" not in json.dumps(document) and "TOPSECRET" not in json.dumps(document)
