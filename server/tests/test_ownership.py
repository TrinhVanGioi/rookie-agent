"""Task 10.2: whose flow it is, who sees it, sharing (only by its owner, after a preview) and cloning."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.identity import DevIdentity
from app.main import create_app
from tests.helpers import java_transfer_session, payload

USERS = [
    {"name": "gdv1", "password": "p1", "display": "GDV Một", "unit": "CN-HN", "roles": ["maker"]},
    {"name": "gdv2", "password": "p2", "display": "GDV Hai", "unit": "CN-HN", "roles": ["maker"]},
    {"name": "gdv3", "password": "p3", "display": "GDV Ba", "unit": "CN-HCM", "roles": ["maker"]},
    {"name": "quantri", "password": "pq", "display": "Quản trị", "unit": "HO", "roles": ["admin"]},
]


@pytest.fixture
def api(tmp_path):
    with TestClient(create_app(tmp_path / "own.db", auth_mode="dev", identity=DevIdentity(USERS))) as client:
        tokens = {}
        for user in USERS:
            reply = client.post("/auth/login", json={"username": user["name"], "password": user["password"]})
            tokens[user["name"]] = {"Authorization": "Bearer " + reply.json()["token"]}
        client.as_ = tokens
        yield client


def learn(api, who, title, prefix):
    ids = []
    for i in range(3):
        sid = f"{prefix}-{i}"
        assert api.post("/sessions", json=payload(sid, java_transfer_session(sid)), headers=api.as_[who]).status_code == 201
        ids.append(sid)
    reply = api.post("/workflows/learn", json={"title": title, "session_ids": ids}, headers=api.as_[who])
    assert reply.status_code == 201, reply.text
    return reply.json()["workflow"]["id"]


def seen(api, who):
    return {row["id"] for row in api.get("/workflows", headers=api.as_[who]).json()["workflows"]}


def test_the_owner_is_whoever_learned_it_and_others_do_not_see_it(api):
    flow = learn(api, "gdv1", "Chuyển tiền của An", "a")
    rows = api.get("/workflows", headers=api.as_["gdv1"]).json()["workflows"]
    assert rows[0]["owner"] == "gdv1" and rows[0]["owner_display"] == "GDV Một" and rows[0]["visibility"] == "private"
    assert flow not in seen(api, "gdv2") and flow in seen(api, "quantri")
    assert api.get(f"/workflows/{flow}", headers=api.as_["gdv2"]).status_code == 404       # not even that it exists
    assert api.post(f"/workflows/{flow}/versions/1/revise", json={"modes": {"x": "approve"}}, headers=api.as_["gdv2"]).status_code == 404


def test_recordings_are_read_only_by_whoever_made_them(api):
    learn(api, "gdv1", "Việc của An", "a")
    assert api.get("/sessions/a-0", headers=api.as_["gdv2"]).status_code == 404
    assert [s["session_id"] for s in api.get("/sessions", headers=api.as_["gdv2"]).json()["sessions"]] == []
    taken = api.post("/workflows/learn", json={"title": "Lấy bản ghi của An", "session_ids": ["a-0", "a-1"]}, headers=api.as_["gdv2"])
    assert taken.status_code == 404


def test_sharing_needs_the_preview_and_only_the_owner_can_share(api):
    flow = learn(api, "gdv1", "Chuyển tiền của An", "a")
    preview = api.get(f"/workflows/{flow}/share-preview", headers=api.as_["gdv1"]).json()
    assert preview["title"] == "Chuyển tiền của An" and preview["steps"] and preview["inputs"]
    assert all(set(step) <= {"label", "risk", "mode"} for step in preview["steps"])
    assert all(set(item) <= {"name", "label", "type"} for item in preview["inputs"])

    assert api.post(f"/workflows/{flow}/share", json={"visibility": "unit"}, headers=api.as_["gdv1"]).status_code == 422   # not confirmed
    assert api.post(f"/workflows/{flow}/share", json={"visibility": "unit", "confirm": True}, headers=api.as_["quantri"]).status_code == 403
    assert api.post(f"/workflows/{flow}/share", json={"visibility": "unit", "confirm": True}, headers=api.as_["gdv1"]).status_code == 200
    assert flow in seen(api, "gdv2") and flow not in seen(api, "gdv3")
    assert api.post(f"/workflows/{flow}/versions/1/revise", json={"modes": {"x": "approve"}}, headers=api.as_["gdv2"]).status_code == 403

    api.post(f"/workflows/{flow}/share", json={"visibility": "all", "confirm": True}, headers=api.as_["gdv1"])
    assert flow in seen(api, "gdv3")
    api.post(f"/workflows/{flow}/share", json={"visibility": "private", "confirm": True}, headers=api.as_["gdv1"])
    assert flow not in seen(api, "gdv2")


def test_a_clone_belongs_to_whoever_cloned_it_and_the_original_does_not_change(api):
    flow = learn(api, "gdv1", "Chuyển tiền của An", "a")
    api.post(f"/workflows/{flow}/share", json={"visibility": "unit", "confirm": True}, headers=api.as_["gdv1"])
    before = api.get(f"/workflows/{flow}", headers=api.as_["gdv1"]).json()
    reply = api.post(f"/workflows/{flow}/clone", json={"title": "Chuyển tiền của Hai"}, headers=api.as_["gdv2"])
    assert reply.status_code == 201
    copy = reply.json()["workflow"]
    assert copy["id"] != flow and copy["version"] == 1 and copy["status"] == "draft" and copy["title"] == "Chuyển tiền của Hai"
    assert copy["steps"] == before["workflow"]["steps"]
    row = next(r for r in api.get("/workflows", headers=api.as_["gdv2"]).json()["workflows"] if r["id"] == copy["id"])
    assert row["owner"] == "gdv2" and row["cloned_from"] == f"{flow}@1" and row["visibility"] == "private"
    assert api.get(f"/workflows/{flow}", headers=api.as_["gdv1"]).json() == before
    assert api.post(f"/workflows/{flow}/clone", json={}, headers=api.as_["gdv3"]).status_code == 404     # cannot see it, cannot clone it


def test_a_flow_from_before_owners_shows_no_owner_and_only_the_admin_gives_it_one(api):
    flow = learn(api, "gdv1", "Việc cũ", "a")
    api.app.state.storage.forget_owner(flow)          # as if it was learned before Gate 10
    row = next(r for r in api.get("/workflows", headers=api.as_["quantri"]).json()["workflows"] if r["id"] == flow)
    assert row["owner"] is None and row["owner_display"] == "Chưa rõ chủ"
    assert flow not in seen(api, "gdv1")
    give = {"owner": "gdv1", "owner_display": "GDV Một", "unit": "CN-HN"}
    assert api.post(f"/workflows/{flow}/owner", json=give, headers=api.as_["gdv1"]).status_code == 403
    assert api.post(f"/workflows/{flow}/owner", json=give, headers=api.as_["quantri"]).status_code == 200
    assert flow in seen(api, "gdv1")


def test_the_owner_or_an_admin_deletes_a_learned_flow_and_the_recordings_and_the_run_log_stay(api):
    flow = learn(api, "gdv1", "Chuyển tiền của An", "a")
    run = {"run_id": "r1", "time": "2026-11-20 10:00:00", "workflow_id": flow, "version": 1, "title": "Chuyển tiền của An",
           "mode": "screen", "status": "finished", "seconds": 4, "steps": [{"id": "s1", "status": "done"}]}
    assert api.post("/runs", json={"runs": [run]}, headers=api.as_["gdv1"]).status_code == 200
    assert api.post(f"/workflows/{flow}/delete", json={}, headers=api.as_["gdv1"]).status_code == 422
    api.post(f"/workflows/{flow}/share", json={"visibility": "unit", "confirm": True}, headers=api.as_["gdv1"])
    assert api.post(f"/workflows/{flow}/delete", json={"confirm": True}, headers=api.as_["gdv2"]).status_code == 403
    assert api.post(f"/workflows/{flow}/delete", json={"confirm": True}, headers=api.as_["gdv3"]).status_code == 404
    assert api.post(f"/workflows/{flow}/delete", json={"confirm": True}, headers=api.as_["gdv1"]).status_code == 200
    assert api.get(f"/workflows/{flow}", headers=api.as_["quantri"]).status_code == 404
    assert flow not in {row["id"] for row in api.get("/runs/summary", headers=api.as_["quantri"]).json()["flows"]}
    assert api.app.state.storage.runs_of(flow)[0]["run_id"] == "r1"
    assert len(api.get("/sessions", headers=api.as_["gdv1"]).json()["sessions"]) == 3
    other = learn(api, "gdv2", "Việc của Hai", "b")
    assert api.post(f"/workflows/{other}/delete", json={"confirm": True}, headers=api.as_["quantri"]).status_code == 200
    assert api.get(f"/workflows/{other}", headers=api.as_["gdv2"]).status_code == 404


def test_with_login_off_this_pc_owns_and_sees_everything_as_before(client):
    ids = []
    for i in range(3):
        client.post("/sessions", json=payload(f"s-{i}", java_transfer_session(f"s-{i}")))
        ids.append(f"s-{i}")
    flow = client.post("/workflows/learn", json={"title": "Việc", "session_ids": ids}).json()["workflow"]["id"]
    row = client.get("/workflows").json()["workflows"][0]
    assert row["id"] == flow and row["owner"] == "may-nay"
