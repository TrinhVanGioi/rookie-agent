"""End-to-end check against the real Swing mock through Java Access Bridge.

Skipped when the machine has no JDK with the bridge DLL of this Python's bitness,
or when `mock-java/out` has not been built (run `mock-java/build.ps1`).

The mock is driven through the bridge (set text, select tab, select row), which
needs no real mouse or keyboard. Clicks on buttons are reported by the bridge only
for real mouse input, so that path is covered by the unit tests of the recorder.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MOCK_CLASSES = REPO / "mock-java" / "out"
PASSWORD = "demo-only-1234"
TYPED_SECRETS = [PASSWORD, "gdv01", "001012345678", "002098765432", "5000000"]

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Java Access Bridge chỉ có trên Windows")


@pytest.fixture(scope="module")
def mock():
    from rookie_agent.jab import bridge as jab
    from rookie_agent.jab.session import JabSession

    try:
        dll = jab.find_dll()
    except jab.BridgeError as error:
        pytest.skip(str(error))
    java = dll.parent / "java.exe"
    if not java.is_file() or not (MOCK_CLASSES / "mocktpss" / "Main.class").is_file():
        pytest.skip("Cần java.exe cạnh DLL và mock-java/out đã build")

    process = subprocess.Popen(
        [
            str(java),
            # Turns the bridge on for this process only; no change to the user's settings.
            "-Djavax.accessibility.assistive_technologies=com.sun.java.accessibility.AccessBridge",
            "-Dfile.encoding=UTF-8",
            "-cp",
            str(MOCK_CLASSES),
            "mocktpss.Main",
        ]
    )
    session = JabSession().open()
    try:
        hwnd, _ = session.wait_for_window("Mock TPSS", timeout=30)
        yield session, hwnd
    finally:
        session.close()
        process.kill()
        process.wait(timeout=10)


def _fill(session, hwnd, role: str, name: str, value: str) -> None:
    def act(bridge, vm, context):
        bridge.request_focus(vm, context)
        assert bridge.set_text(vm, context, value)

    session.with_element(hwnd, [f"role={role}[name='{name}']"], act)
    time.sleep(0.3)


def _wait_title(session, part: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if any(part in title for _, title in session.windows()):
            return
        time.sleep(0.1)
    raise AssertionError(f"Không thấy cửa sổ có tiêu đề chứa {part!r}: {session.windows()}")


def _flatten(node):
    yield node
    for child in node.children:
        yield from _flatten(child)


def test_reads_the_login_screen(mock):
    session, hwnd = mock
    nodes = {(node.role, node.name) for node in _flatten(session.tree(hwnd))}
    assert {("text", "Tên đăng nhập"), ("password text", "Mật khẩu"), ("push button", "Đăng nhập")} <= nodes


def test_records_a_transfer_without_leaking_values(mock, assert_valid_events):
    from rookie_agent.recorder import Recorder

    session, hwnd = mock
    recorder = Recorder()
    session.attach(recorder)

    _fill(session, hwnd, "text", "Tên đăng nhập", "gdv01")
    _fill(session, hwnd, "password text", "Mật khẩu", PASSWORD)
    session.with_element(
        hwnd, ["role=push button[name='Đăng nhập']"], lambda b, vm, c: b.do_action(vm, c, "click")
    )
    _wait_title(session, "Khách hàng (CIF)")

    # Path selectors recorded on one screen must resolve on the same screen.
    path = "path=frame/root pane[0]/layered pane[1]/page tab list[1]"
    assert session.with_element(hwnd, [path], lambda b, vm, c: b.info(vm, c).name) == "Chức năng"

    session.with_element(hwnd, ["role=page tab list[name='Chức năng']"], lambda b, vm, c: b.select_child(vm, c, 1))
    _wait_title(session, "Chuyển tiền")
    _fill(session, hwnd, "text", "Tài khoản chuyển", "001012345678")
    _fill(session, hwnd, "text", "Tài khoản nhận", "002098765432")
    _fill(session, hwnd, "text", "Số tiền", "5000000")
    # Move focus away so the last field is written out the way a user leaving it would.
    session.with_element(hwnd, ["role=text[name='Nội dung']"], lambda b, vm, c: b.request_focus(vm, c))
    time.sleep(0.5)

    session.detach()
    events = recorder.stop()
    assert_valid_events(events)

    summary = [(e["type"], e["target"]["label"], e["value_class"]) for e in events]
    assert ("input", "Tên đăng nhập", "username") in summary
    assert ("click", "Chuyển tiền", None) in summary
    assert summary[-3:] == [
        ("input", "Tài khoản chuyển", "account_number"),
        ("input", "Tài khoản nhận", "account_number"),
        ("input", "Số tiền", "amount"),
    ]
    assert all(e["target"]["label"] != "Mật khẩu" for e in events), "ô mật khẩu không được sinh sự kiện"
    assert all(e["value"] is None for e in events if e["type"] == "input")
    assert events[-1]["url"] == "Mock TPSS - Chuyển tiền"

    dumped = json.dumps(events, ensure_ascii=False)
    for secret in TYPED_SECRETS:
        assert secret not in dumped, f"giá trị nhạy cảm lọt vào event: {secret}"


def test_ambiguous_name_falls_back_to_the_next_selector(mock):
    session, hwnd = mock
    # After the previous test the transfer tab is open and its form has unnamed labels.
    with pytest.raises(LookupError):
        session.with_element(hwnd, ["role=label[name='']"], lambda b, vm, c: None)
