"""The Internet Explorer side: the PowerShell bridge and the recorder that lives in the page.

The page-side recorder is run in the real MSHTML engine (the same engine and the same quirks mode as the IE pages),
through the COM object `htmlfile`. A real IE window with frames is not needed, and none is available on a PC without IE.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from rookie_agent.ie.bridge import IeBridge, IeBridgeError
from rookie_agent.ie.session import IeSession

IE_DIR = Path(__file__).resolve().parents[1] / "rookie_agent" / "ie"
CHECK = Path(__file__).with_name("ie_mshtml_check.ps1")
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Cần Windows")


def run_mshtml_check() -> list[str]:
    try:
        done = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Sta", "-ExecutionPolicy", "Bypass", "-File", str(CHECK), "-JsPath", str(IE_DIR / "page_recorder.js")],
            capture_output=True, text=True, encoding="utf-8", timeout=45,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("Bộ ghi trong trang làm treo MSHTML (thường do chuỗi script không phải [string] thuần hoặc lỗi cú pháp).")
    if "FLAGS" not in done.stdout:
        pytest.skip("Máy này không tạo được đối tượng htmlfile: " + done.stderr[:200])
    return done.stdout.splitlines()


@windows_only
def test_the_page_recorder_runs_in_real_mshtml_quirks_mode_and_keeps_secrets_out():
    lines = run_mshtml_check()
    flags = next(line for line in lines if line.startswith("FLAGS")).split(" ", 1)[1]
    assert flags == "BackCompat|undefined|undefined"  # quirks mode: no JSON, no addEventListener, like the old pages
    everything_raw = [json.loads(line) for line in lines if line.startswith("{")]
    events = [e for e in everything_raw if e["kind"] in ("click", "input", "select", "submit")]
    kinds = [(e["kind"], e["id"]) for e in events]
    assert kinds[:5] == [("input", "txtCustomerId"), ("submit", "pw"), ("input", "amt"), ("submit", "amt"), ("click", "btnSave")]
    # Everything the teller presses is recorded (Gate 4): a tab (hand cursor), a row of a list, the text of a menu item, and also
    # plain text that nothing says can be pressed, but that one is marked ctl:false (not a control) for the model to judge.
    # A row of a list is named by its position only: its text can be a customer name
    after = events[5:-1]
    # a field that already had the focus when recording began (the login page puts the cursor in the user field): what is typed there
    # is still recorded, although no focusin was ever seen for it
    assert (events[-1]["kind"], events[-1]["id"], events[-1]["value"]) == ("input", "txtUser", "teller01")
    assert [(e["tag"], e["id"], e["label"], e.get("ctl")) for e in after] == [
        ("td", "tabHoSo", "Ho so", True), ("div", "plain", "Chi la chu, khong bam duoc", False),
        ("tr", "row1", "dòng 2", True), ("span", "inner", "Duy tri", True),
    ]
    assert events[0]["label"] == "Ma khach hang" and events[0]["value"] == "0123456789"  # raw here; the agent decides what to keep
    # focus and blur of a field are recorded; a password field leaves nothing at all, and no key carries a character
    assert [e["id"] for e in everything_raw if e["kind"] == "focus"] == ["txtCustomerId", "amt"]
    assert "blur" in {e["kind"] for e in everything_raw}
    assert all(e.get("keyclass") in (None, "enter", "tab", "escape", "function", "arrow", "char") for e in everything_raw)
    everything = "\n".join(lines)
    assert "TOPSECRET" not in everything and "SECRET1" not in everything  # a password and a hidden field are never read


@windows_only
def test_the_bridge_starts_answers_and_lists_tabs_without_needing_any_ie_window():
    bridge = IeBridge().open()
    try:
        assert isinstance(bridge.tabs(), list)
        with pytest.raises(IeBridgeError):
            bridge.request({"cmd": "no-such-command"})
        with pytest.raises(IeBridgeError):
            bridge.request({"cmd": "poll"})  # nothing started yet
    finally:
        bridge.close()


class FakeBridge:
    def __init__(self, batches, fail_after=None):
        self.batches, self.calls, self.started, self.fail_after = list(batches), 0, None, fail_after

    def start_recording(self, tab_id, requests=False):
        self.started = tab_id

    def poll(self):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise IeBridgeError("tab đã đóng")
        return self.batches.pop(0) if self.batches else []

    def stop_recording(self):
        return self.batches.pop(0) if self.batches else []


def line(kind, t, **fields):
    base = {"t": t, "kind": kind, "frame": "top", "title": "Main", "tag": "button", "type": "button", "id": "b", "name": "", "label": "Lưu", "pos": 0, "value": None}
    base.update(fields)
    return base


def test_a_session_collects_what_the_bridge_reports_and_the_rest_at_stop():
    bridge = FakeBridge([[line("click", 1000, id="b1", label="Một")], [], [line("click", 3000, id="b2", label="Hai")]])
    session = IeSession(bridge, tab_id=3, app_title="TouchPoint", poll_seconds=0.01)
    session.start()
    while bridge.calls < 2:
        pass
    events = session.stop()
    assert bridge.started == 3
    assert [e["target"]["label"] for e in events] == ["Một", "Hai"]
    assert session.session_id == events[0]["session_id"]


def test_what_the_recorder_could_reach_is_left_in_the_log_when_it_changes(capsys):
    bridge = FakeBridge([[], []])
    bridge.diag = "window 1 frame='' host=tp.example ready=complete mode=8 listen=attachEvent | frame #0 unreadable: Access is denied"
    session = IeSession(bridge, tab_id=1, app_title="TouchPoint", poll_seconds=0.01)
    session.start()
    while bridge.calls < 2:
        pass
    session.stop()
    out = capsys.readouterr().out
    assert "[ie-ghi]" in out and "unreadable" in out and "tp.example" in out


def test_a_session_keeps_every_raw_line_for_the_trace_even_those_the_old_recorder_ignores():
    bridge = FakeBridge([[line("focus", 900, id="u"), line("key", 950, id="u", keyclass="tab")], [line("click", 1000, id="b1", label="Một")]])
    session = IeSession(bridge, tab_id=1, app_title="TouchPoint", poll_seconds=0.01)
    session.start()
    while bridge.calls < 2:
        pass
    events = session.stop()
    assert [raw["kind"] for raw in session.raw] == ["focus", "key", "click"]
    assert [e["type"] for e in events] == ["click"]  # the old pipeline is unchanged


def test_one_bad_line_or_a_failing_log_does_not_end_the_recording_silently(monkeypatch):
    bridge = FakeBridge([[line("click", 1000, id="b1", label="Một")], [line("click", 2000, id="b2", label="Hai")], [line("click", 3000, id="b3", label="Ba")]])
    bridge.diag = "note with a character a console cannot print: ạ"
    session = IeSession(bridge, tab_id=1, app_title="TouchPoint", poll_seconds=0.01)
    real = session.recorder.handle
    seen = []

    def flaky(raw):
        seen.append(raw["id"])
        if raw["id"] == "b1":
            raise ValueError("a line the recorder cannot read")
        real(raw)

    monkeypatch.setattr(session.recorder, "handle", flaky)
    monkeypatch.setattr("builtins.print", lambda *a, **k: (_ for _ in ()).throw(UnicodeEncodeError("ascii", "ạ", 0, 1, "x")))
    session.start()
    while bridge.calls < 4:
        pass
    events = session.stop()
    assert seen == ["b1", "b2", "b3"] and [e["target"]["label"] for e in events] == ["Hai", "Ba"]
    assert "Bỏ qua một dòng" in session.error  # said, not hidden


def test_a_line_that_arrives_twice_is_kept_once():
    """A page that is left with a line not yet taken keeps it in a cookie; the poll may take it too. Each line has a unique id."""
    twice = line("submit", 1000, id="pw", tag="input", type="password", label="Password", uid="u-1")
    bridge = FakeBridge([[twice], [dict(twice)], [line("click", 3000, id="b", label="OK", uid="u-2")]])
    session = IeSession(bridge, tab_id=1, app_title="TouchPoint", poll_seconds=0.01)
    session.start()
    while bridge.calls < 3:
        pass
    events = session.stop()
    assert [(e["type"], e["target"]["label"]) for e in events] == [("submit", "Password"), ("click", "OK")]
    assert [r["uid"] for r in session.raw] == ["u-1", "u-2"]


def test_a_tab_that_closes_in_the_middle_keeps_what_was_recorded_so_far():
    bridge = FakeBridge([[line("click", 1000, id="b1", label="Một")]], fail_after=1)
    session = IeSession(bridge, tab_id=1, app_title="TouchPoint", poll_seconds=0.01)
    session.start()
    while session.error is None:
        pass
    events = session.stop()
    assert len(events) == 1 and "đã đóng" in session.error


# ---- tasks 4.31 and 4.32: the session looks at the screen after each action, once it is quiet ----

class ReadingBridge(FakeBridge):
    """A bridge whose screen can be scripted: `screens` is a list of lists of raw frame texts, one per look."""

    def __init__(self, batches, screens):
        super().__init__(batches)
        self.screens, self.looks = list(screens), 0

    def read(self):
        self.looks += 1
        return self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]


def screen(*, table_rows=None, clock=None, message=None):
    import json as _json

    fields = [{"label": "Gio", "value": clock}] if clock else []
    tables = [{"id": "grid", "headers": ["So TK", "Loai"], "rows": table_rows, "row_count": len(table_rows)}] if table_rows else []
    messages = [{"level": "error", "text": message}] if message else []
    return [_json.dumps({"frame": "main", "title": "T", "tables": tables, "fields": fields, "messages": messages})]


def test_after_an_action_the_session_reads_the_screen_and_keeps_the_region_that_changed():
    # each look reads the screen three times; the clock differs inside every look, so it is known to change by itself
    looks = [screen(clock="09:00:01"), screen(clock="09:00:02"), screen(clock="09:00:03"),
             screen(table_rows=[["001", "DDA"]], clock="09:00:04"), screen(table_rows=[["001", "DDA"]], clock="09:00:05"),
             screen(table_rows=[["001", "DDA"]], clock="09:00:06")]
    bridge = ReadingBridge([[] for _ in range(12)] + [[line("click", 1000, id="btnFind", label="TIM KIEM")]], looks)
    session = IeSession(bridge, tab_id=1, app_title="TouchPoint", poll_seconds=0.01, settle_seconds=0.03)
    session.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not any(s["after"] for s in session.seen):
        time.sleep(0.02)
    session.stop()
    last = next(s for s in session.seen if s["after"])
    assert last["after"]["id"] == "btnFind" and last["region"] == ["main"]
    assert [c["kind"] for c in last["changed"]] == ["table"]               # the clock is not the result
    assert last["frames"][0]["tables"][0]["rows"] == [["001", "DDA"]]       # the full values are there, in memory
    assert "1 dòng" in last["summary"]


def test_a_bridge_that_cannot_read_does_not_stop_the_recording():
    class Deaf(FakeBridge):
        def read(self):
            raise IeBridgeError("không đọc được")

    bridge = Deaf([[line("click", 1000, id="b1", label="Một")], []])
    session = IeSession(bridge, tab_id=1, app_title="TouchPoint", poll_seconds=0.01, settle_seconds=0.02)
    session.start()
    time.sleep(0.4)
    events = session.stop()
    assert [e["target"]["label"] for e in events] == ["Một"] and session.seen == []


def test_a_result_that_appears_between_two_reads_is_not_mistaken_for_a_clock():
    rows = [["001", "DDA"]]
    looks = [screen(), screen(), screen(),                                    # the first look: nothing yet
             screen(), screen(table_rows=rows), screen(table_rows=rows)]      # the result lands between the 1st and the 2nd read
    bridge = ReadingBridge([[] for _ in range(12)] + [[line("click", 1000, id="btnFind", label="TIM KIEM")]], looks)
    session = IeSession(bridge, tab_id=1, app_title="TouchPoint", poll_seconds=0.01, settle_seconds=0.03)
    session.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not any(x["after"] for x in session.seen):
        time.sleep(0.02)
    session.stop()
    snap = next(x for x in session.seen if x["after"])
    assert [c["kind"] for c in snap["changed"]] == ["table"]
