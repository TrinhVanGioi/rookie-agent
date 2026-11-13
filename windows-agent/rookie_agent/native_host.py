"""Native Messaging host: the side panel of the extension drives the agent through this.

Wire format (Chrome/Edge Native Messaging): each message is a 4-byte length in
native byte order followed by UTF-8 JSON, on stdin and stdout. Nothing else may
be written to stdout.

Requests are `{"id": ..., "cmd": ...}`. Every reply echoes `id` and has `ok`.

    status          agent version, bitness, bridge state, Java windows, recording and running flags
    start           begin recording; optional "session_id"
    stop            end recording; returns the events (PII already removed)
    run             run an approved workflow: "server_url", "workflow_id", "inputs", optional "window"
    decide          answer the open question of a run: "approve": true or false
    emergency_stop  Dừng khẩn: stop the run at once
    snapshot        a drawing of the Java screen (structure only, no values) for the flow visualizer;
                    optional "window" (part of the title). Works while the window is minimized.

While a run is going the host also sends messages without a request id:
`{"event": "progress" | "waiting" | "finished", ...}`. Values the GDV typed are never in them.
"""

from __future__ import annotations

import json
import struct
import sys
import threading
from collections.abc import Callable
from typing import Any, BinaryIO, Protocol

from rookie_agent import __version__
from rookie_agent.controllers import RemoteController
from rookie_agent.recorder import Recorder

HOST_NAME = "com.rookie_agent.host"
MAX_MESSAGE_BYTES = 64 * 1024 * 1024  # limit the browser puts on messages to a host


class ProtocolError(Exception):
    """The byte stream is not a valid Native Messaging stream."""


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    """Read one message. Returns None when the browser closed the pipe."""
    header = stream.read(4)
    if len(header) == 0:
        return None
    if len(header) < 4:
        raise ProtocolError("Thiếu byte độ dài của thông điệp")
    (length,) = struct.unpack("=I", header)
    if length > MAX_MESSAGE_BYTES:
        raise ProtocolError(f"Thông điệp quá lớn: {length} byte")
    body = stream.read(length)
    if len(body) < length:
        raise ProtocolError("Thông điệp bị cắt giữa chừng")
    try:
        message = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError(f"Thông điệp không phải JSON hợp lệ: {error}") from error
    if not isinstance(message, dict):
        raise ProtocolError("Thông điệp phải là một object JSON")
    return message


def write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    stream.write(struct.pack("=I", len(body)))
    stream.write(body)
    stream.flush()


class Session(Protocol):
    """What the host needs from the Java Access Bridge thread."""

    def windows(self) -> list[tuple[int, str]]: ...
    def attach(self, recorder: Recorder) -> None: ...
    def detach(self) -> Recorder | None: ...
    def wait_for_window(self, title_part: str = "", timeout: float = 20.0) -> tuple[int, str]: ...
    def tree(self, hwnd: int, max_nodes: int = 5000) -> Any: ...


# (server_url, workflow_id) -> {"workflow": ..., "digest": ...}, already checked against its digest
Loader = Callable[[str, str], dict[str, Any]]
# (workflow, inputs, window title part, controller, stop event) -> run result
Executor = Callable[[dict[str, Any], dict[str, str], str, RemoteController, threading.Event], dict[str, Any]]


def default_loader(server_url: str, workflow_id: str) -> dict[str, Any]:
    from rookie_agent.server_client import ServerClient

    return ServerClient(server_url).approved_workflow(workflow_id)


class Host:
    """Command handling, separate from the pipes so it can be tested with fakes."""

    def __init__(
        self,
        session: Session | None,
        bridge_error: str | None = None,
        bits: int = 0,
        emit: Callable[[dict[str, Any]], None] | None = None,
        loader: Loader = default_loader,
        executor: Executor | None = None,
    ) -> None:
        self._session = session
        self._bridge_error = bridge_error
        self._bits = bits
        self._emit = emit or (lambda message: None)
        self._loader = loader
        self._executor = executor or self._execute_on_java
        self._recorder: Recorder | None = None
        self._run_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._controller: RemoteController | None = None

    def set_emitter(self, emit: Callable[[dict[str, Any]], None]) -> None:
        self._emit = emit

    @property
    def running(self) -> bool:
        return self._run_thread is not None and self._run_thread.is_alive()

    def wait_for_run(self, timeout: float | None = None) -> None:
        if self._run_thread is not None:
            self._run_thread.join(timeout)

    def handle(self, message: dict[str, Any]) -> dict[str, Any]:
        reply: dict[str, Any] = {"id": message.get("id")}
        command = message.get("cmd")
        handler = {
            "status": self._status,
            "start": self._start,
            "stop": self._stop_recording,
            "run": self._run,
            "decide": self._decide,
            "emergency_stop": self._emergency_stop,
            "snapshot": self._snapshot,
        }.get(command)
        if handler is None:
            return {**reply, "ok": False, "error": f"Lệnh không hỗ trợ: {command!r}"}
        try:
            return {**reply, "ok": True, **handler(message)}
        except Exception as error:
            return {**reply, "ok": False, "error": str(error)}

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError(self._bridge_error or "Java Access Bridge chưa sẵn sàng.")
        return self._session

    # ---- status and recording -------------------------------------------------------

    def _status(self, _: dict[str, Any]) -> dict[str, Any]:
        windows = [title for _, title in self._session.windows()] if self._session else []
        return {
            "agent_version": __version__,
            "bits": self._bits,
            "bridge": "ready" if self._session else "unavailable",
            "bridge_error": self._bridge_error,
            "java_windows": windows,
            "recording": self._recorder is not None,
            "session_id": self._recorder.session_id if self._recorder else None,
            "running": self.running,
            "waiting_for": self._controller.pending if self._controller else None,
        }

    def _start(self, message: dict[str, Any]) -> dict[str, Any]:
        session = self._require_session()
        if self.running:
            raise RuntimeError("Agent đang chạy workflow. Dừng trước khi ghi.")
        if self._recorder is not None:
            raise RuntimeError("Đang ghi. Bấm Dừng trước khi ghi phiên mới.")
        self._recorder = Recorder(session_id=message.get("session_id"))
        session.attach(self._recorder)
        return {"session_id": self._recorder.session_id}

    def _stop_recording(self, _: dict[str, Any]) -> dict[str, Any]:
        if self._recorder is None:
            raise RuntimeError("Chưa bắt đầu ghi.")
        self._require_session().detach()
        recorder, self._recorder = self._recorder, None
        return {"session_id": recorder.session_id, "engine": "java", "events": recorder.stop()}

    # ---- running a workflow ------------------------------------------------------------

    def _run(self, message: dict[str, Any]) -> dict[str, Any]:
        self._require_session()
        if self.running:
            raise RuntimeError("Đang chạy một workflow khác.")
        if self._recorder is not None:
            raise RuntimeError("Đang ghi. Bấm Dừng trước khi chạy.")
        server_url, workflow_id = message.get("server_url"), message.get("workflow_id")
        if not isinstance(server_url, str) or not isinstance(workflow_id, str):
            raise RuntimeError("Thiếu server_url hoặc workflow_id.")
        raw_inputs = message.get("inputs") or {}
        if not isinstance(raw_inputs, dict):
            raise RuntimeError("inputs phải là object.")
        inputs = {str(name): str(value) for name, value in raw_inputs.items()}
        reply = self._loader(server_url, workflow_id)  # fails here, before anything runs, if it is not approved
        workflow = reply["workflow"]

        self._stop = threading.Event()
        controller = self._controller = RemoteController(self._emit, self._stop)
        window = str(message.get("window") or "")

        def work() -> None:
            try:
                result = self._executor(workflow, inputs, window, controller, self._stop)
            except Exception as error:
                result = {"status": "failed", "message": str(error), "steps": []}
            self._emit({"event": "finished", "workflow_id": workflow["id"], "version": workflow["version"], **result})

        self._run_thread = threading.Thread(target=work, name="runner", daemon=True)
        self._run_thread.start()
        return {"workflow_id": workflow["id"], "version": workflow["version"], "steps": len(workflow["steps"])}

    def _execute_on_java(
        self,
        workflow: dict[str, Any],
        inputs: dict[str, str],
        window: str,
        controller: RemoteController,
        stop: threading.Event,
    ) -> dict[str, Any]:
        from rookie_agent.jab.driver import JabDriver
        from rookie_agent.runner import run_workflow

        session = self._require_session()
        hwnd, _ = session.wait_for_window(window, timeout=10)  # type: ignore[attr-defined]
        return run_workflow(workflow, inputs, JabDriver(session, hwnd), controller, stop)  # type: ignore[arg-type]

    def _decide(self, message: dict[str, Any]) -> dict[str, Any]:
        if self._controller is None or not self.running:
            raise RuntimeError("Không có bước nào đang chờ.")
        if not self._controller.decide(bool(message.get("approve"))):
            raise RuntimeError("Không có bước nào đang chờ.")
        return {}

    def _snapshot(self, message: dict[str, Any]) -> dict[str, Any]:
        from rookie_agent.wireframe import wireframe

        session = self._require_session()
        hwnd, _ = session.wait_for_window(str(message.get("window") or ""), timeout=2)
        return {"screen": wireframe(session.tree(hwnd))}

    def _emergency_stop(self, _: dict[str, Any]) -> dict[str, Any]:
        self._stop.set()
        return {"was_running": self.running}


class _LockedWriter:
    """Replies and unsolicited events come from different threads; one message at a time."""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def __call__(self, message: dict[str, Any]) -> None:
        with self._lock:
            write_message(self._stream, message)


def serve(host: Host, stdin: BinaryIO, stdout: BinaryIO) -> None:
    """Answer requests until the browser closes the pipe."""
    write = _LockedWriter(stdout)
    host.set_emitter(write)
    while True:
        try:
            message = read_message(stdin)
        except ProtocolError as error:
            write({"id": None, "ok": False, "error": str(error)})
            break
        if message is None:
            break
        write(host.handle(message))
    host._stop.set()  # the browser went away: a running workflow must not carry on alone
    host.wait_for_run(timeout=5)


def main() -> None:
    from rookie_agent.jab import bridge as jab
    from rookie_agent.jab.session import JabSession

    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    sys.stdout = sys.stderr  # stray prints must not corrupt the message stream
    session: JabSession | None = None
    bridge_error: str | None = None
    try:
        session = JabSession().open()
    except Exception as error:
        bridge_error = str(error)
    try:
        serve(Host(session, bridge_error, jab.BITS), stdin, stdout)
    finally:
        if session is not None:
            session.close()
