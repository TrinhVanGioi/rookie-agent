"""The Internet Explorer side: the PowerShell bridge and the recorder that lives in the page.

The page-side recorder is run in the real MSHTML engine (the same engine and the same quirks mode as the IE pages),
through the COM object `htmlfile`. A real IE window with frames is not needed, and none is available on a PC without IE.
"""

import json
import subprocess
import sys
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
    events = [json.loads(line) for line in lines if line.startswith("{")]
    kinds = [(e["kind"], e["id"]) for e in events]
    assert kinds == [("input", "txtCustomerId"), ("submit", "pw"), ("input", "amt"), ("submit", "amt"), ("click", "btnSave")]
    assert events[0]["label"] == "Ma khach hang" and events[0]["value"] == "0123456789"  # raw here; the agent decides what to keep
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

    def start_recording(self, tab_id):
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


def test_a_tab_that_closes_in_the_middle_keeps_what_was_recorded_so_far():
    bridge = FakeBridge([[line("click", 1000, id="b1", label="Một")]], fail_after=1)
    session = IeSession(bridge, tab_id=1, app_title="TouchPoint", poll_seconds=0.01)
    session.start()
    while session.error is None:
        pass
    events = session.stop()
    assert len(events) == 1 and "đã đóng" in session.error
