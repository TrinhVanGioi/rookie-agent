"""Task 12.5 (SADPT, Delta Learning) on the teller's PC: «Dạy lại đoạn này» after a run stopped at a change; the server puts the part
in; the PC keeps it as a draft that a person approves; the version before can be brought back, approved again."""

from __future__ import annotations

import json

from test_webui import FakeServer, make_core

FLOW = {"schema_version": 4, "engine": "ie", "id": "tra-cuu", "version": 1, "status": "approved", "title": "Tra cứu",
        "inputs": [{"name": "acct", "type": "string"}],
        "steps": [{"id": "s1", "action": "fill", "value": "{acct}", "target": {"selectors": ["frame=work|id=a"]}, "risk": "read", "mode": "auto"},
                  {"id": "s2", "action": "click", "target": {"selectors": ["frame=work|id=b"], "label": "TRA CỨU"}, "risk": "read", "mode": "auto"}]}
ADDED = {"id": "d2_1_dong_y", "action": "click", "target": {"selectors": ["frame=work/dlg|id=btnOK"], "label": "ĐỒNG Ý"}, "risk": "write", "mode": "approve"}


class TeachServer(FakeServer):
    taught = []
    restored = []

    def post_session(self, session_id, engine, events, role=None, case_key=None):
        TeachServer.events = events

    def teach(self, workflow_id, version, after_step, session_id):
        TeachServer.taught.append((workflow_id, version, after_step, session_id))
        steps = FLOW["steps"][:2] + [ADDED]
        return {"workflow": {**FLOW, "version": 2, "status": "draft", "steps": steps}, "warnings": [],
                "change": {"op": "teach", "after": after_step, "added": [ADDED["id"]]}}

    def restore(self, workflow_id, version):
        TeachServer.restored.append((workflow_id, version))
        return {"workflow": {**FLOW, "version": 3, "status": "draft"}, "warnings": []}


def teach_core(tmp_path):
    core, _ = make_core(tmp_path, server_client=TeachServer)
    core.store.put("server_url", "http://server")
    core.store.put("flows", [{"title": "Tra cứu", "inputs": ["acct"], "steps": [], "warnings": [], "learned_at": "x", "workflow": json.loads(json.dumps(FLOW))}])
    core.store.save("t-1", [{"schema_version": 4, "engine": "ie", "session_id": "t-1", "seq": 0, "ts": "2026-11-20T09:00:00.000Z", "type": "click",
                             "url": "IE", "target": ADDED["target"] | {"tag": "button"}, "value": None, "value_class": None, "api_calls": [],
                             "shows": []}], "Dạy lại", engine="ie")
    return core


def test_the_part_taught_again_goes_to_the_server_and_comes_back_as_a_draft_waiting_for_approval(tmp_path):
    core = teach_core(tmp_path)
    made = core._teach_finish("Tra cứu", "s2", "t-1")
    assert TeachServer.taught[-1] == ("tra-cuu", 1, "s2", "t-1") and TeachServer.events[0]["schema_version"] == 4
    assert made["version"] == 2 and made["added"] == ["Bấm «ĐỒNG Ý»"]
    flow = core.store.get("flows")[0]
    assert flow["workflow"]["version"] == 1 and flow["workflow"]["status"] == "approved"           # the version in use does not change
    assert flow["repair"]["kind"] == "teach" and flow["repair"]["workflow"]["version"] == 2
    listed = core.dispatch("GET", "/api/flows", {})[1]["flows"][0]
    assert listed["repair_pending"] is True and listed["repair_version"] == 2
    assert listed["teach_steps"][1] == {"id": "s2", "label": "TRA CỨU"}
    audit = [json.loads(line) for line in (core.store.home / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert audit[-1]["mode"] == "teach" and audit[-1]["status"] == "waiting_approval" and audit[-1]["after"] == "s2"


def test_approving_the_draft_uses_it_and_keeps_the_one_before_which_can_come_back_approved_again(tmp_path):
    core = teach_core(tmp_path)
    core._teach_finish("Tra cứu", "s2", "t-1")
    assert core.dispatch("POST", "/api/flow/approve", {"title": "Tra cứu"})[0] == 200
    flow = core.store.get("flows")[0]
    assert flow["workflow"]["version"] == 2 and flow["workflow"]["status"] == "approved" and flow["previous"][-1]["version"] == 1
    status, reply = core.dispatch("POST", "/api/flow/restore", {"title": "Tra cứu"})
    assert status == 200 and reply["version"] == 3 and TeachServer.restored[-1] == ("tra-cuu", 1)
    flow = core.store.get("flows")[0]
    assert flow["workflow"]["version"] == 2 and flow["repair"]["kind"] == "restore" and flow["repair"]["workflow"]["status"] == "draft"


def test_teaching_needs_a_flow_on_the_server_and_a_step_to_start_after(tmp_path):
    core = teach_core(tmp_path)
    status, reply = core.dispatch("POST", "/api/teach/start", {"title": "Tra cứu", "window": "ie-tab:1"})
    assert status == 400 and "bước" in reply["error"]
    status, reply = core.dispatch("POST", "/api/teach/stop", {})
    assert status == 400
