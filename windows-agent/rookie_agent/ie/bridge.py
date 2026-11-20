"""The agent's end of the PowerShell bridge to Internet Explorer (ie-bridge.ps1).

A child process, one JSON line per request and per reply, all ASCII. The bridge reads the pages through COM
(Shell.Application), so nothing has to be installed and no browser setting changes.
"""

from __future__ import annotations

import base64
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
        self.diag: str | None = None

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

    def start_recording(self, tab_id: int, requests: bool = False, diag: str = "") -> dict[str, Any]:
        """Put the recorder into the page. Answers how many frames were reached (`frames`) and how many now listen (`attached`)."""
        return self.request({"cmd": "start", "id": tab_id, "requests": bool(requests), "diag": diag}, timeout=30)

    def bind(self, tab_id: int, peek: bool = False) -> dict[str, Any]:
        """The tab the agent drives while it runs a flow. `peek`: the page's requests are remembered in its memory from now on (the last
        bodies per path, nothing recorded, nothing written), so a run of API calls can take the session value the page uses now."""
        message: dict[str, Any] = {"cmd": "bind", "id": tab_id}
        if peek:
            message["peek"] = True
        return self.request(message, timeout=30)

    def unbind(self) -> None:
        self.request({"cmd": "unbind"})

    def act(self, op: str, selectors: list[str], value: str = "") -> dict[str, Any]:
        """Do `op` (find, exists, read, click, fill, select, submit) on the one element the selectors name, in whichever frame it is.
        The answer is `{ok, ...}` or `{ok: False, error}` with the error not_found, ambiguous, disabled, secret, no_option..."""
        reply = self.request({"cmd": "act", "op": op, "selectors": selectors, "value": value}, timeout=60)
        return dict(reply.get("result") or {"ok": False, "error": "no_answer"})

    def locate(self, selectors: list[str]) -> list[dict[str, Any]]:
        """Task 6.1: for each frame that has any of the selectors, `{frame, probes: [{kind, m: [element numbers]}], fields: {n: 0|1}}`."""
        reply = self.request({"cmd": "locate", "selectors": selectors}, timeout=60)
        return list(reply.get("frames") or [])

    def frame_op(self, op: str, selectors: list[str], value: str = "") -> list[dict[str, Any]]:
        """Task 6.2: `suggest`, `mark` or `unmark` asked of every frame; the frames that answered."""
        reply = self.request({"cmd": "frameop", "op": op, "selectors": selectors, "value": value}, timeout=60)
        return list(reply.get("frames") or [])

    def send(self, frame: str, method: str, url: str, headers: str, body: str, timeout: float = 30.0,
             sleep: Any = None) -> dict[str, Any]:
        """Gate 7: one learned request sent again by the page of `frame` in the bound tab, in the teller's session. Returns
        `{ok, status, ms, text}` or `{ok: False, error}` (no_frame, timeout, or what the page said). The answer stays in memory."""
        import time as _time

        pause = sleep or _time.sleep
        payload = "\u0001".join([frame, method, url, headers, body])
        started = [a for a in self.frame_op("send", [], payload) if isinstance(a, dict) and a.get("id")]
        if not started:
            return {"ok": False, "error": "no_frame"}
        ask = started[0]["id"]
        deadline = _time.monotonic() + timeout
        while True:
            done = [a for a in self.frame_op("sendres", [], ask) if isinstance(a, dict) and a.get("id") == ask and a.get("done")]
            if done:
                answer = done[0]
                if answer.get("error"):
                    return {"ok": False, "error": str(answer["error"])}
                if answer.get("file"):
                    return self._file_answer(ask, answer)
                return {"ok": True, "status": int(answer.get("status") or 0), "ms": int(answer.get("ms") or 0), "text": str(answer.get("text") or "")}
            if _time.monotonic() >= deadline:
                return {"ok": False, "error": "timeout"}
            pause(0.2)

    def _file_answer(self, ask: str, answer: dict[str, Any]) -> dict[str, Any]:
        """The answer of `send` is a file. Its bytes are read by the bridge from the page's request object (`responseBody`, a byte array, over COM)
        and come back as base64: never as text, so no byte is changed. Over 50 MB is not fetched. The file is only in memory here."""
        from rookie_agent.ie import files

        base = {"ok": True, "status": int(answer.get("status") or 0), "ms": int(answer.get("ms") or 0), "text": ""}
        length = int(answer.get("len") or 0)
        if length > files.MAX_BYTES:
            self.request({"cmd": "dropfile", "id": ask})
            return {"ok": False, "error": "too_big", "size": length}
        reply = self.request({"cmd": "fetchfile", "id": ask, "max": files.MAX_BYTES}, timeout=180)
        if reply.get("too_big"):
            return {"ok": False, "error": "too_big", "size": int(reply.get("size") or 0)}
        if not reply.get("found"):
            return {"ok": False, "error": "không lấy được nội dung file từ trang"}
        try:
            data = base64.b64decode(str(reply.get("b64") or ""), validate=True)
        except ValueError:
            return {"ok": False, "error": "nội dung file nhận về bị hỏng"}
        return {**base, "file": {"data": data, "ctype": str(answer.get("ctype") or ""), "disposition": str(answer.get("disp") or "")}}

    def last_requests(self, frame: str, path: str, timeout: float = 30.0) -> list[str]:
        """The last bodies (at most 3 per frame, oldest first) the live page sent to `path`, with passwords hidden. `frame` "" or "*":
        every frame; else the frame of that name. Nothing is stored by the agent; [] when the page was not watching."""
        bodies: list[str] = []
        for answer in self.frame_op("lastreq", [], path):
            if isinstance(answer, dict) and (frame in ("", "*") or answer.get("frame") == frame):
                bodies += [b for b in (answer.get("bodies") or []) if isinstance(b, str)]
        return bodies

    def live_urls(self, timeout: float = 30.0) -> list[str]:
        """The addresses with a query that the live page shows or used lately, in every frame (its own address, its links, its form actions,
        the requests it made): where a session value that rides in a query can be read. Memory only; [] when the page was not watching."""
        urls: list[str] = []
        for answer in self.frame_op("lasturls", [], ""):
            if isinstance(answer, dict):
                urls += [u for u in (answer.get("urls") or []) if isinstance(u, str)]
        return urls

    def read(self) -> list[str]:
        """What every frame being recorded shows now (tables, label-value pairs, messages), one JSON text per frame."""
        reply = self.request({"cmd": "read"}, timeout=30)
        return [text for text in (reply.get("reads") or []) if isinstance(text, str)]

    def poll(self) -> list[dict[str, Any]]:
        reply = self.request({"cmd": "poll"}, timeout=30)
        self.diag = reply.get("diag")  # which windows and frames the recorder reached; only set when it changed
        lines = reply.get("lines") or []
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
