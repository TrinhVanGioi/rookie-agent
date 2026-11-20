"""Task 12.5 (SADPT, Delta Learning): the teller teaches again only the part that changed; it is put into the flow between the steps
that still hold, as a new draft; the steps around it stay as they were. An older version can be brought back, as a new draft too."""

from __future__ import annotations

import json

import pytest

from app.delta import DeltaError, splice
from app.learner import learn
from tests.test_learner import ie_event, lookup_run, shown


def base_flow():
    workflow, _ = learn([lookup_run("a"), lookup_run("b")], "wf-lookup", title="Tra cứu tài khoản")
    return workflow


def segment(*events):
    return [dict(e, session_id="t", seq=i) for i, e in enumerate(events)]


CONFIRM = shown(ie_event(0, "click", "btnOK", "ĐỒNG Ý", session="t"), ("work", "table", "tblInfo"))


def test_the_new_part_goes_in_after_the_step_where_the_run_stopped_and_the_rest_stays_as_it_was():
    old = base_flow()
    new, change = splice(old, "s2_tra_cuu", [segment(CONFIRM)], version=2)
    assert [s["id"] for s in new["steps"]] == ["s1_so_tai_khoan", "s2_tra_cuu", "d2_1_dong_y", "s3_luu"]
    assert new["version"] == 2 and new["status"] == "draft" and new["schema_version"] == 4
    added = new["steps"][2]
    # a new confirmation no rule says is read-only is a write: it waits for Duyệt and is never found again by the agent itself
    assert added["intent"] == "ĐỒNG Ý" and (added["risk"], added["mode"]) == ("write", "approve") and added["adapt"] == {"reresolve": False}
    assert [s for s in new["steps"] if s["id"] != "d2_1_dong_y"] == old["steps"]          # every other step exactly as before
    assert change == {"op": "teach", "after": "s2_tra_cuu", "added": ["d2_1_dong_y"]}


def test_what_the_teller_did_again_after_the_new_part_is_the_old_flow_going_on_not_a_new_step():
    old = base_flow()
    again = shown(ie_event(1, "click", "btnSave", "LƯU", session="t"), ("work", "message", ""))
    new, change = splice(old, "s2_tra_cuu", [segment(CONFIRM, again)], version=2)
    assert [s["id"] for s in new["steps"]] == ["s1_so_tai_khoan", "s2_tra_cuu", "d2_1_dong_y", "s3_luu"] and change["added"] == ["d2_1_dong_y"]


def test_a_new_field_brings_its_input_and_a_new_money_step_is_never_automatic():
    old = base_flow()
    field = shown(ie_event(0, "input", "txtIdNo", "Số CCCD", value_class="id_number", session="t"))
    new, _ = splice(old, "s1_so_tai_khoan", [segment(field)], version=2)
    assert any(i.get("value_class") == "id_number" for i in new["inputs"]) and len(new["inputs"]) == len(old["inputs"]) + 1
    assert "0123456789" not in json.dumps(new)


def test_nothing_new_or_a_step_that_is_not_there_is_refused():
    old = base_flow()
    with pytest.raises(DeltaError):
        splice(old, "s9_khong_co", [segment(CONFIRM)], version=2)
    with pytest.raises(DeltaError):
        splice(old, "s2_tra_cuu", [segment(shown(ie_event(0, "click", "btnSave", "LƯU", session="t")))], version=2)


# ---- over HTTP: the draft is a version like any other, with who taught it; bringing an old version back --------------------------

def post_lookup(client, name):
    events = [{**e, "session_id": name} for e in lookup_run(name)]
    assert client.post("/sessions", json={"schema_version": 4, "engine": "ie", "session_id": name, "events": events}).status_code == 201


def test_teaching_a_part_makes_a_draft_the_base_keeps_and_an_old_version_comes_back_as_a_new_draft(client):
    for name in ("a", "b"):
        post_lookup(client, name)
    first = client.post("/workflows/learn", json={"title": "Tra cứu tài khoản", "session_ids": ["a", "b"]}).json()["workflow"]
    wid = first["id"]
    events = segment(CONFIRM)
    assert client.post("/sessions", json={"schema_version": 4, "engine": "ie", "session_id": "t", "events": events}).status_code == 201
    reply = client.post(f"/workflows/{wid}/versions/1/teach", json={"after_step": "s2_tra_cuu", "session_id": "t"})
    assert reply.status_code == 201, reply.text
    taught = reply.json()["workflow"]
    assert taught["version"] == 2 and taught["status"] == "draft" and len(taught["steps"]) == 4
    assert client.get(f"/workflows/{wid}/versions/1").json()["workflow"]["steps"] == first["steps"]     # version 1 unchanged
    edit = client.get(f"/workflows/{wid}/versions/2/edit").json()["edit"]
    assert edit["base_version"] == 1 and edit["ops"][0]["op"] == "teach"
    back = client.post(f"/workflows/{wid}/versions/1/restore", json={})
    assert back.status_code == 201, back.text
    restored = back.json()["workflow"]
    assert restored["version"] == 3 and restored["status"] == "draft" and restored["steps"] == first["steps"]
    assert client.get(f"/workflows/{wid}/versions/3/edit").json()["edit"]["ops"] == [{"op": "restore", "to": 1}]
    assert client.post(f"/workflows/{wid}/versions/1/teach", json={"after_step": "s2_tra_cuu", "session_id": "nope"}).status_code == 404
