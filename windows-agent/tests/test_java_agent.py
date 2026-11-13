"""The recording helper inside the Java application, on the real Swing mock.

The mock is started with the helper loaded through JAVA_TOOL_OPTIONS, exactly as it would be on a
teller's machine, so the application itself is not changed. The actions are made through Java Access
Bridge (no keyboard needed): `submit` runs the field's own accept action, which is what Enter does.
That the helper also sees real key presses was checked by hand with real keys.

Needs `java-agent/build.ps1` and `mock-java/build.ps1` to have been run; skipped otherwise.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
JAR = REPO / "java-agent" / "rookie-java-agent.jar"
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Java Access Bridge chỉ có trên Windows")


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    from rookie_agent import sandbox
    from rookie_agent.jab import bridge as jab
    from rookie_agent.jab.session import JabSession

    if not JAR.is_file():
        pytest.skip("Chưa build java-agent (java-agent\\build.ps1)")
    try:
        java, arguments = sandbox.find_mock()
    except jab.BridgeError as error:
        pytest.skip(str(error))
    home = tmp_path_factory.mktemp("agent-home")
    env = dict(os.environ, ROOKIE_AGENT_HOME=str(home), JAVA_TOOL_OPTIONS=f"-javaagent:{JAR}")
    process = subprocess.Popen([str(java), sandbox.BRIDGE_FLAG, "-Dfile.encoding=UTF-8", *arguments], env=env, stderr=subprocess.DEVNULL)
    session = JabSession().open()
    try:
        hwnd, _ = session.wait_for_window("Mock TPSS", timeout=30)
        yield session, hwnd, home
    finally:
        session.close()
        process.kill()
        process.wait(timeout=10)


def wait_for_title(session, part: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if any(part in title for _, title in session.windows()):
            return
        time.sleep(0.1)
    raise AssertionError(f"Không thấy màn hình {part!r}: {session.windows()}")


def event_lines(home: Path) -> int:
    folder = home / "java-events"
    return sum(len(path.read_bytes().splitlines()) for path in folder.glob("*.jsonl")) if folder.exists() else 0


def test_silent_until_recording_then_records_enter_and_clicks_once_each(app, assert_valid_events):
    from rookie_agent.java_feed import JavaFeed
    from rookie_agent.jab.driver import JabDriver
    from rookie_agent.jab.session import JabSession
    from rookie_agent.recorder import Recorder
    from rookie_agent.selectors import selectors_for

    session, hwnd, home = app
    driver = JabDriver(session, hwnd)

    # not recording: the helper does nothing at all
    driver.fill(["role=text[name='Tên đăng nhập']"], "gdv01")
    time.sleep(0.8)
    assert event_lines(home) == 0

    recorder = Recorder()
    session.attach(recorder)
    feed = JavaFeed(recorder, home=home)
    feed.start("s-keys")
    time.sleep(1.2)  # the helper looks for the flag a few times a second

    driver.fill(["role=text[name='Tên đăng nhập']"], "gdv01")
    driver.fill(["role=password text[name='Mật khẩu']"], "demo-only-1234")
    time.sleep(0.5)
    driver.submit(["role=password text[name='Mật khẩu']"])  # Enter in the password field: no event in Java Access Bridge
    wait_for_title(session, "Khách hàng")
    time.sleep(1.0)  # the helper listens to the new screen
    driver.fill(["role=text[name='Số CIF hoặc CCCD']"], "00103840")
    driver.click(["role=push button[name='Tra cứu CIF']"])
    time.sleep(1.0)
    feed.stop()
    session.detach()
    events = recorder.stop()
    assert_valid_events(events)

    summary = [(e["type"], e["target"]["label"]) for e in events]
    assert ("submit", "Mật khẩu") in summary
    assert summary.count(("click", "Tra cứu CIF")) == 1  # the bridge and the helper may both report it; it is one click
    assert summary.index(("submit", "Mật khẩu")) < summary.index(("click", "Tra cứu CIF"))
    dumped = json.dumps(events, ensure_ascii=False)
    for secret in ("demo-only-1234", "00103840"):
        assert secret not in dumped
    assert all(e["value"] is None for e in events if e["type"] in ("submit", "click"))

    # the helper names a component exactly as the bridge recorder does, which is what makes the de-duplication work
    element = session.with_element(hwnd, ["role=push button[name='Tra cứu CIF']"], lambda b, vm, c: JabSession._element(b, vm, c))
    click = next(e for e in events if e["type"] == "click" and e["target"]["label"] == "Tra cứu CIF")
    assert click["target"]["selectors"] == selectors_for(element)
    assert click["url"] == element.window

    # recording stopped: the helper is silent again
    before = event_lines(home)
    driver.click(["role=push button[name='Tra cứu CIF']"])
    time.sleep(1.0)
    assert event_lines(home) == before
