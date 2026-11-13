"""Sandbox for Java workflows: run a `draft` on the Swing mock and report the result to the server (task 2.9).

The sandbox starts its own copy of the mock with synthetic data, logs in with the
mock's demo account and runs the workflow without asking anyone. It refuses to
run on any window that is not the mock.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from rookie_agent.controllers import ConsoleController  # noqa: F401  (re-exported for callers)
from rookie_agent.jab import bridge as jab
from rookie_agent.jab.driver import JabDriver
from rookie_agent.jab.session import JabSession
from rookie_agent.runner import AutoController, run_workflow
from rookie_agent.server_client import ServerClient

REPO = Path(__file__).resolve().parents[2]
BRIDGE_FLAG = "-Djavax.accessibility.assistive_technologies=com.sun.java.accessibility.AccessBridge"
# Synthetic accounts of the mock. Never real credentials.
MOCK_USERS = {"maker": ("gdv01", "demo-only-1234"), "checker": ("ksv01", "demo-only-5678")}


def find_mock() -> tuple[Path, list[str]]:
    """Return (java.exe, arguments that start the mock). Prefers the built classes, then the jar."""
    candidates = [Path(os.environ["ROOKIE_JAVA"])] if os.environ.get("ROOKIE_JAVA") else []
    candidates.append(jab.find_dll().parent / "java.exe")
    java = next((path for path in candidates if path.is_file()), None)
    if java is None:
        raise jab.BridgeError("Không thấy java.exe cạnh WindowsAccessBridge DLL. Đặt ROOKIE_JAVA.")
    classes = REPO / "mock-java" / "out"
    jar = REPO / "mock-java" / "mock-tpss.jar"
    if (classes / "mocktpss" / "Main.class").is_file():
        return java, ["-cp", str(classes), "mocktpss.Main"]
    if jar.is_file():
        return java, ["-jar", str(jar)]
    raise jab.BridgeError("Chưa có mock Swing. Chạy mock-java\\build.ps1 hoặc dùng gói đã có mock-tpss.jar.")


def start_mock() -> subprocess.Popen:
    java, arguments = find_mock()
    # The flag turns the bridge on for this process only; the user's settings stay as they are.
    return subprocess.Popen([str(java), BRIDGE_FLAG, "-Dfile.encoding=UTF-8", *arguments])


def login(session: JabSession, hwnd: int, role: str = "maker", timeout: float = 10.0) -> None:
    """Log in to the mock as the maker or the checker."""
    user, password = MOCK_USERS[role]
    driver = JabDriver(session, hwnd)
    driver.fill(["role=text[name='Tên đăng nhập']"], user)
    driver.fill(["role=password text[name='Mật khẩu']"], password)
    driver.click(["role=push button[name='Đăng nhập']"])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if "Đăng nhập" not in driver.window_title():
            return
        time.sleep(0.1)
    raise jab.BridgeError("Mock không cho đăng nhập.")


def run_in_sandbox(
    workflow: dict[str, Any], inputs: dict[str, str], role: str = "maker", element_timeout: float = 10.0
) -> dict[str, Any]:
    """Start the mock, log in, run the workflow, close the mock. Returns the run result."""
    process = start_mock()
    session = JabSession().open()
    try:
        hwnd, _ = session.wait_for_window("Mock TPSS", timeout=30)
        login(session, hwnd, role)
        return run_workflow(
            workflow,
            inputs,
            JabDriver(session, hwnd),
            AutoController(),
            sandbox=True,
            element_timeout=element_timeout,
        )
    finally:
        session.close()
        process.kill()
        process.wait(timeout=10)


def sandbox_and_report(
    server: ServerClient, workflow_id: str, version: int, inputs: dict[str, str], role: str = "maker"
) -> dict[str, Any]:
    """Run a stored workflow version in the sandbox and report the outcome to the server."""
    reply = server.workflow_version(workflow_id, version)
    result = run_in_sandbox(reply["workflow"], inputs, role)
    server.post_test_run(workflow_id, version, result)
    return result
