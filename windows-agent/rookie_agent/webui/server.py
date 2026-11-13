"""The local web page: `python -m rookie_agent web`. Listens on this PC only (127.0.0.1)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from rookie_agent import diagnose
from rookie_agent.java_feed import JavaFeed, agent_home
from rookie_agent.webui.core import Core

PORT = 8765
SERVER_PORT = 8000
PAGE = Path(__file__).with_name("index.html")
AGENT_ROOT = Path(__file__).resolve().parents[2]  # windows-agent/
PACKAGE_ROOT = AGENT_ROOT.parent
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def runtime_python(bits: int) -> Path | None:
    """The bundled Python of the wanted bitness (package folder runtime\\py32 or py64)."""
    for name in ("pythonw.exe", "python.exe"):
        candidate = PACKAGE_ROOT / "runtime" / f"py{bits}" / name
        if candidate.is_file():
            return candidate
    return None


def relaunch(bits: int, port: int = PORT, start_server: bool = False) -> None:
    python = runtime_python(bits)
    if python is None:
        raise RuntimeError(f"Gói này không có Python {bits}-bit.")
    command = [str(python), "-m", "rookie_agent", "web", "--port", str(port), "--no-browser"]
    if start_server:
        command.append("--start-server")
    subprocess.Popen(command, cwd=str(AGENT_ROOT), creationflags=NO_WINDOW)


class LocalServer:
    """The learning server, started on this PC with the bundled Python when the teller asks."""

    def __init__(self, home: Path) -> None:
        self._home = home
        self._process: subprocess.Popen | None = None

    def start(self) -> str:
        url = f"http://localhost:{SERVER_PORT}"
        if self._alive(url):
            return url
        python = runtime_python(64) or runtime_python(32)
        if python is None:
            raise RuntimeError("Gói này không có Python để chạy máy chủ.")
        python_exe = python.with_name("python.exe")
        env = dict(os.environ, ROOKIE_DB=str(self._home / "rookie.db"), PYTHONUTF8="1")
        self._process = subprocess.Popen(
            [str(python_exe if python_exe.is_file() else python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(SERVER_PORT)],
            cwd=str(PACKAGE_ROOT / "server"), env=env, creationflags=NO_WINDOW,
            stdout=open(self._home / "server.log", "ab"), stderr=subprocess.STDOUT,
        )
        for _ in range(40):
            if self._alive(url):
                return url
            if self._process.poll() is not None:
                break
            time.sleep(0.5)
        raise RuntimeError(f"Máy chủ không bật được. Xem {self._home / 'server.log'}")

    @staticmethod
    def _alive(url: str) -> bool:
        try:
            with urllib.request.urlopen(url + "/health", timeout=1):
                return True
        except OSError:
            return False

    def stop(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()


def make_handler(core: Core, port: int, on_shutdown: Any):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: Any) -> None:
            pass

        def _send(self, status: int, payload: bytes, kind: str = "application/json; charset=utf-8") -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, status: int, data: dict[str, Any]) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"))

        def _guarded(self) -> bool:
            """Only this PC's own page may talk to the agent: another site in the browser must not."""
            if self.headers.get("Host", "") not in allowed_hosts:
                self._json(403, {"error": "Chỉ dùng được từ chính máy này."})
                return False
            if self.command == "POST":
                origin = self.headers.get("Origin")
                if (origin and origin.split("//")[-1] not in allowed_hosts) or self.headers.get("X-Rookie") != "1":
                    self._json(403, {"error": "Yêu cầu không hợp lệ."})
                    return False
            return True

        def do_GET(self) -> None:
            if not self._guarded():
                return
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/ping":
                self._json(200, {"rookie": True})
            else:
                status, data = core.dispatch("GET", path, {})
                self._json(status, data)

        def do_POST(self) -> None:
            if not self._guarded():
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self._json(400, {"error": "Yêu cầu không đọc được."})
                return
            status, data = core.dispatch("POST", self.path.split("?")[0], body if isinstance(body, dict) else {})
            self._json(status, data)
            if status == 200 and self.path == "/api/switch-bits" and data.get("switched"):
                threading.Thread(target=on_shutdown, daemon=True).start()

    return Handler


def build_core(home: Path, local_server: LocalServer, start_server: bool = False) -> Core:
    from rookie_agent.jab import bridge as jab
    from rookie_agent.jab.session import JabSession

    def dll_info() -> tuple[str | None, str | None]:
        try:
            return str(jab.find_dll()), None
        except jab.BridgeError as error:
            return None, str(error)

    return Core(
        home=home, open_session=lambda: JabSession().open(), own_bits=jab.BITS, dll_info=dll_info,
        feed_factory=lambda recorder: JavaFeed(recorder), server_starter=local_server.start,
        relauncher=lambda bits: relaunch(bits, start_server=start_server),
    )


def already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as reply:
            return json.loads(reply.read()).get("rookie") is True
    except (OSError, ValueError):
        return False


def main(port: int = PORT, open_browser: bool = True, auto_bits: bool = False, start_server: bool = False) -> None:
    home = agent_home()
    home.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:  # started without a console (pythonw)
        log = open(home / "agent.log", "a", encoding="utf-8")
        sys.stdout = sys.stderr = log
    url = f"http://localhost:{port}"
    if already_running(port):
        if open_browser:
            webbrowser.open(url)
        return
    if auto_bits:
        import struct

        own = struct.calcsize("P") * 8
        wanted = diagnose.wanted_bits(diagnose.java_users(), diagnose.find_java_installs(), own)
        if wanted != own and runtime_python(wanted):
            relaunch(wanted, port, start_server)
            return
    local_server = LocalServer(home)
    core = build_core(home, local_server, start_server)
    box: dict[str, ThreadingHTTPServer] = {}
    handler = make_handler(core, port, lambda: (time.sleep(0.5), box["server"].shutdown()))
    for attempt in range(20):  # a copy that is handing over may still hold the port for a moment
        try:
            box["server"] = ThreadingHTTPServer(("127.0.0.1", port), handler)
            break
        except OSError:
            if attempt == 19:
                raise
            time.sleep(0.5)
    if open_browser:
        webbrowser.open(url)
    if start_server:  # at Windows logon: the learning server is ready before the teller needs it
        def warm_up() -> None:
            try:
                local_server.start()
            except Exception as error:
                print("Máy chủ học chưa bật được:", error)

        threading.Thread(target=warm_up, daemon=True).start()
    try:
        box["server"].serve_forever()
    finally:
        local_server.stop()
