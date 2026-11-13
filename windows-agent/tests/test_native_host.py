import io
import json
import struct

import pytest

from rookie_agent.native_host import Host, ProtocolError, read_message, serve, write_message
from rookie_agent.recorder import Recorder
from rookie_agent.selectors import Element, Step


def frame(message) -> bytes:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    return struct.pack("=I", len(body)) + body


def unframe(data: bytes) -> list[dict]:
    stream = io.BytesIO(data)
    messages = []
    while (message := read_message(stream)) is not None:
        messages.append(message)
    return messages


class FakeSession:
    def __init__(self):
        self.recorder: Recorder | None = None

    def windows(self):
        return [(1, "Mock TPSS - Chuyển tiền")]

    def attach(self, recorder):
        self.recorder = recorder

    def detach(self):
        recorder, self.recorder = self.recorder, None
        return recorder


# ---- framing ----------------------------------------------------------------------


def test_write_then_read_round_trips_unicode():
    stream = io.BytesIO()
    write_message(stream, {"cmd": "status", "note": "Dừng khẩn"})
    stream.seek(0)
    assert read_message(stream) == {"cmd": "status", "note": "Dừng khẩn"}
    assert read_message(stream) is None  # pipe closed


def test_length_prefix_counts_bytes_not_characters():
    stream = io.BytesIO()
    write_message(stream, {"t": "Học"})
    data = stream.getvalue()
    assert struct.unpack("=I", data[:4])[0] == len(data) - 4


@pytest.mark.parametrize(
    "data",
    [
        b"\x01\x00",  # short header
        struct.pack("=I", 10) + b"{}",  # truncated body
        struct.pack("=I", 3) + b"abc",  # not JSON
        struct.pack("=I", 2) + b"[]",  # not an object
        struct.pack("=I", 2**31),  # absurd length
    ],
)
def test_bad_streams_raise_protocol_error(data):
    with pytest.raises(ProtocolError):
        read_message(io.BytesIO(data))


# ---- commands ---------------------------------------------------------------------


def test_status_reports_bridge_and_windows():
    reply = Host(FakeSession(), bits=64).handle({"id": 1, "cmd": "status"})
    assert reply["ok"] and reply["id"] == 1
    assert reply["bridge"] == "ready"
    assert reply["java_windows"] == ["Mock TPSS - Chuyển tiền"]
    assert reply["recording"] is False and reply["bits"] == 64


def test_status_explains_a_missing_bridge_and_start_fails():
    host = Host(None, bridge_error="Không tìm thấy WindowsAccessBridge-64.dll")
    status = host.handle({"id": 1, "cmd": "status"})
    assert status["ok"] and status["bridge"] == "unavailable"
    assert "WindowsAccessBridge" in status["bridge_error"]
    start = host.handle({"id": 2, "cmd": "start"})
    assert not start["ok"] and "WindowsAccessBridge" in start["error"]


def test_start_record_stop_returns_events(assert_valid_events):
    session = FakeSession()
    host = Host(session)
    started = host.handle({"id": 1, "cmd": "start", "session_id": "s-abc"})
    assert started["ok"] and started["session_id"] == "s-abc"
    assert host.handle({"cmd": "status"})["recording"] is True

    button = Element("push button", "Tải lại", (Step("frame", -1), Step("push button", 0)), "Mock TPSS")
    session.recorder.clicked(button)

    stopped = host.handle({"id": 2, "cmd": "stop"})
    assert stopped["ok"] and stopped["engine"] == "java" and stopped["session_id"] == "s-abc"
    assert_valid_events(stopped["events"])
    assert len(stopped["events"]) == 1
    assert session.recorder is None
    assert host.handle({"cmd": "status"})["recording"] is False


def test_double_start_and_stop_without_start_are_errors():
    host = Host(FakeSession())
    assert not host.handle({"cmd": "stop"})["ok"]
    assert host.handle({"cmd": "start"})["ok"]
    assert not host.handle({"cmd": "start"})["ok"]


def test_unknown_command_is_an_error():
    reply = Host(FakeSession()).handle({"id": 7, "cmd": "format_disk"})
    assert reply == {"id": 7, "ok": False, "error": "Lệnh không hỗ trợ: 'format_disk'"}


def test_serve_answers_each_request_until_the_pipe_closes():
    stdin = io.BytesIO(frame({"id": 1, "cmd": "status"}) + frame({"id": 2, "cmd": "nope"}))
    stdout = io.BytesIO()
    serve(Host(FakeSession()), stdin, stdout)
    replies = unframe(stdout.getvalue())
    assert [(r["id"], r["ok"]) for r in replies] == [(1, True), (2, False)]


def test_serve_reports_a_corrupt_stream_and_stops():
    stdout = io.BytesIO()
    serve(Host(FakeSession()), io.BytesIO(struct.pack("=I", 3) + b"abc"), stdout)
    replies = unframe(stdout.getvalue())
    assert len(replies) == 1 and replies[0]["ok"] is False
