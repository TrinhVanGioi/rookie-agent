"""Task 10.5: the runs of a flow, sent up by the PCs that ran it. Names and states only, never a value; who ran it is the login."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.identity import DevIdentity
from app.main import create_app
from tests.helpers import java_transfer_session, payload

USERS = [
    {"name": "gdv1", "password": "p1", "display": "GDV Một", "unit": "CN-HN", "roles": ["maker"]},
    {"name": "gdv2", "password": "p2", "display": "GDV Hai", "unit": "CN-HCM", "roles": ["maker"]},
    {"name": "quantri", "password": "pq", "display": "Quản trị", "unit": "HO", "roles": ["admin"]},
]


@pytest.fixture
def api(tmp_path):
    with TestClient(create_app(tmp_path / "runs.db", auth_mode="dev", identity=DevIdentity(USERS))) as client:
        client.as_ = {u["name"]: {"Authorization": "Bearer " + client.post("/auth/login", json={"username": u["name"], "password": u["password"]}).json()["token"]}
                      for u in USERS}
        ids = []
        for i in range(3):
            client.post("/sessions", json=payload(f"s-{i}", java_transfer_session(f"s-{i}")), headers=client.as_["gdv1"])
            ids.append(f"s-{i}")
        client.flow = client.post("/workflows/learn", json={"title": "Tra cứu", "session_ids": ids}, headers=client.as_["gdv1"]).json()["workflow"]["id"]
        yield client


def run(flow, run_id="r1", status="finished", **extra):
    return {"run_id": run_id, "time": "2026-11-19 10:00:00", "workflow_id": flow, "version": 1, "title": "Tra cứu", "mode": "simulate",
            "status": status, "seconds": 3.5, "steps": [{"id": "g1", "status": "done"}, {"id": "g2", "status": "done"}],
            "decisions": [{"step_id": "g2", "kind": "approve", "risk": "write", "approved": True}], "input_names": ["so_cif"], **extra}


def test_a_run_is_kept_once_with_who_ran_it_from_the_login(api):
    for _ in range(2):        # sent again after a lost answer: kept once
        reply = api.post("/runs", json={"runs": [run(api.flow)]}, headers=api.as_["gdv1"])
        assert reply.status_code == 200
    assert reply.json() == {"kept": 0, "known": 1, "skipped": 0}
    runs = api.get(f"/workflows/{api.flow}/runs", headers=api.as_["gdv1"]).json()["runs"]
    assert len(runs) == 1
    assert runs[0]["by"] == {"name": "gdv1", "display": "GDV Một", "unit": "CN-HN"}
    assert runs[0]["steps"] == [{"id": "g1", "status": "done"}, {"id": "g2", "status": "done"}]
    assert runs[0]["decisions"][0] == {"step_id": "g2", "kind": "approve", "risk": "write", "approved": True}


def test_a_field_with_text_or_a_value_is_refused(api):
    for change in ({"steps": [{"id": "g1", "status": "done", "detail": "Đã nhập 0123456789"}]}, {"inputs": {"so_cif": "0123"}},
                   {"answer": "x"}):
        assert api.post("/runs", json={"runs": [run(api.flow, **change)]}, headers=api.as_["gdv1"]).status_code == 422


def test_a_run_of_a_flow_the_caller_does_not_see_is_skipped(api):
    reply = api.post("/runs", json={"runs": [run(api.flow), run("khong-co", "r2")]}, headers=api.as_["gdv2"])
    assert reply.json() == {"kept": 0, "known": 0, "skipped": 2}


def test_runs_are_seen_like_their_flow_and_the_summary_counts_failures(api):
    api.post("/runs", json={"runs": [run(api.flow, "r1"), run(api.flow, "r2", status="failed"), run(api.flow, "r3", status="stopped")]},
             headers=api.as_["gdv1"])
    assert api.get(f"/workflows/{api.flow}/runs", headers=api.as_["gdv2"]).status_code == 404
    assert len(api.get(f"/workflows/{api.flow}/runs", headers=api.as_["quantri"]).json()["runs"]) == 3
    summary = api.get("/runs/summary", headers=api.as_["quantri"]).json()["flows"][api.flow]
    assert (summary["runs"], summary["failed"]) == (3, 1) and summary["last"] == "2026-11-19 10:00:00"
    assert api.get("/runs/summary", headers=api.as_["gdv2"]).json()["flows"] == {}


def test_the_summary_says_the_time_saved_once_there_are_three_recordings_and_three_finished_runs(api):
    # the three recordings of the fixture last 0 s each (one timestamp): make the runs slower than nothing to see only the counting
    api.post("/runs", json={"runs": [run(api.flow, "r1"), run(api.flow, "r2")]}, headers=api.as_["gdv1"])
    assert "saved_s" not in api.get("/runs/summary", headers=api.as_["gdv1"]).json()["flows"][api.flow]
    api.post("/runs", json={"runs": [run(api.flow, "r3")]}, headers=api.as_["gdv1"])
    row = api.get("/runs/summary", headers=api.as_["gdv1"]).json()["flows"][api.flow]
    assert (row["agent_s"], row["saved_s"]) == (3.5, 0.0) and "manual_s" in row
