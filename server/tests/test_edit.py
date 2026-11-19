"""Task 10.4: editing a flow on the admin page. Every save is a new draft; the server checks every rule again."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.identity import DevIdentity
from app.main import create_app
from tests.helpers import java_transfer_session, payload
from tests.test_api_nodes import NODES


def learn(client, headers=None, with_api=True):
    ids = []
    for i in range(3):
        sid = f"s-{i}"
        client.post("/sessions", json=payload(sid, java_transfer_session(sid)), headers=headers)
        ids.append(sid)
    flow = client.post("/workflows/learn", json={"title": "Tra cứu", "session_ids": ids}, headers=headers).json()["workflow"]["id"]
    if with_api:
        assert client.put(f"/workflows/{flow}/versions/1/api", json={"api": NODES}, headers=headers).status_code == 200
    return flow


def edit(client, flow, *ops, version=1, headers=None):
    return client.post(f"/workflows/{flow}/versions/{version}/edit", json={"ops": list(ops)}, headers=headers)


def test_a_save_is_a_new_draft_and_the_base_version_does_not_change(client):
    flow = learn(client)
    before = client.get(f"/workflows/{flow}/versions/1").json()
    reply = edit(client, flow, {"op": "label", "node": "g2", "label": "Tìm khách"})
    assert reply.status_code == 201, reply.text
    new = reply.json()
    assert new["workflow"]["version"] == 2 and new["workflow"]["status"] == "draft"
    assert [n["group_label"] for n in new["api"] if n["group"] == "g2"] == ["Tìm khách"]
    assert new["api"][1]["label"] == "Tìm khách → POST /tp/rpc"
    assert client.get(f"/workflows/{flow}/versions/1").json() == before
    record = client.get(f"/workflows/{flow}/versions/2/edit").json()["edit"]
    assert record["base_version"] == 1 and record["edited_by"] == "may-nay" and record["ops"][0]["op"] == "label"


def test_risk_and_mode_only_go_up(client):
    flow = learn(client)
    assert edit(client, flow, {"op": "mode", "node": "g2", "mode": "approve"}).json()["api"][1]["mode"] == "approve"
    raised = edit(client, flow, {"op": "risk", "node": "g1", "risk": "write"}).json()
    assert raised["api"][0]["risk"] == "write" and raised["api"][0]["mode"] == "approve"
    lowered = edit(client, flow, {"op": "risk", "node": "g1", "risk": "read"}, version=3)
    assert lowered.status_code == 422 and "không được hạ" in lowered.json()["detail"]
    assert edit(client, flow, {"op": "mode", "node": "g1", "mode": "auto"}, version=3).status_code == 422


def test_a_step_flow_keeps_money_steps_under_approval(client):
    flow = learn(client, with_api=False)
    assert edit(client, flow, {"op": "mode", "node": "s8_gui_duyet", "mode": "auto"}).status_code == 422
    assert edit(client, flow, {"op": "risk", "node": "s8_gui_duyet", "risk": "read"}).status_code == 422
    reply = edit(client, flow, {"op": "risk", "node": "s2_tra_cuu_cif", "risk": "write"}).json()
    step = next(s for s in reply["workflow"]["steps"] if s["id"] == "s2_tra_cuu_cif")
    assert (step["risk"], step["mode"]) == ("write", "approve")


def test_a_new_node_gets_its_risk_from_the_rules_and_a_checker_step_is_never_added(client):
    flow = learn(client)
    read = edit(client, flow, {"op": "add_http", "after": "g2", "label": "Tra cứu lịch sử", "method": "GET", "url": "http://tp.local/tp/history?cif=⟦so_cif_hoac_cccd⟧"}).json()
    added = read["api"][-1]
    assert (added["id"], added["group"], added["risk"], added["mode"], added["added"]) == ("n1", "g3", "read", "auto", True)
    money = edit(client, flow, {"op": "add_http", "after": "g2", "label": "Tra cứu", "method": "POST", "url": "http://tp.local/api/Chuyen-Tien/tao"}).json()
    assert money["api"][-1]["risk"] == "money" and money["api"][-1]["mode"] == "approve"
    unknown = edit(client, flow, {"op": "add_http", "after": "g2", "label": "Xử lý", "method": "POST", "url": "http://tp.local/tp/x"}).json()
    assert unknown["api"][-1]["risk"] == "write"
    checker = edit(client, flow, {"op": "add_http", "after": "g2", "label": "Duyệt", "method": "POST", "url": "http://tp.local/api/transfers/1/approve"})
    assert checker.status_code == 422 and "do người bấm" in checker.json()["detail"]


def test_a_new_node_lists_the_names_it_does_not_know(client):
    flow = learn(client)
    added = edit(client, flow, {"op": "add_http", "after": None, "label": "Xem", "method": "GET", "url": "http://tp.local/tp/x?a=⟦khong_co⟧&b=⟦so_cif_hoac_cccd⟧"}).json()["api"][0]
    assert added["unresolved"] == ["khong_co"]


def test_a_template_with_data_is_refused(client):
    flow = learn(client)
    reply = edit(client, flow, {"op": "add_http", "after": "g2", "label": "Xem", "method": "GET", "url": "http://tp.local/tp/x?cif=0012345678"})
    assert reply.status_code == 422 and "giống dữ liệu" in reply.json()["detail"]


def test_deleting_a_node_another_takes_data_from_is_refused_with_the_name_of_that_node(client):
    flow = learn(client)
    refused = edit(client, flow, {"op": "delete", "node": "g1"})
    assert refused.status_code == 422 and "Tra cứu" in refused.json()["detail"]
    assert [n["id"] for n in edit(client, flow, {"op": "delete", "node": "g2"}).json()["api"]] == ["a1"]


def test_a_node_cannot_be_put_before_the_node_it_takes_data_from(client):
    flow = learn(client)
    refused = edit(client, flow, {"op": "reorder", "order": ["g2", "g1"]})
    assert refused.status_code == 422 and "phải đứng sau" in refused.json()["detail"]
    added = edit(client, flow, {"op": "add_http", "after": "g2", "label": "Xem", "method": "GET", "url": "http://tp.local/tp/x"}).json()
    moved = edit(client, flow, {"op": "reorder", "order": ["g3", "g1", "g2"]}, version=added["workflow"]["version"]).json()
    assert [n["group"] for n in moved["api"]] == ["g3", "g1", "g2"]


def test_the_template_of_a_node_masked_on_the_pc_cannot_be_edited_but_its_label_and_an_added_node_can(client):
    flow = learn(client)
    refused = edit(client, flow, {"op": "edit_http", "node": "a2", "body": "x"})
    assert refused.status_code == 422 and "chỉ nằm trên máy đó" in refused.json()["detail"]
    assert edit(client, flow, {"op": "edit_http", "node": "a1", "url": "http://tp.local/tp/token2"}).status_code == 201
    v3 = edit(client, flow, {"op": "add_http", "after": "g2", "label": "Xem", "method": "GET", "url": "http://tp.local/tp/x"}).json()
    changed = edit(client, flow, {"op": "edit_http", "node": "n1", "method": "post", "url": "http://tp.local/tp/x/save"}, version=v3["workflow"]["version"]).json()
    node = next(n for n in changed["api"] if n["id"] == "n1")
    assert (node["method"], node["risk"], node["mode"]) == ("POST", "write", "approve")


def test_the_layout_is_kept_per_flow_and_is_not_a_new_version(client):
    flow = learn(client)
    assert client.put(f"/workflows/{flow}/layout", json={"layout": {"g1": [10, 20], "g2": [200, 20]}}).status_code == 200
    assert client.get(f"/workflows/{flow}/layout").json()["layout"] == {"g1": [10, 20], "g2": [200, 20]}
    assert [r["version"] for r in client.get("/workflows").json()["workflows"]] == [1]


def test_an_unknown_operation_is_refused(client):
    flow = learn(client)
    assert edit(client, flow, {"op": "run"}).status_code == 422


USERS = [
    {"name": "gdv1", "password": "p1", "display": "GDV Một", "unit": "CN-HN", "roles": ["maker"]},
    {"name": "quantri", "password": "pq", "display": "Quản trị", "unit": "HO", "roles": ["admin"]},
    {"name": "quantri2", "password": "pq2", "display": "Quản trị 2", "unit": "HO", "roles": ["admin"]},
]


@pytest.fixture
def people(tmp_path):
    with TestClient(create_app(tmp_path / "edit.db", auth_mode="dev", identity=DevIdentity(USERS))) as client:
        client.as_ = {u["name"]: {"Authorization": "Bearer " + client.post("/auth/login", json={"username": u["name"], "password": u["password"]}).json()["token"]}
                      for u in USERS}
        yield client


def test_whoever_edited_a_version_cannot_approve_it(people):
    flow = learn(people, headers=people.as_["gdv1"])
    v2 = edit(people, flow, {"op": "label", "node": "g2", "label": "Tìm"}, headers=people.as_["quantri"]).json()["workflow"]["version"]
    for who in ("gdv1",):
        people.post(f"/workflows/{flow}/versions/{v2}/test-runs", json={"status": "finished"}, headers=people.as_[who])
        assert people.post(f"/workflows/{flow}/versions/{v2}/status", json={"status": "tested"}, headers=people.as_[who]).status_code == 200
    refused = people.post(f"/workflows/{flow}/versions/{v2}/status", json={"status": "approved"}, headers=people.as_["quantri"])
    assert refused.status_code == 409 and "không tự duyệt" in refused.json()["detail"]
    assert people.post(f"/workflows/{flow}/versions/{v2}/status", json={"status": "approved"}, headers=people.as_["gdv1"]).status_code == 200
