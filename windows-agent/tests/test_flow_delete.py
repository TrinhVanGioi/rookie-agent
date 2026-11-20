"""A learned flow can be deleted from this PC. The copy on the server goes too when this PC is allowed to remove it."""

from __future__ import annotations

import threading

from rookie_agent.server_client import ServerError
from test_webui import make_core


FLOW = {"schema_version": 4, "engine": "ie", "id": "tra-cuu", "version": 1, "status": "approved", "title": "Tra cứu",
        "inputs": [], "steps": [{"id": "s1", "action": "click", "target": {"selectors": ["frame=work|id=a"]}, "risk": "read", "mode": "auto"}]}


class DeleteServer:
    deleted = []
    status = None

    def __init__(self, url):
        self.url = url

    def delete_workflow(self, workflow_id):
        if DeleteServer.status:
            raise ServerError("từ chối", DeleteServer.status)
        DeleteServer.deleted.append(workflow_id)
        return {"deleted": workflow_id}


def core_with(tmp_path, workflow=FLOW):
    DeleteServer.deleted = []
    DeleteServer.status = None
    core, _ = make_core(tmp_path, server_client=DeleteServer)
    core.store.put("server_url", "http://server")
    core.store.put("flows", [{"title": "Tra cứu", "inputs": [], "steps": [], "warnings": [], "learned_at": "x", "workflow": workflow}])
    core.store.save("rec-1", [{"schema_version": 2, "engine": "ie", "session_id": "rec-1", "seq": 0, "ts": "2026-11-20T09:00:00.000Z",
                               "type": "click", "url": "IE", "target": {"selectors": ["frame=work|id=a"], "tag": "button"},
                               "value": None, "value_class": None, "api_calls": []}], "Lần 1", engine="ie")
    return core


def test_deleting_a_learned_flow_removes_it_here_and_on_the_server_and_keeps_the_recording(tmp_path):
    core = core_with(tmp_path)
    status, reply = core.dispatch("POST", "/api/flow/delete", {"title": "Tra cứu"})
    assert status == 200 and reply["deleted"] == "Tra cứu" and reply["server"] == ""
    assert DeleteServer.deleted == ["tra-cuu"]
    assert core.store.get("flows") == []
    assert core.store.listing()[0]["id"] == "rec-1"


def test_a_flow_the_server_refuses_still_leaves_this_pc(tmp_path):
    core = core_with(tmp_path)
    DeleteServer.status = 403
    status, reply = core.dispatch("POST", "/api/flow/delete", {"title": "Tra cứu"})
    assert status == 200 and "máy chủ vẫn còn" in reply["server"]
    assert core.store.get("flows") == []


def test_a_flow_already_gone_on_the_server_is_still_removed_here(tmp_path):
    core = core_with(tmp_path)
    DeleteServer.status = 404
    status, reply = core.dispatch("POST", "/api/flow/delete", {"title": "Tra cứu"})
    assert status == 200 and reply["server"] == "" and core.store.get("flows") == []


def test_the_flow_on_this_pc_goes_even_when_the_server_cannot_be_reached(tmp_path):
    class Down(DeleteServer):
        def delete_workflow(self, workflow_id):
            raise ServerError("Không kết nối được máy chủ")

    core, _ = make_core(tmp_path, server_client=Down)
    core.store.put("server_url", "http://server")
    core.store.put("flows", [{"title": "Tra cứu", "inputs": [], "steps": [], "warnings": [], "learned_at": "x", "workflow": FLOW}])
    status, reply = core.dispatch("POST", "/api/flow/delete", {"title": "Tra cứu"})
    assert status == 200 and core.store.get("flows") == [] and "máy này" in reply["server"]


def test_a_flow_that_is_running_is_not_deleted(tmp_path):
    core = core_with(tmp_path)
    hold = threading.Event()
    thread = threading.Thread(target=hold.wait, args=(2,))
    thread.start()
    core._run = {"title": "Tra cứu", "thread": thread}
    status, reply = core.dispatch("POST", "/api/flow/delete", {"title": "Tra cứu"})
    hold.set()
    thread.join()
    assert status == 400 and "Dừng khẩn" in reply["error"]
    assert core.store.get("flows")[0]["title"] == "Tra cứu"
