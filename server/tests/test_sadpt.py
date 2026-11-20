"""Task 12.8 (SADPT, Knowledge): four numbers from the adaptation log. The server counts; it does not decide again.
A run of digits is a value and is refused. The risk is the step's risk on the version that ran."""

from __future__ import annotations

from app.sadpt import measure
from tests.test_delta import post_lookup
from tests.test_learner import ie_event, shown


def test_the_four_numbers_and_an_empty_log_has_no_made_up_rate():
    rows = [
        {"saw": "low_confidence", "change": "technical", "action": "reresolve", "outcome": "done", "risk": "read"},
        {"saw": "not_found", "change": "technical", "action": "ask", "outcome": "stopped", "risk": "read"},
        {"saw": "low_confidence", "change": "technical", "action": "reresolve", "outcome": "postcheck_failed", "risk": "read"},
        {"saw": "contract_changed", "change": "technical", "action": "ask", "outcome": "stopped", "risk": "read"},
        {"saw": "unexpected", "change": "business", "action": "ask", "outcome": "stopped", "risk": "read"},
        {"saw": "low_confidence", "change": "technical", "action": "reresolve", "outcome": "done", "risk": "money"},
        {"saw": "unexpected", "change": "business", "action": "reresolve", "outcome": "done", "risk": "read"},
    ]
    got = measure(rows, steps_retaught=2)
    assert (got["ui_changes"], got["ui_recovered"], got["ui_recovery"]) == (4, 2, 0.5)
    assert (got["steps_retaught"], got["business_stops"], got["overreach"]) == (2, 1, 2)
    assert measure([])["ui_recovery"] is None and measure([])["overreach"] == 0


def _run(flow, run_id, adaptations):
    return {"run_id": run_id, "time": "2026-11-20 10:00:00", "workflow_id": flow, "version": 1, "title": "Tra cứu",
            "mode": "screen", "status": "finished", "seconds": 4, "steps": [{"id": "s1", "status": "done"}],
            "adaptations": adaptations}


def test_the_numbers_come_from_the_runs_and_the_parts_taught_again_and_a_value_is_refused(client):
    for name in ("a", "b"):
        post_lookup(client, name)
    first = client.post("/workflows/learn", json={"title": "Tra cứu tài khoản", "session_ids": ["a", "b"]}).json()["workflow"]
    wid = first["id"]
    read = next(step["id"] for step in first["steps"] if step["risk"] == "read")
    write = next(step["id"] for step in first["steps"] if step["risk"] != "read")
    quiet = client.post("/runs", json={"runs": [_run(wid, "r0", [])]})
    assert quiet.status_code == 200
    assert client.get(f"/workflows/{wid}/runs").json()["sadpt"]["ui_recovery"] is None

    sent = _run(wid, "r1", [
        {"step_id": read, "saw": "low_confidence", "change": "technical", "action": "reresolve", "outcome": "done", "risk": "read"},
        {"step_id": read, "saw": "not_found", "change": "technical", "action": "ask", "outcome": "stopped", "risk": "read"},
        {"step_id": read, "saw": "unexpected", "change": "business", "action": "ask", "outcome": "stopped", "risk": "read"},
        {"step_id": write, "saw": "low_confidence", "change": "technical", "action": "reresolve", "outcome": "done", "risk": "read"},
    ])
    assert client.post("/runs", json={"runs": [sent]}).status_code == 200
    events = [dict(shown(ie_event(0, "click", "btnOK", "ĐỒNG Ý", session="t"), ("work", "table", "tblInfo")), session_id="t", seq=0)]
    assert client.post("/sessions", json={"schema_version": 4, "engine": "ie", "session_id": "t", "events": events}).status_code == 201
    assert client.post(f"/workflows/{wid}/versions/1/teach", json={"after_step": "s2_tra_cuu", "session_id": "t"}).status_code == 201

    sadpt = client.get(f"/workflows/{wid}/runs").json()["sadpt"]
    assert (sadpt["ui_changes"], sadpt["ui_recovered"], sadpt["ui_recovery"]) == (3, 2, 0.667)
    assert (sadpt["steps_retaught"], sadpt["business_stops"], sadpt["overreach"]) == (1, 1, 1)
    summary = client.get("/runs/summary").json()["flows"][wid]["sadpt"]
    assert summary["overreach"] == 1 and summary["steps_retaught"] == 1

    valued = _run(wid, "r2", [{"step_id": "acct_0123456789", "saw": "not_found", "change": "technical", "action": "ask", "outcome": "stopped"}])
    assert client.post("/runs", json={"runs": [valued]}).status_code == 422
    extra = _run(wid, "r3", [{"step_id": read, "saw": "not_found", "change": "technical", "action": "ask", "outcome": "stopped",
                              "where": {"name": "0123456789"}}])
    assert client.post("/runs", json={"runs": [extra]}).status_code == 422
