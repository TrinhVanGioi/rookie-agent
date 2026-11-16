"""The agent's end of the PowerShell bridge to Internet Explorer (ie-bridge.ps1).

A child process, one JSON line per request and per reply, all ASCII. The bridge reads the pages through COM
(Shell.Application), so nothing has to be installed and no browser setting changes.
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).with_name("ie-bridge.ps1")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class IeBridgeError(Exception):
    """The bridge is not there, or did not answer. The message is for the teller."""


class IeBridge:
    def __init__(self, command: list[str] | None = None) -> None:
        self._command = command or [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Sta", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
        ]
        self._process: subprocess.Popen | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()

    # ---- process ------------------------------------------------------------------

    def open(self, timeout: float = 20.0) -> "IeBridge":
        if self._process is not None and self._process.poll() is None:
            return self
        if sys.platform != "win32":
            raise IeBridgeError("Đọc trang Internet Explorer chỉ có trên Windows.")
        try:
            self._process = subprocess.Popen(
                self._command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=NO_WINDOW, text=True, encoding="ascii", errors="replace", bufsize=1,
            )
        except OSError as error:
            raise IeBridgeError(f"Không chạy được PowerShell: {error}") from error
        self._lines = queue.Queue()
        threading.Thread(target=self._read, args=(self._process,), daemon=True, name="ie-bridge-reader").start()
        ready = self._next(timeout)
        if not ready.get("ready"):
            self.close()
            raise IeBridgeError("Cầu nối trang IE không khởi động được.")
        return self

    def _read(self, process: subprocess.Popen) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            if process.poll() is None and process.stdin:
                process.stdin.write('{"cmd":"quit"}\n')
                process.stdin.flush()
                process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        if process.poll() is None:
            process.kill()

    # ---- requests -----------------------------------------------------------------

    def _next(self, timeout: float) -> dict[str, Any]:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            raise IeBridgeError("Cầu nối trang IE không trả lời (quá thời gian chờ).") from None
        if line is None:
            raise IeBridgeError("Cầu nối trang IE đã dừng. PowerShell có thể bị máy chặn.")
        try:
            return json.loads(line)
        except ValueError as error:
            raise IeBridgeError("Cầu nối trang IE trả lời sai dạng.") from error

    def request(self, message: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
        with self._lock:
            if self._process is None or self._process.poll() is not None or self._process.stdin is None:
                raise IeBridgeError("Cầu nối trang IE chưa chạy.")
            try:
                self._process.stdin.write(json.dumps(message, ensure_ascii=True) + "\n")
                self._process.stdin.flush()
            except (OSError, ValueError) as error:
                raise IeBridgeError("Không gửi được lệnh cho cầu nối trang IE.") from error
            reply = self._next(timeout)
        if not reply.get("ok"):
            raise IeBridgeError(str(reply.get("error") or "Cầu nối trang IE báo lỗi."))
        return reply

    # ---- what the agent needs -----------------------------------------------------

    def tabs(self) -> list[dict[str, Any]]:
        """The IE tabs that show a web page: [{id, title}]."""
        return list(self.request({"cmd": "tabs"}).get("tabs") or [])

    def probe(self, tab_id: int) -> dict[str, Any]:
        """Frames, input fields, buttons and objects (ActiveX or applet) of a tab, for the machine check."""
        return dict(self.request({"cmd": "probe", "id": tab_id}, timeout=30).get("info") or {})

    def start_recording(self, tab_id: int) -> None:
        self.request({"cmd": "start", "id": tab_id}, timeout=30)

    def poll(self) -> list[dict[str, Any]]:
        lines = self.request({"cmd": "poll"}, timeout=30).get("lines") or []
        return [parsed for parsed in (_parse(line) for line in lines) if parsed]

    def stop_recording(self) -> list[dict[str, Any]]:
        lines = self.request({"cmd": "stop"}, timeout=30).get("lines") or []
        return [parsed for parsed in (_parse(line) for line in lines) if parsed]


def _parse(line: Any) -> dict[str, Any] | None:
    if not isinstance(line, str):
        return None
    try:
        parsed = json.loads(line)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None
