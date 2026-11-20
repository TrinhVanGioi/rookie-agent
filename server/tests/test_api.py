import copy

import pytest

from tests.helpers import java_transfer_session, payload, web_report_session


def post_sessions(client, count=3):
    ids = []
    for i in range(count):
        events = java_transfer_session(f"s-java-{i}")
        assert client.post("/sessions", json=payload(f"s-java-{i}", events)).status_code == 201
        ids.append(f"s-java-{i}")
    return ids


def learn(client, workflow_id="chuyen-tien", count=3):
    response = client.post("/workflows/learn", json={"workflow_id": workflow_id, "session_ids": post_sessions(client, count)})
    assert response.status_code == 201, response.text
    return response.json()


# ---- sessions (task 1.6) -----------------------------------------------------------------


def test_valid_session_is_stored_and_can_be_read_back(client):
    events = java_transfer_session("s-1")
    created = client.post("/sessions", json=payload("s-1", events))
    assert created.status_code == 201
    assert created.json() == {"session_id": "s-1", "engine": "java", "event_count": len(events)}
    got = client.get("/sessions/s-1").json()
    assert got["events"] == events and got["engine"] == "java"
    assert [s["session_id"] for s in client.get("/sessions").json()["sessions"]] == ["s-1"]
    assert client.get("/sessions?engine=web").json()["sessions"] == []


def test_unknown_session_is_404(client):
    assert client.get("/sessions/khong-co").status_code == 404


def test_invalid_event_is_rejected_and_nothing_is_stored(client):
    events = java_transfer_session("s-1")
    events[2]["type"] = "drag"
    response = client.post("/sessions", json=payload("s-1", events))
    assert response.status_code == 422 and "sự kiện 2" in response.json()["detail"][0]
    assert client.get("/sessions/s-1").status_code == 404


def test_event_that_leaks_a_sensitive_value_is_rejected(client):
    events = java_transfer_session("s-1")
    events[3]["value"] = "001012345678"  # value_class says account_number: the value must be null
    assert client.post("/sessions", json=payload("s-1", events)).status_code == 422


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["events"][1].update(session_id="khac"),
        lambda p: p["events"][1].update(seq=7),
        lambda p: p.update(engine="web"),
        lambda p: p.update(events=[]),
        lambda p: p.update(schema_version=2),
    ],
)
def test_inconsistent_sessions_are_rejected(client, change):
    body = payload("s-1", java_transfer_session("s-1"))
    change(body)
    assert client.post("/sessions", json=body).status_code == 422


def test_same_session_cannot_be_sent_twice(client):
    body = payload("s-1", java_transfer_session("s-1"))
    assert client.post("/sessions", json=body).status_code == 201
    assert client.post("/sessions", json=body).status_code == 409


def test_web_and_java_sessions_both_accepted(client):
    assert client.post("/sessions", json=payload("w-1", web_report_session("w-1", "2026-11-10"))).status_code == 201
    assert client.post("/sessions", json=payload("j-1", java_transfer_session("j-1"))).status_code == 201


# ---- learning and workflow life cycle (tasks 2.2, 2.3) -----------------------------------------


def test_learn_stores_a_draft_with_digest_and_versions_increase(client):
    first = learn(client)
    assert first["workflow"]["version"] == 1 and first["workflow"]["status"] == "draft"
    assert len(first["digest"]) == 64
    second = client.post("/workflows/learn", json={"workflow_id": "chuyen-tien", "session_ids": ["s-java-0", "s-java-1", "s-java-2"]})
    assert second.json()["workflow"]["version"] == 2
    assert client.get("/workflows/chuyen-tien").json()["workflow"]["version"] == 2
    assert client.get("/workflows/chuyen-tien/versions/1").json()["digest"] == first["digest"]


def test_learn_refuses_unknown_sessions_and_diverging_sessions(client):
    assert client.post("/workflows/learn", json={"workflow_id": "x", "session_ids": ["khong-co"]}).status_code == 404
    client.post("/sessions", json=payload("a", java_transfer_session("a")))
    client.post("/sessions", json=payload("b", java_transfer_session("b", extra_click=True)))
    response = client.post("/workflows/learn", json={"workflow_id": "x", "session_ids": ["a", "b"]})
    assert response.status_code == 422 and "khác phiên 1" in response.json()["detail"]


def test_workflow_id_must_be_a_safe_slug(client):
    ids = [f"s-{i}" for i in range(1)]
    client.post("/sessions", json=payload("s-0", java_transfer_session("s-0")))
    for bad in ["Chuyển Tiền", "../x", ""]:
        assert client.post("/workflows/learn", json={"workflow_id": bad, "session_ids": ids}).status_code == 422


def test_status_must_go_draft_tested_approved_in_order(client):
    learn(client)
    url = "/workflows/chuyen-tien/versions/1/status"
    assert client.post(url, json={"status": "approved"}).status_code == 409  # cannot skip tested
    assert client.post(url, json={"status": "draft"}).status_code == 409
    assert client.post(url, json={"status": "bogus"}).status_code == 422


def test_tested_needs_a_passed_sandbox_run(client):
    learn(client)
    status = "/workflows/chuyen-tien/versions/1/status"
    runs = "/workflows/chuyen-tien/versions/1/test-runs"
    assert client.post(status, json={"status": "tested"}).status_code == 409

    assert client.post(runs, json={"status": "needs_help", "message": "x"}).json() == {"ok": False}
    assert client.post(status, json={"status": "tested"}).status_code == 409  # a failed run does not count

    assert client.post(runs, json={"status": "finished"}).json() == {"ok": True}
    tested = client.post(status, json={"status": "tested"})
    assert tested.status_code == 200 and tested.json()["workflow"]["status"] == "tested"


def test_status_change_changes_the_digest_and_cannot_go_back(client):
    first = learn(client)
    client.post("/workflows/chuyen-tien/versions/1/test-runs", json={"status": "finished"})
    tested = client.post("/workflows/chuyen-tien/versions/1/status", json={"status": "tested"}).json()
    assert tested["digest"] != first["digest"]
    assert client.post("/workflows/chuyen-tien/versions/1/status", json={"status": "draft"}).status_code == 409


def test_unapproved_workflow_is_never_served_as_approved(client):
    learn(client)
    assert client.get("/workflows/chuyen-tien/approved").status_code == 404
    client.post("/workflows/chuyen-tien/versions/1/test-runs", json={"status": "finished"})
    client.post("/workflows/chuyen-tien/versions/1/status", json={"status": "tested"})
    assert client.get("/workflows/chuyen-tien/approved").status_code == 404  # tested is not enough
    client.post("/workflows/chuyen-tien/versions/1/status", json={"status": "approved"})
    approved = client.get("/workflows/chuyen-tien/approved")
    assert approved.status_code == 200 and approved.json()["workflow"]["status"] == "approved"


def test_latest_approved_version_is_served_while_a_newer_draft_exists(client):
    learn(client)
    for status in ("tested", "approved"):
        client.post("/workflows/chuyen-tien/versions/1/test-runs", json={"status": "finished"})
        client.post("/workflows/chuyen-tien/versions/1/status", json={"status": status})
    client.post("/workflows/learn", json={"workflow_id": "chuyen-tien", "session_ids": ["s-java-0", "s-java-1"]})
    assert client.get("/workflows/chuyen-tien").json()["workflow"]["version"] == 2
    assert client.get("/workflows/chuyen-tien/approved").json()["workflow"]["version"] == 1
    listing = client.get("/workflows").json()["workflows"]
    assert [(w["version"], w["status"], w["engine"]) for w in listing] == [(1, "approved", "java"), (2, "draft", "java")]
    assert all("title" in w for w in listing)


def test_unknown_workflow_is_404(client):
    for path in ["/workflows/khong-co", "/workflows/khong-co/approved", "/workflows/khong-co/versions/1"]:
        assert client.get(path).status_code == 404
    assert client.post("/workflows/khong-co/versions/1/status", json={"status": "tested"}).status_code == 404
    assert client.post("/workflows/khong-co/versions/1/test-runs", json={"status": "finished"}).status_code == 404


def test_data_survives_a_restart(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    db = tmp_path / "keep.db"
    with TestClient(create_app(db)) as first:
        learn(first)
    with TestClient(create_app(db)) as second:
        assert second.get("/workflows/chuyen-tien").json()["workflow"]["version"] == 1
        assert second.get("/sessions/s-java-0").status_code == 200


# ---- naming and adjusting an agent in the GDV's own words -------------------------------------------


def test_the_gdv_names_the_agent_and_the_id_is_made_for_them(client):
    ids = post_sessions(client)
    first = client.post("/workflows/learn", json={"title": "Tra CIF và lập lệnh chuyển tiền", "session_ids": ids})
    assert first.status_code == 201
    workflow = first.json()["workflow"]
    assert workflow["id"] == "tra-cif-va-lap-lenh-chuyen-tien" and workflow["title"] == "Tra CIF và lập lệnh chuyển tiền"
    second = client.post("/workflows/learn", json={"title": "Tra CIF và lập lệnh chuyển tiền", "session_ids": ids})
    assert second.json()["workflow"]["id"] == "tra-cif-va-lap-lenh-chuyen-tien-2"  # same name twice: no clash
    assert {w["title"] for w in client.get("/workflows").json()["workflows"]} == {"Tra CIF và lập lệnh chuyển tiền"}


def test_learning_needs_a_name_or_an_id(client):
    assert client.post("/workflows/learn", json={"session_ids": post_sessions(client)}).status_code == 422


def test_one_click_changes_how_much_control_a_read_step_has(client):
    learn(client)
    steps = client.get("/workflows/chuyen-tien").json()["workflow"]["steps"]
    read_step = next(s for s in steps if s["risk"] == "read")
    response = client.post("/workflows/chuyen-tien/versions/1/revise", json={"modes": {read_step["id"]: "review"}})
    assert response.status_code == 201
    revised = response.json()["workflow"]
    assert revised["version"] == 2 and revised["status"] == "draft"
    assert next(s for s in revised["steps"] if s["id"] == read_step["id"])["mode"] == "review"
    assert client.get("/workflows/chuyen-tien/versions/1").json()["workflow"]["steps"] == steps  # the old version is untouched


def test_the_safety_rules_cannot_be_relaxed_from_the_screen(client):
    learn(client)
    steps = client.get("/workflows/chuyen-tien").json()["workflow"]["steps"]
    money = next(s for s in steps if s["risk"] == "money")
    url = "/workflows/chuyen-tien/versions/1/revise"
    refused = client.post(url, json={"modes": {money["id"]: "auto"}})
    assert refused.status_code == 422 and "tiền" in refused.json()["detail"]
    assert client.post(url, json={"modes": {money["id"]: "review"}}).status_code == 201  # more control is allowed
    assert client.post(url, json={"modes": {"khong-co": "auto"}}).status_code == 422
    assert client.post(url, json={"modes": {}}).status_code == 422
    assert client.post(url, json={"modes": {money["id"]: "bogus"}}).status_code == 422
    assert client.post("/workflows/khong-co/versions/1/revise", json={"modes": {"s": "auto"}}).status_code == 404


# ---- learning with a model: the traces go to the builder, the rule-based learner is the way back ----

class StubBuilder:
    """Stands for the Codie builder: an answer, or the reason it could not build."""

    def __init__(self, result=None, failure=None):
        self.result, self.failure, self.traces = result, failure, None
        self.available = True

    def build(self, traces, workflow_id, version, title=None):
        from app.llm.flow import FlowBuildError

        self.traces = traces
        if self.failure:
            raise FlowBuildError(self.failure, [{"mode": "rookie-design", "ok": False, "seconds": 1.2, "prompt_chars": 900, "note": "lỗi", "time": "t"}])
        return self.result


def _ie_sessions(client):
    from tests.test_learner import signin_run

    ids = []
    for name, run in (("a", signin_run("a", role="KSV")), ("b", signin_run("b")), ("c", signin_run("c", role="GDV"))):
        body = {"schema_version": 2, "engine": "ie", "session_id": name, "events": run}
        assert client.post("/sessions", json=body).status_code == 201
        ids.append(name)
    return ids


def test_a_model_built_workflow_is_stored_and_says_how_it_was_made(tmp_path):
    from app.llm.flow import FlowResult
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app(tmp_path / "t.db")
    workflow = {"schema_version": 2, "engine": "ie", "id": "x", "version": 1, "status": "draft", "inputs": [],
                "steps": [{"id": "s1", "action": "click", "target": {"selectors": ["frame=top|id=b"], "label": "B", "tag": "button"}, "risk": "read", "mode": "auto"}]}
    app.state.flow_builder = StubBuilder(FlowResult(workflow, ["một cảnh báo"], ["Một câu hỏi?"], [{"mode": "rookie-design", "ok": True, "seconds": 3.0, "prompt_chars": 500, "note": "đạt kiểm chứng", "time": "t"}]))
    client = TestClient(app)
    ids = _ie_sessions(client)
    reply = client.post("/workflows/learn", json={"title": "Dang nhap", "session_ids": ids, "traces": [{"trace": 1}, {"trace": 2}, {"trace": 3}]})
    assert reply.status_code == 201
    body = reply.json()
    assert body["method"] == "codie" and body["questions"] == ["Một câu hỏi?"] and body["llm"]["calls"][0]["mode"] == "rookie-design"
    assert body["workflow"]["id"] and client.get(f"/workflows/{body['workflow']['id']}").status_code == 200
    assert len(app.state.flow_builder.traces) == 3


def test_when_the_model_fails_the_rule_based_learner_builds_it_and_the_reason_is_given_in_plain_words(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app(tmp_path / "t.db")
    app.state.flow_builder = StubBuilder(failure="Codie không trả lời sau 600 giây.")
    client = TestClient(app)
    ids = _ie_sessions(client)
    reply = client.post("/workflows/learn", json={"title": "Dang nhap", "session_ids": ids, "traces": [{"trace": 1}]})
    assert reply.status_code == 201
    body = reply.json()
    assert body["method"] == "rule" and "Codie không trả lời" in body["fallback_reason"] and body["llm"]["calls"][0]["ok"] is False
    assert [s["action"] for s in body["workflow"]["steps"]] == ["fill", "select", "click"]        # the rule learner's own result


def test_without_traces_or_without_a_builder_the_old_way_is_unchanged(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app(tmp_path / "t.db")
    app.state.flow_builder = None
    client = TestClient(app)
    ids = _ie_sessions(client)
    body = client.post("/workflows/learn", json={"title": "Dang nhap", "session_ids": ids}).json()
    assert body["method"] == "rule" and "fallback_reason" not in body
    body = client.post("/workflows/learn", json={"title": "Dang nhap 2", "session_ids": ids, "traces": [{"x": 1}]}).json()
    assert body["method"] == "rule" and "chưa bật" in body["fallback_reason"]


def test_an_ie_recording_that_says_what_the_screen_showed_is_taken_and_learned_as_version_4(client):
    """Task 12.1: schema 4 sessions (events with `shows`) go in and give a flow whose steps carry a postcondition."""
    from tests.test_learner import lookup_run

    ids = []
    for name in ("v4-a", "v4-b"):
        events = [{**e, "session_id": name} for e in lookup_run(name)]
        body = {"schema_version": 4, "engine": "ie", "session_id": name, "events": events}
        assert client.post("/sessions", json=body).status_code == 201, client.post("/sessions", json=body).text
        ids.append(name)
    reply = client.post("/workflows/learn", json={"title": "Tra cứu tài khoản", "session_ids": ids})
    assert reply.status_code == 201, reply.text
    workflow = reply.json()["workflow"]
    assert workflow["schema_version"] == 4 and workflow["steps"][1]["expect"]["appears"][0]["name"] == "tblInfo"
    shown = dict(body, schema_version=4, session_id="v4-x", events=[{**e, "session_id": "v4-x", "shows": [{"frame": "w", "kind": "value", "name": "1"}]} for e in events])
    assert client.post("/sessions", json=shown).status_code == 422                       # what the screen showed is names only, by kind
