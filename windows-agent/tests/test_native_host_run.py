import io
import threading
import time

import pytest

from rookie_agent.native_host import Host, serve
from rookie_agent.runner import AutoController, run_workflow

WORKFLOW = {
    "schema_version": 1,
    "engine": "java",
    "id": "chuyen-tien",
    "version": 2,
    "status": "approved",
    "inputs": [{"name": "so_tien", "type": "string", "value_class": "amount"}],
    "steps": [
        {"id": "s1", "action": "fill", "target": {"selectors": ["role=text[name='Số tiền']"], "label": "Số tiền"}, "value": "{so_tien}", "risk": "read", "mode": "auto"},
        {"id": "s2", "action": "click", "target": {"selectors": ["role=push button[name='Gửi duyệt']"], "label": "Gửi duyệt"}, "risk": "money", "mode": "approve"},
    ],
}


class FakeSession:
    def windows(self):
        return [(1, "Mock TPSS - Chuyển tiền")]

    def attach(self, recorder):
        pass

    def detach(self):
        return None


class Driver:
    def __init__(self):
        self.calls = []

    def window_title(self):
        return "Mock TPSS - Chuyển tiền"

    def exists(self, selectors):
        return True

    def click(self, selectors):
        self.calls.append("click")

    def fill(self, selectors, value):
        self.calls.append("fill")

    def select(self, selectors, value):
        pass

    def read_value(self, selectors):
        return ""


def make_host(events, driver=None):
    driver = driver or Driver()

    def loader(server_url, workflow_id):
        if workflow_id != "chuyen-tien":
            raise RuntimeError("Máy chủ từ chối (404): Workflow chưa có bản nào được duyệt")
        return {"workflow": WORKFLOW, "digest": "x"}

    def executor(workflow, inputs, window, controller, stop):
        return run_workflow(workflow, inputs, driver, controller, stop, settle=0, sleep=lambda s: None)

    host = Host(FakeSession(), bits=64, emit=events.append, loader=loader, executor=executor)
    return host, driver


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("hết thời gian chờ")


def start(host):
    return host.handle({"id": 1, "cmd": "run", "server_url": "http://s", "workflow_id": "chuyen-tien", "inputs": {"so_tien": "5000000"}})


def test_run_asks_for_approval_then_finishes_after_the_panel_answers():
    events = []
    host, driver = make_host(events)
    reply = start(host)
    assert reply["ok"] and reply["version"] == 2 and reply["steps"] == 2

    wait_for(lambda: host.handle({"cmd": "status"})["waiting_for"] == "approve")
    waiting = next(e for e in events if e["event"] == "waiting")
    assert (waiting["kind"], waiting["step_id"], waiting["label"], waiting["risk"]) == ("approve", "s2", "Gửi duyệt", "money")
    assert driver.calls == ["fill"]  # the money click has not happened

    assert host.handle({"cmd": "decide", "approve": True})["ok"]
    host.wait_for_run(3)
    finished = events[-1]
    assert finished["event"] == "finished" and finished["status"] == "finished" and finished["version"] == 2
    assert driver.calls == ["fill", "click"]


def test_panel_can_refuse_approval():
    events = []
    host, driver = make_host(events)
    start(host)
    wait_for(lambda: host.handle({"cmd": "status"})["waiting_for"] == "approve")
    host.handle({"cmd": "decide", "approve": False})
    host.wait_for_run(3)
    assert events[-1]["status"] == "rejected" and driver.calls == ["fill"]


def test_emergency_stop_ends_the_run_even_while_waiting_for_approval():
    events = []
    host, driver = make_host(events)
    start(host)
    wait_for(lambda: host.handle({"cmd": "status"})["waiting_for"] == "approve")
    assert host.handle({"cmd": "emergency_stop"})["ok"]
    host.wait_for_run(3)
    assert events[-1]["status"] == "stopped" and driver.calls == ["fill"]


def test_workflow_the_server_will_not_serve_is_not_run():
    events = []
    host, driver = make_host(events)
    reply = host.handle({"cmd": "run", "server_url": "http://s", "workflow_id": "chua-duyet", "inputs": {}})
    assert not reply["ok"] and "chưa có bản nào được duyệt" in reply["error"]
    assert events == [] and not host.running


def test_only_one_run_at_a_time_and_no_recording_during_a_run():
    events = []
    host, _ = make_host(events)
    start(host)
    wait_for(lambda: host.handle({"cmd": "status"})["waiting_for"] == "approve")
    assert not start(host)["ok"]
    assert not host.handle({"cmd": "start"})["ok"]
    host.handle({"cmd": "emergency_stop"})
    host.wait_for_run(3)


def test_decide_without_an_open_question_is_an_error():
    host, _ = make_host([])
    assert not host.handle({"cmd": "decide", "approve": True})["ok"]


def test_missing_arguments_are_reported():
    host, _ = make_host([])
    assert not host.handle({"cmd": "run", "inputs": {}})["ok"]
    assert not host.handle({"cmd": "run", "server_url": "u", "workflow_id": "w", "inputs": [1]})["ok"]


def test_executor_crash_is_reported_as_failed():
    events = []

    def boom(*args):
        raise RuntimeError("không thấy cửa sổ Java")

    host = Host(FakeSession(), emit=events.append, loader=lambda u, w: {"workflow": WORKFLOW, "digest": "x"}, executor=boom)
    start(host)
    host.wait_for_run(3)
    assert events[-1]["status"] == "failed" and "cửa sổ Java" in events[-1]["message"]


def test_pipe_closing_stops_a_run_that_is_waiting(monkeypatch):
    import struct

    events = []
    host, driver = make_host(events)
    request = b'{"id":1,"cmd":"run","server_url":"http://s","workflow_id":"chuyen-tien","inputs":{"so_tien":"1"}}'
    stdin = io.BytesIO(struct.pack("=I", len(request)) + request)
    stdout = io.BytesIO()

    def close_when_waiting():
        pass

    serve(host, stdin, stdout)  # reads the run request, then the pipe closes
    assert not host.running
    assert driver.calls in ([], ["fill"])  # never reached the money click


def test_input_values_never_appear_in_messages():
    events = []
    host, _ = make_host(events)
    start(host)
    wait_for(lambda: host.handle({"cmd": "status"})["waiting_for"] == "approve")
    host.handle({"cmd": "decide", "approve": True})
    host.wait_for_run(3)
    assert "5000000" not in repr(events)


def test_sandbox_command_runs_in_the_background_and_reports_when_finished():
    events = []
    calls = []

    def sandboxer(server_url, workflow_id, version, inputs, session):
        calls.append((server_url, workflow_id, version, inputs))
        return {"status": "finished", "message": "ok", "steps": []}

    host = Host(FakeSession(), emit=events.append, sandboxer=sandboxer)
    reply = host.handle({"id": 4, "cmd": "sandbox", "server_url": "http://s", "workflow_id": "chuyen-tien", "version": 1, "inputs": {"so_tien": "1000"}})
    assert reply["ok"] and reply["version"] == 1
    host.wait_for_run(3)
    assert calls == [("http://s", "chuyen-tien", 1, {"so_tien": "1000"})]
    assert events[-1] == {"event": "finished", "sandbox": True, "workflow_id": "chuyen-tien", "version": 1, "status": "finished", "message": "ok", "steps": []}


def test_sandbox_failure_is_reported_and_bad_arguments_refused():
    events = []

    def boom(*args):
        raise RuntimeError("Chưa có mock Swing")

    host = Host(FakeSession(), emit=events.append, sandboxer=boom)
    assert not host.handle({"cmd": "sandbox", "server_url": "u", "workflow_id": "w"})["ok"]  # no version
    assert host.handle({"cmd": "sandbox", "server_url": "u", "workflow_id": "w", "version": 1})["ok"]
    host.wait_for_run(3)
    assert events[-1]["status"] == "failed" and "mock Swing" in events[-1]["message"]
