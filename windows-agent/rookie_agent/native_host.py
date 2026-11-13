"""Native Messaging host: the side panel of the extension drives the agent through this.

Wire format (Chrome/Edge Native Messaging): each message is a 4-byte length in
native byte order followed by UTF-8 JSON, on stdin and stdout. Nothing else may
be written to stdout.

Requests are `{"id": ..., "cmd": ...}`. Every reply echoes `id` and has `ok`.

    status   -> agent version, bitness, bridge state, Java windows, recording flag
    start    -> begin recording; optional "session_id"
    stop     -> end recording; returns the events (PII already removed)
"""

from __future__ import annotations

import json
import struct
import sys
from typing import Any, BinaryIO, Protocol

from rookie_agent import __version__
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


class Host:
    """Command handling, separate from the pipes so it can be tested with a fake session."""

    def __init__(self, session: Session | None, bridge_error: str | None = None, bits: int = 0) -> None:
        self._session = session
        self._bridge_error = bridge_error
        self._bits = bits
        self._recorder: Recorder | None = None

    def handle(self, message: dict[str, Any]) -> dict[str, Any]:
        reply: dict[str, Any] = {"id": message.get("id")}
        command = message.get("cmd")
        handler = {"status": self._status, "start": self._start, "stop": self._stop}.get(command)
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
        }

    def _start(self, message: dict[str, Any]) -> dict[str, Any]:
        session = self._require_session()
        if self._recorder is not None:
            raise RuntimeError("Đang ghi. Bấm Dừng trước khi ghi phiên mới.")
        self._recorder = Recorder(session_id=message.get("session_id"))
        session.attach(self._recorder)
        return {"session_id": self._recorder.session_id}

    def _stop(self, _: dict[str, Any]) -> dict[str, Any]:
        if self._recorder is None:
            raise RuntimeError("Chưa bắt đầu ghi.")
        self._require_session().detach()
        recorder, self._recorder = self._recorder, None
        return {"session_id": recorder.session_id, "engine": "java", "events": recorder.stop()}


def serve(host: Host, stdin: BinaryIO, stdout: BinaryIO) -> None:
    """Answer requests until the browser closes the pipe."""
    while True:
        try:
            message = read_message(stdin)
        except ProtocolError as error:
            write_message(stdout, {"id": None, "ok": False, "error": str(error)})
            return
        if message is None:
            return
        write_message(stdout, host.handle(message))


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
