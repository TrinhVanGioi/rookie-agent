"""Process Digital Twin: log, discovery, metrics, simulation and the /twin routes (Gate 9, server half)."""

from __future__ import annotations

import importlib.util
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.llm.rule_based import RuleBasedClient
from app.storage import Storage

BASE = datetime(2026, 11, 2, 8, 0, 0, tzinfo=timezone.utc)
SEED_PATH = Path(__file__).resolve().parents[2] / "scripts" / "twin_seed.py"


def _ts(offset: float) -> str:
    moment = BASE + timedelta(seconds=offset)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _event(session: str, seq: int, at: float, kind: str, selector: str, label: str, api=None, value_class=None) -> dict:
    return {
        "schema_version": 3, "engine": "web", "session_id": session, "seq": seq, "ts": _ts(at), "type": kind, "url": "/p",
        "target": {"selectors": [selector], "label": label, "tag": "button" if kind == "click" else "input"},
        "value": None, "value_class": value_class, "api_calls": api or [], "screenshot": None,
    }


def case_sessions(i: int, queue: float = 600.0, rework: bool = False, error: bool = False, start: float | None = None) -> dict:
    """One case with exact times: maker A (0s), B (10+i s), C (15 s, api 400 ms); queue; checker E (0 s), D (20 s)."""
    t = i * 1000.0 if start is None else start
    b = 10.0 + i
    status = 500 if error else 200
    maker = [
        _event(f"m{i}", 0, t, "click", "#a", "Mở"),
        _event(f"m{i}", 1, t + b, "input", "#b", "Số tiền", value_class="amount"),
    ]
    at = t + b
    if rework:
        at += 5
        maker.append(_event(f"m{i}", 2, at, "input", "#b", "Số tiền", value_class="amount"))
    at += 15
    maker.append(_event(f"m{i}", len(maker), at, "click", "#c", "Gửi", api=[{"method": "POST", "path": "/api/x", "status": status, "ms": 400}]))
    start_checker = at + queue
    checker = [_event(f"c{i}", 0, start_checker, "click", "#e", "Chờ duyệt"), _event(f"c{i}", 1, start_checker + 20, "click", "#d", "Duyệt")]
    return {"key": f"{i:016x}", "maker": maker, "checker": checker}


def load_world(client, cases: list[dict], learn_from: int | None = None) -> None:
    for case in cases:
        for role in ("maker", "checker"):
            events = case[role]
            body = {"schema_version": 3, "engine": "web", "session_id": events[0]["session_id"], "events": events,
                    "role": role, "case_key": case["key"], "synthetic": True}
            assert client.post("/sessions", json=body).status_code == 201
    for workflow_id, role in (("lap-lenh", "maker"), ("duyet", "checker")):
        reply = client.post("/workflows/learn", json={"workflow_id": workflow_id, "title": workflow_id, "session_ids": [c[role][0]["session_id"] for c in cases[:learn_from]]})
        assert reply.status_code == 201, reply.text


def make_process(client) -> dict:
    draft = client.get("/twin/suggest").json()
    reply = client.post("/twin/processes", json={"id": "ksv", "name": "Chuyển tiền", "stages": draft["stages"], "handoffs": draft["handoffs"]})
    assert reply.status_code == 201, reply.text
    return reply.json()


@pytest.fixture
def world(client):
    load_world(client, [case_sessions(i, rework=(i == 0), error=(i == 1)) for i in range(10)])
    return make_process(client)


# ---- sessions: role, case key, synthetic -----------------------------------------------------


def test_session_keeps_role_case_key_and_synthetic(client):
    case = case_sessions(0)
    body = {"schema_version": 3, "engine": "web", "session_id": "m0", "events": case["maker"], "role": "maker", "case_key": "ab" * 16, "synthetic": True}
    assert client.post("/sessions", json=body).status_code == 201
    stored = client.get("/sessions/m0").json()
    assert (stored["role"], stored["case_key"], stored["synthetic"]) == ("maker", "ab" * 16, True)


@pytest.mark.parametrize(
    "extra",
    [{"role": "teller"}, {"case_key": "NV001"}, {"case_key": "ab" * 4}, {"user": "nguyen.van.a"}, {"employee_id": "E1"}, {"case_id": "ORD-1"}],
)
def test_session_refuses_person_like_fields(client, extra):
    case = case_sessions(0)
    body = {"schema_version": 3, "engine": "web", "session_id": "m0", "events": case["maker"], **extra}
    assert client.post("/sessions", json=body).status_code == 422


def test_old_database_is_migrated(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, engine TEXT NOT NULL, created_at TEXT NOT NULL, events TEXT NOT NULL)")
    old.execute("INSERT INTO sessions VALUES ('x', 'web', '2026-01-01T00:00:00Z', '[]')")
    old.commit()
    old.close()
    storage = Storage(path)
    stored = storage.get_session("x")
    assert stored and stored["role"] is None and stored["synthetic"] is False
    assert storage.add_session("y", "web", [], "checker", "ab" * 8, True)
    storage.close()


# ---- schema v3 reaches the server ----------------------------------------------------------------


def test_ie_session_with_api_timings_is_accepted(client):
    event = {"schema_version": 3, "engine": "ie", "session_id": "ie-1", "seq": 0, "ts": _ts(0), "type": "click", "url": "TouchPoint/Main",
             "target": {"selectors": ["id=btn"], "label": "OK", "tag": "button"}, "value": None, "value_class": None,
             "api_calls": [{"method": "POST", "path": "/api/cif/search", "status": 200, "ms": 120.5}]}
    assert client.post("/sessions", json={"schema_version": 3, "engine": "ie", "session_id": "ie-1", "events": [event]}).status_code == 201


# ---- log ---------------------------------------------------------------------------------------------


def test_log_rows_have_steps_roles_times_and_outcomes(client, world):
    rows = client.get("/twin/log?workflow_id=lap-lenh").json()["rows"]
    mine = [r for r in rows if r["case"] == f"{0:016x}"]
    assert [r["role"] for r in mine] == ["maker"] * 3
    assert [r["outcome"] for r in mine] == ["done", "rework", "done"]   # the amount typed twice is a rework
    assert mine[1]["end"] > mine[1]["start"]
    assert mine[2]["api_ms"] == 400 and mine[0]["api_ms"] is None
    errors = [r for r in rows if r["case"] == f"{1:016x}" and r["outcome"] == "error"]
    assert len(errors) == 1 and errors[0]["step_id"].endswith("gui")
    assert set(mine[0]) == {"case", "session_id", "workflow_id", "step_id", "label", "role", "start", "end", "outcome", "api_ms"}


def test_returning_to_an_earlier_step_is_a_rework(client):
    case = case_sessions(0)
    back = _event("m0", 3, 100, "click", "#a", "Mở")   # opens the first page again after sending
    case["maker"].append(back)
    load_world(client, [case])
    rows = [r for r in client.get("/twin/log?workflow_id=lap-lenh").json()["rows"]]
    assert [r["outcome"] for r in rows] == ["done", "done", "done", "rework"]


def test_cases_join_across_roles_by_case_key(client, world):
    rows = client.get("/twin/log").json()["rows"]
    by_case = {}
    for row in rows:
        by_case.setdefault(row["case"], set()).add(row["role"])
    assert len(by_case) == 10 and all(roles == {"maker", "checker"} for roles in by_case.values())


# ---- suggest ---------------------------------------------------------------------------------------------


def test_suggest_builds_a_draft_from_joined_cases(client, world):
    draft = client.get("/twin/suggest").json()
    assert [(s["workflow_id"], s["role"]) for s in draft["stages"]] == [("lap-lenh", "maker"), ("duyet", "checker")]
    assert draft["handoffs"] == [{"from_stage": "lap-lenh", "to_stage": "duyet", "queue": "cho_duyet"}]
    assert draft["cases_joined"] == 10 and draft["name"] and draft["reason"] is None


def test_suggest_with_nothing_learned_says_why(client):
    draft = client.get("/twin/suggest").json()
    assert draft["stages"] == [] and draft["handoffs"] == [] and "ghi" in draft["reason"].lower()


def test_an_inquiry_needs_one_role_and_no_approval_so_the_draft_is_one_stage(client):
    """Vấn tin: only the teller's recordings, no case key, no checker. The draft is that one workflow, no handoff."""
    for i in range(3):
        events = case_sessions(i)["maker"]
        body = {"schema_version": 3, "engine": "web", "session_id": events[0]["session_id"], "events": events, "role": "maker"}
        assert client.post("/sessions", json=body).status_code == 201
    reply = client.post("/workflows/learn", json={"workflow_id": "tra-cif", "title": "Tra CIF", "session_ids": ["m0", "m1", "m2"]})
    assert reply.status_code == 201, reply.text
    draft = client.get("/twin/suggest").json()
    assert [(s["workflow_id"], s["role"]) for s in draft["stages"]] == [("tra-cif", "maker")]
    assert draft["handoffs"] == [] and draft["reason"] is None and draft["name"] == "Tra CIF"
    saved = client.post("/twin/processes", json={"name": draft["name"], "stages": draft["stages"], "handoffs": []})
    assert saved.status_code == 201, saved.text


# ---- discover ---------------------------------------------------------------------------------------------


def test_discover_nodes_edges_handoff_and_variants(client, world):
    graph = client.get("/twin/discover?process_id=ksv").json()
    assert graph["cases"] == 10
    ids = [n["id"] for n in graph["nodes"]]
    assert all(":" in i for i in ids) and any(i.startswith("duyet:") for i in ids)
    roles = {n["stage"]: n["role"] for n in graph["nodes"]}
    assert roles == {"lap-lenh": "maker", "duyet": "checker"}
    handoffs = [e for e in graph["edges"] if e["handoff"]]
    assert len(handoffs) == 1 and handoffs[0]["handoff"] == "cho_duyet" and handoffs[0]["count"] == 10
    assert handoffs[0]["from"].startswith("lap-lenh:") and handoffs[0]["to"].startswith("duyet:")
    counts = sorted(v["count"] for v in graph["variants"])
    assert sum(counts) == 10 and all(abs(v["share"] - v["count"] / 10) < 1e-9 for v in graph["variants"])
    assert all(n["count"] >= 10 for n in graph["nodes"])


def test_discover_variants_are_counted(client):
    cases = [case_sessions(i) for i in range(6)]
    for i in (4, 5):   # two cases go back to the first page
        cases[i]["maker"].append(_event(f"m{i}", 3, i * 1000 + 200, "click", "#a", "Mở"))
    load_world(client, cases, learn_from=4)   # the two odd cases were not learned from: they still count
    graph = client.get("/twin/discover?workflow_ids=lap-lenh,duyet").json()
    assert [v["count"] for v in graph["variants"]] == [4, 2]
    assert graph["variants"][0]["share"] == pytest.approx(4 / 6, abs=1e-4)
    assert len(graph["variants"][1]["steps"]) == len(graph["variants"][0]["steps"]) + 1


def test_discover_needs_a_target(client):
    assert client.get("/twin/discover").status_code == 422


# ---- metrics ----------------------------------------------------------------------------------------------------


def test_metrics_known_answers(client, world):
    metrics = client.get("/twin/processes/ksv/metrics").json()
    assert metrics["cases"] == 10 and metrics["hidden"] is False
    steps = {s["step_id"].split("_", 1)[1]: s for s in metrics["steps"]}
    amount = steps["so_tien"]
    assert amount["median_s"] == 15.0 and amount["p90_s"] == 18.1 and amount["rework_rate"] == 0.1
    send = steps["gui"]
    assert send["median_s"] == 15 and send["api_ms_median"] == 400 and send["error_rate"] == 0.1
    approve = steps["duyet"]
    assert approve["median_s"] == 20 and approve["stage"] == "duyet"
    first_checker = steps["cho_duyet"]
    assert first_checker["wait_median_s"] == 600
    assert metrics["queues"] == [{"name": "cho_duyet", "wait_median_s": 600, "wait_p90_s": 600}]
    assert metrics["bottleneck"]["kind"] == "queue" and metrics["bottleneck"]["id"] == "cho_duyet"
    assert metrics["bottleneck"]["share"] == pytest.approx(600 / (600 + 50), abs=1e-3)
    assert "user" not in str(metrics) and "person" not in str(metrics)


def test_metrics_are_hidden_below_five_cases(client):
    load_world(client, [case_sessions(i) for i in range(4)])
    make_process(client)
    metrics = client.get("/twin/processes/ksv/metrics").json()
    assert metrics == {"cases": 4, "hidden": True, "steps": [], "queues": [], "bottleneck": None}


# ---- process models -------------------------------------------------------------------------------------------


def test_process_versions_and_validation(client, world):
    first = client.get("/twin/processes/ksv").json()
    assert first["version"] == 1 and first["schema_version"] == 1
    again = client.post("/twin/processes", json={"id": "ksv", "name": "Bản 2", "stages": first["stages"], "handoffs": first["handoffs"]}).json()
    assert again["version"] == 2 and client.get("/twin/processes/ksv").json()["name"] == "Bản 2"
    listing = client.get("/twin/processes").json()["processes"]
    assert [(p["id"], p["version"]) for p in listing] == [("ksv", 1), ("ksv", 2)]
    bad = dict(first["stages"][0], workflow_id="khong-co")
    assert client.post("/twin/processes", json={"name": "x", "stages": [bad], "handoffs": []}).status_code == 422
    assert client.post("/twin/processes", json={"name": "x", "stages": first["stages"], "handoffs": [{"from_stage": "a", "to_stage": "b", "queue": "q"}]}).status_code == 422
    assert client.get("/twin/processes/none").status_code == 404


# ---- simulation -------------------------------------------------------------------------------------------------


def simulate(client, **body):
    reply = client.post("/twin/processes/ksv/simulate", json=body)
    assert reply.status_code == 200, reply.text
    return reply.json()


def test_simulation_shape_and_determinism(client, world):
    body = {"seed": 5, "hours": 4, "arrivals_per_hour": 60, "staff": {"maker": 2, "checker": 1}}
    one, two = simulate(client, **body), simulate(client, **body)
    assert one == two
    assert set(one) >= {"baseline", "scenario", "explanation"}
    for result in (one["baseline"], one["scenario"]):
        assert set(result) == {"completed", "cycle_mean_s", "cycle_p90_s", "waits", "utilization", "bottleneck"}
        assert set(result["utilization"]) == {"maker", "checker"}
    assert simulate(client, **{**body, "seed": 6}) != one
    assert "phút" in one["explanation"]


def test_one_more_checker_reduces_the_approval_wait(client, world):
    reply = simulate(client, seed=3, hours=6, arrivals_per_hour=170, baseline_staff={"maker": 3, "checker": 1}, staff={"maker": 3, "checker": 2})
    before, after = reply["baseline"]["waits"]["cho_duyet"], reply["scenario"]["waits"]["cho_duyet"]
    assert before > 30 and after < before / 2
    assert reply["scenario"]["completed"] >= reply["baseline"]["completed"]
    assert reply["scenario"]["utilization"]["checker"] < reply["baseline"]["utilization"]["checker"]


def test_baseline_reproduces_the_measured_approval_wait(client, world):
    measured = next(q for q in client.get("/twin/processes/ksv/metrics").json()["queues"] if q["name"] == "cho_duyet")["wait_median_s"]
    reply = simulate(client, seed=4, hours=40, arrivals_per_hour=5)
    assert reply["baseline"]["waits"]["cho_duyet"] == pytest.approx(measured, rel=0.15)
    assert reply["inputs"]["pickup_s"]["checker"] > 0


def test_removing_a_step_cuts_the_cycle_by_about_that_step(client, world):
    step = next(s["step_id"] for s in client.get("/twin/processes/ksv/metrics").json()["steps"] if s["step_id"].endswith("so_tien"))
    reply = simulate(client, seed=2, hours=40, arrivals_per_hour=5, steps={step: "remove"})
    drop = reply["baseline"]["cycle_mean_s"] - reply["scenario"]["cycle_mean_s"]
    assert abs(drop - 15.0) < 1.5


def test_agent_step_uses_a_fraction_of_human_time(client, world):
    step = next(s["step_id"] for s in client.get("/twin/processes/ksv/metrics").json()["steps"] if s["step_id"].endswith("gui"))
    reply = simulate(client, seed=2, hours=40, arrivals_per_hour=5, steps={step: "agent"})
    assert reply["baseline"]["cycle_mean_s"] - reply["scenario"]["cycle_mean_s"] == pytest.approx(14.6 * 0.7, abs=1.0)   # 70% of the human part (14.6 s) is saved; the 0.4 s of API stays


def test_api_factor_only_scales_the_api_part(client, world):
    reply = simulate(client, seed=2, hours=40, arrivals_per_hour=5, api_factor=0)
    assert reply["baseline"]["cycle_mean_s"] - reply["scenario"]["cycle_mean_s"] == pytest.approx(0.4, abs=0.05)   # 400 ms of one step


def test_simulation_with_work_hours_runs(client, world):
    reply = simulate(client, seed=1, hours=48, arrivals_per_hour=20, work_hours={"start": 8, "end": 17})
    assert reply["scenario"]["completed"] > 0


@pytest.mark.parametrize("body", [{"steps": {"khong-co": "remove"}}, {"staff": {"maker": 0}}, {"staff": {"boss": 1}}, {"steps": {"x": "skip"}}, {"hours": 0}, {"arrivals_per_hour": 99999}])
def test_simulation_refuses_bad_input(client, world, body):
    assert client.post("/twin/processes/ksv/simulate", json=body).status_code == 422


def test_simulation_needs_enough_cases(client):
    load_world(client, [case_sessions(i) for i in range(4)])
    make_process(client)
    assert client.post("/twin/processes/ksv/simulate", json={}).status_code == 409


def test_explanation_falls_back_to_the_rule_text_when_the_model_fails(client, world):
    class Broken:
        def explain_simulation(self, *args):
            raise RuntimeError("down")

    body = {"seed": 1, "hours": 2, "arrivals_per_hour": 30}
    expected = simulate(client, **body)["explanation"]
    client.app.state.llm_client = Broken()
    assert simulate(client, **body)["explanation"] == expected


def test_rule_based_client_explains_in_vietnamese():
    text = RuleBasedClient().explain_simulation(
        {"completed": 10, "cycle_mean_s": 1800, "waits": {"cho_duyet": 1500}},
        {"completed": 14, "cycle_mean_s": 900, "waits": {"cho_duyet": 600}, "bottleneck": {"kind": "queue", "id": "cho_duyet", "share": 0.6}},
        {},
    )
    assert "30.0 phút" in text and "15.0 phút" in text and "cho_duyet" in text


# ---- the seed script, in process -----------------------------------------------------------------------------------


def _seed_module():
    spec = importlib.util.spec_from_file_location("twin_seed", SEED_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_script_makes_a_process_with_an_approval_queue_bottleneck(client):
    seed = _seed_module()

    def call(path, body=None):
        reply = client.get(path) if body is None else client.post(path, json=body)
        assert reply.status_code < 300, reply.text
        return reply.json()

    result = seed.seed_cases(call, n=30, seed=7)
    assert result["cases"] == 30 and result["synthetic"] and result["process"]["id"] == "chuyen-tien-ksv"
    assert all(client.get(f"/sessions/{s['session_id']}").json()["synthetic"] for s in client.get("/sessions").json()["sessions"])
    metrics = client.get("/twin/processes/chuyen-tien-ksv/metrics").json()
    assert metrics["cases"] == 30 and metrics["bottleneck"]["id"] == "cho_duyet"
    assert seed.make_cases(5, 7) == seed.make_cases(5, 7) and seed.make_cases(5, 7) != seed.make_cases(5, 8)
    reply = call("/twin/processes/chuyen-tien-ksv/simulate", {"seed": 4, "hours": 8, "staff": {"maker": 1, "checker": 2}})
    assert reply["scenario"]["waits"]["cho_duyet"] <= reply["baseline"]["waits"]["cho_duyet"]
