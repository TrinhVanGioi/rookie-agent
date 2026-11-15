"""An applet in Internet Explorer is a Java window inside the browser's window, not a top-level window.

This puts the Swing mock inside another native window the same way and checks the agent still finds it and
can read its component tree. Skipped without a JDK (bridge DLL of this Python's bitness) or the built mock.
"""

import ctypes
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MOCK_CLASSES = REPO / "mock-java" / "out"

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Java Access Bridge chỉ có trên Windows")

GWL_STYLE = -16
WS_POPUP, WS_CHILD, WS_VISIBLE, WS_CAPTION = 0x80000000, 0x40000000, 0x10000000, 0x00C00000


@pytest.fixture
def embedded_mock():
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
        [str(java), "-Djavax.accessibility.assistive_technologies=com.sun.java.accessibility.AccessBridge",
         "-Dfile.encoding=UTF-8", "-cp", str(MOCK_CLASSES), "mocktpss.Main"]
    )
    session = JabSession().open()
    user32 = ctypes.windll.user32
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    host = None
    try:
        hwnd, _ = session.wait_for_window("Mock TPSS", timeout=30)
        host = user32.CreateWindowExW(0, "STATIC", "Cổng thử - Internet Explorer", WS_POPUP | WS_VISIBLE | WS_CAPTION, 50, 50, 1200, 800, None, None, None, None)
        assert host, "could not create the host window"
        style = user32.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF
        user32.SetWindowLongW(hwnd, GWL_STYLE, ctypes.c_long((style & ~WS_POPUP & ~WS_CAPTION) | WS_CHILD | WS_VISIBLE).value)
        user32.SetParent(hwnd, host)
        user32.MoveWindow(hwnd, 0, 0, 1000, 700, True)
        yield session, hwnd, host
    finally:
        session.close()
        if host:
            user32.DestroyWindow(host)
        process.kill()
        process.wait(timeout=10)


def test_a_java_window_inside_another_window_is_found(embedded_mock):
    session, hwnd, host = embedded_mock
    user32 = ctypes.windll.user32
    assert user32.GetParent(hwnd) == host  # it really is a child window now
    found = dict(session.windows())
    assert hwnd in found
    assert "Mock TPSS" in found[hwnd]
    node = session.tree(hwnd)
    assert node.children  # the component tree can be read through the child window


def test_an_applet_without_its_own_name_is_named_after_the_browser_window(embedded_mock):
    from rookie_agent.jab import bridge as jab

    _, hwnd, host = embedded_mock
    assert jab.host_title(hwnd) == "Cổng thử - Internet Explorer"
