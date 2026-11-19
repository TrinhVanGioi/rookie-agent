"""Task 10.5, the agent's side: each run's audit line goes up to the server (names and states only); a failed send is kept for later."""

from __future__ import annotations

import json
import threading

from rookie_agent.server_client import ServerError


def make_core(*a, **k):
    from test_webui import make_core as real    # sibling module (tests/ has no package: the server has one named `tests`)
    return real(*a, **k)


class Server:
    sent: list = []
    down = False

    def __init__(self, url):
        self.url = url

    def post_runs(self, runs):
        if Server.down:
            raise ServerError("Không kết nối được máy chủ")
        Server.sent.append(runs)
        return {"kept": len(runs), "known": 0, "skipped": 0}


class Controller:
    decisions = [{"step_id": "g2", "kind": "approve", "risk": "write", "approved": True}]
    steps = [{"id": "g1", "status": "done", "detail": "Đã gửi 0123456789"}, {"id": "g2", "status": "done", "detail": "NGUYEN VAN AN"}]


def run_once(core, title="Tra cứu"):
    state = {"title": title, "mode": "simulate", "controller": Controller(), "started": 0, "via": "assistant", "input_names": ["so_cif"]}
    core._audit(state, {"status": "finished"})


def test_a_run_goes_up_once_with_its_flow_and_version_and_without_any_detail_text(tmp_path):
    Server.sent, Server.down = [], False
    core, _ = make_core(tmp_path, server_client=Server)
    core.store.put("flows", [{"title": "Tra cứu", "workflow": {"id": "tra-cuu", "version": 3}}])
    run_once(core)
    (runs,) = Server.sent
    (run,) = runs
    assert (run["workflow_id"], run["version"], run["status"], run["mode"]) == ("tra-cuu", 3, "finished", "simulate")
    assert run["steps"] == [{"id": "g1", "status": "done"}, {"id": "g2", "status": "done"}]
    assert run["decisions"] == Controller.decisions and run["input_names"] == ["so_cif"] and run["run_id"]
    text = json.dumps(Server.sent, ensure_ascii=False)
    assert "0123456789" not in text and "NGUYEN" not in text
    core._send_runs()
    assert len(Server.sent) == 1            # nothing new: nothing sent again


def test_a_run_that_could_not_go_up_goes_with_the_next_one(tmp_path):
    Server.sent, Server.down = [], True
    core, _ = make_core(tmp_path, server_client=Server)
    core.store.put("flows", [{"title": "Tra cứu", "workflow": {"id": "tra-cuu", "version": 3}}])
    run_once(core)
    assert Server.sent == []
    Server.down = False
    run_once(core)
    assert [len(batch) for batch in Server.sent] == [2]
    assert (tmp_path / "audit.jsonl").read_text(encoding="utf-8").count(chr(10)) == 2      # the log on this PC is unchanged


def test_a_run_of_a_flow_learned_without_the_server_stays_on_this_pc(tmp_path):
    Server.sent, Server.down = [], False
    core, _ = make_core(tmp_path, server_client=Server)
    run_once(core, title="Không có trên máy chủ")
    assert Server.sent == []


def test_a_server_without_runs_does_not_stop_a_run(tmp_path):
    core, _ = make_core(tmp_path)        # the plain fake server has no post_runs
    core.store.put("flows", [{"title": "Tra cứu", "workflow": {"id": "tra-cuu", "version": 3}}])
    run_once(core)
    assert "tra-cuu" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
