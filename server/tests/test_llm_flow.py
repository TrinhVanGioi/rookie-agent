"""Gate 4: building a workflow with Genie Codie. A fake `codie` (a Python script run as a real process) answers; the program around it is real.

What is tested: the merge of traces; every rule of the gate with one case that breaks it; the fix loop; the fall back; that the model
never writes a selector, a risk or a mode; that a link to what an earlier screen showed becomes a read step and a value; and that no value
of the screen is in anything built or sent.
"""

import copy
import json
import sys
from pathlib import Path

import pytest

from app.llm import codie_cli
from app.llm.flow import CodieFlowBuilder, FlowBuildError, assemble, check_design, check_draft, merge_traces
from app.schemas import validate_workflow

# ---- a trace like the one the teller's PC makes: three recordings of "sign in, choose a role if needed, search, type the account found, log off" ----


def ev(sid, seq, kind, el, **extra):
    base = {"eid": f"{sid}e{seq:03d}", "seq": seq, "t_rel_ms": seq * 100, "kind": kind, "el_id": el, "key_class": None, "value": None,
            "value_class": None, "screen": "TouchPoint", "value_before": None, "option_value": None}
    base.update(extra)
    return base


def one_trace(sid, role=None):
    events, seq = [], 0

    def add(kind, el, **extra):
        nonlocal seq
        events.append(ev(sid, seq, kind, el, **extra))
        seq += 1
        return events[-1]["eid"]

    add("change", "e1", value_class="username")
    if role:
        add("change", "e2", value=role, option_value=role.lower())
    find = add("click", "e3")
    copied = add("change", "e4", value_class="account_number")
    add("click", "e5")
    session = {"session_id": sid, "events": events,
               "screens": [{"after_eid": find, "region": ["main"], "items": [{"frame": "main", "kind": "table", "table_id": "grid", "headers": ["So TK", "Loai"],
                                                                           "col_classes": ["account_number", "plain"], "row_count": 2}]}],
               "links": [{"eid": copied, "from_eid": find, "path": "grid.0.so_tk", "ambiguous": False}]}
    elements = {
        "e1": {"frame": "top", "tag": "input", "type": "text", "label": "User Account", "selectors": ["frame=top|id=txtUser"], "is_control": True},
        "e2": {"frame": "top", "tag": "select", "type": "select-one", "label": "Role", "selectors": ["frame=top|id=currentRole"], "is_control": True,
               "options": [{"value": "gdv", "text": "GDV"}, {"value": "ksv", "text": "KSV"}]},
        "e3": {"frame": "main", "tag": "input", "type": "button", "label": "TÌM KIẾM", "selectors": ["frame=main|id=btnFind"], "is_control": True},
        "e4": {"frame": "main", "tag": "input", "type": "text", "label": "So tai khoan chuyen", "selectors": ["frame=main|id=txtCopy"], "is_control": True},
        "e5": {"frame": "top", "tag": "button", "type": "button", "label": "ĐĂNG XUẤT", "selectors": ["frame=top|id=btnLogoff"], "is_control": True},
    }
    return {"schema_version": 2, "engine": "ie", "trace_id": f"t-{sid}", "app": "TouchPoint", "sessions": [session], "elements": elements,
            "masking": {"rules_version": "1", "dropped_count": 1}}


def three_traces():
    return [one_trace("s1", role="KSV"), one_trace("s1"), one_trace("s1", role="GDV")]


def good_design(trace):
    s = [x["session_id"] for x in trace["sessions"]]
    eid = lambda sid, n: f"{sid}e{n:03d}"                     # noqa: E731
    with_role = {sid: ("role" in str(sid)) for sid in s}        # not used: roles are read from the trace below
    del with_role
    role_evidence, find, copy_, off = {}, {}, {}, {}
    for session in trace["sessions"]:
        sid = session["session_id"]
        by_el = {}
        for e in session["events"]:
            by_el.setdefault(e["el_id"], []).append(e["eid"])
        if "e2" in by_el:
            role_evidence[sid] = by_el["e2"]
        find[sid], copy_[sid], off[sid] = by_el["e3"], by_el["e4"], by_el["e5"]
    user = {session["session_id"]: [e["eid"] for e in session["events"] if e["el_id"] == "e1"] for session in trace["sessions"]}
    return {"title": "Tra cứu tài khoản", "steps": [
        {"n": 1, "intent_vi": "Nhập user", "action": "fill", "el_id": "e1", "evidence": user, "value_kind": "param", "param_name": "user_account"},
        {"n": 2, "intent_vi": "Chọn role", "action": "select", "el_id": "e2", "evidence": role_evidence, "value_kind": "param", "param_name": "role", "optional": "if_different"},
        {"n": 3, "intent_vi": "Tìm kiếm", "action": "click", "el_id": "e3", "evidence": find},
        {"n": 4, "intent_vi": "Đọc màn hình", "action": "read_fields", "save_as": "kq", "evidence": {}},
        {"n": 5, "intent_vi": "Nhập số tài khoản tìm được", "action": "fill", "el_id": "e4", "evidence": copy_, "value_kind": "link", "link": {"var": "kq", "path": "grid.0.so_tk"}},
        {"n": 6, "intent_vi": "Đăng xuất", "action": "click", "el_id": "e5", "evidence": off}],
        "ignored": [], "questions": [], "overall_confidence": 0.92}


def good_draft(design):
    steps = []
    for step in design["steps"]:
        out = {"action": step["action"], "target": {"el_id": step["el_id"]} if step.get("el_id") else None, "optional": {"mode": step["optional"]} if step.get("optional") else None}
        if step["action"] in ("fill", "select"):
            out["value"] = {"param": "{" + str(step.get("param_name")) + "}", "link": "{" + str((step.get("link") or {}).get("var")) + "." + str((step.get("link") or {}).get("path")) + "}"}[step["value_kind"]]
        if step["action"] == "read_fields":
            out["save_as"] = step["save_as"]
        steps.append(out)
    return {"title": design["title"], "inputs": [{"name": "user_account", "type": "string", "label": "User Account"},
                                                 {"name": "role", "type": "string", "label": "Role"}], "steps": steps}


def merged():
    return merge_traces(three_traces())


# ---- the merge ----------------------------------------------------------------------------------------------------------------

def test_the_traces_become_one_with_unique_event_ids_and_one_element_per_selector():
    trace = merged()
    assert [s["session_id"] for s in trace["sessions"]] == ["s1", "s2", "s3"]
    eids = [e["eid"] for s in trace["sessions"] for e in s["events"]]
    assert len(eids) == len(set(eids)) and eids[0] == "s1e000"
    assert len(trace["elements"]) == 5
    link = trace["sessions"][1]["links"][0]
    assert link["eid"].startswith("s2") and link["from_eid"].startswith("s2")      # the links follow their events
    assert trace["masking"]["dropped_count"] == 3


# ---- the gate: a good design passes, and each rule has a case that breaks it ------------------------------------------------------

def test_a_good_design_and_draft_pass_the_gate():
    trace = merged()
    design = good_design(trace)
    assert check_design(trace, design) == []
    assert check_draft(design, good_draft(design)) == []


def broken(mutate):
    trace = merged()
    design = good_design(trace)
    mutate(design, trace)
    return check_design(trace, design)


@pytest.mark.parametrize("name,mutate,needle", [
    ("an invented element", lambda d, t: d["steps"][2].update(el_id="e99"), "not an element of the trace"),
    ("an invented event", lambda d, t: d["steps"][2]["evidence"].update(s1=["s1e999"]), "not an event of session"),
    ("evidence on the wrong element", lambda d, t: d["steps"][2]["evidence"].update(s1=d["steps"][0]["evidence"]["s1"]), "not on e3"),
    ("a fill that is a click", lambda d, t: d["steps"][2].update(action="fill", value_kind="param", param_name="x"), "not a fill"),
    ("a step missing from a recording that is not optional", lambda d, t: d["steps"][1].update(optional=None), "must be optional"),
    ("an optional step of the wrong kind", lambda d, t: d["steps"][1].update(optional="if_present"), "does not fit"),
    ("a link to a variable never read", lambda d, t: d["steps"][4]["link"].update(var="nope"), "EARLIER read_fields"),
    ("a link to a value no screen showed", lambda d, t: d["steps"][4]["link"].update(path="grid.9.so_tk"), "not shown by any screen"),
    ("a constant that is sensitive", lambda d, t: d["steps"][0].update(value_kind="const", const_value="teller01"), "sensitive"),
    ("a parameter name that is not a name", lambda d, t: d["steps"][0].update(param_name="So Tai Khoan"), "lower_snake_case"),
    ("two parameters with one name", lambda d, t: d["steps"][1].update(param_name="user_account"), "already used"),
    ("steps out of order", lambda d, t: d["steps"].insert(0, d["steps"].pop(2)), "order of the work"),
    ("an action that is in no step", lambda d, t: d["steps"].pop(5), "in no step"),
])
def test_each_rule_of_the_gate_catches_its_case(name, mutate, needle):
    problems = broken(mutate)
    assert any(needle in p for p in problems), (name, problems)


def test_a_step_that_writes_cannot_be_optional_and_cannot_be_left_out():
    trace = merged()
    for session in trace["sessions"]:
        for event in session["events"]:
            if event["el_id"] == "e5":
                event["screen"] = "Chuyển tiền"
    trace["elements"]["e5"]["label"] = "Lưu"
    design = good_design(trace)
    design["steps"][5]["optional"] = "if_present"
    assert any("never be optional" in p for p in check_design(trace, design))
    design = good_design(trace)
    design["steps"].pop(5)
    design["ignored"] = [{"eid": "s1e004", "reason": "noise"}, {"eid": "s2e003", "reason": "noise"}, {"eid": "s3e004", "reason": "noise"}]
    assert any("cannot be left out" in p for p in check_design(trace, design))


def test_a_draft_that_adds_removes_reorders_or_changes_a_value_is_refused():
    design = good_design(merged())
    for mutate, needle in [
        (lambda d: d["steps"].pop(), "do not add, remove or reorder"),
        (lambda d: d["steps"][0].update(value="{other}"), "value must be exactly"),
        (lambda d: d["steps"][2]["target"].update(el_id="e1"), "target.el_id"),
        (lambda d: d["inputs"].pop(), "inputs must be exactly"),
        (lambda d: d["steps"][1].update(optional=None), "optional.mode"),
    ]:
        draft = good_draft(design)
        mutate(draft)
        assert any(needle in p for p in check_draft(design, draft)), needle


# ---- what the code builds from what the model named ----------------------------------------------------------------------------

def test_the_workflow_is_built_by_the_code_with_selectors_risk_and_mode_it_chose_not_the_model():
    trace = merged()
    design = good_design(trace)
    workflow, warnings = assemble(trace, design, good_draft(design), "tra-cuu", 1, "Tra cứu tài khoản")
    validate_workflow(workflow)
    assert workflow["schema_version"] == 3 and workflow["engine"] == "ie"
    steps = {s["id"].split("_", 1)[0]: s for s in workflow["steps"]}
    assert steps["s3"]["target"]["selectors"] == ["frame=main|id=btnFind"] and steps["s3"]["risk"] == "read" and steps["s3"]["mode"] == "auto"
    assert steps["s4"]["action"] == "read_fields" and steps["s4"]["save_as"] == "kq" and "target" not in steps["s4"]
    assert steps["s5"]["value"] == "{kq.grid.0.so_tk}"                                  # the value comes from the screen
    assert steps["s2"]["optional"] == {"mode": "if_different"}
    role = next(i for i in workflow["inputs"] if i["name"] == "role")
    assert role["required"] is False and not any(i["name"] == "user_account" and "required" in i for i in workflow["inputs"])
    assert any("tuỳ chọn" in w for w in warnings)


def test_a_step_a_person_must_do_ends_the_workflow_there_like_the_rule_learner_does():
    trace = merged()
    for session in trace["sessions"]:
        for event in session["events"]:
            if event["el_id"] == "e5":
                event["screen"] = "Phê duyệt"
    trace["elements"]["e5"]["label"] = "Duyệt"
    design = good_design(trace)
    workflow, warnings = assemble(trace, design, good_draft(design), "x", 1, None)
    assert [s["action"] for s in workflow["steps"]][-1] == "fill" and any("chỉ người" in w for w in warnings)


# ---- Codie as a real process -----------------------------------------------------------------------------------------------------

FAKE = r'''
import json, os, sys
mode = sys.argv[sys.argv.index("--mode") + 1]
queue = os.environ["FAKE_CODIE_QUEUE"]
answers = json.load(open(queue, encoding="utf-8"))
print(sys.argv[sys.argv.index("-p") + 1][:80])
print("[task] active 77")
step = answers.pop(0)
json.dump(answers, open(queue, "w", encoding="utf-8"))
if "raw" in step:
    print(step["raw"])
else:
    seen = {"mode": mode, "files": sorted(os.listdir("."))}
    open(os.environ["FAKE_CODIE_QUEUE"] + ".seen", "a", encoding="utf-8").write(json.dumps(seen) + "\n")
    print("<<<MV_RESULT\n" + json.dumps(step["result"]) + "\nMV_RESULT>>>")
'''


@pytest.fixture
def fake(tmp_path, monkeypatch):
    script = tmp_path / "fake_codie.py"
    script.write_text(FAKE, encoding="utf-8")
    queue = tmp_path / "queue.json"
    monkeypatch.setenv("FAKE_CODIE_QUEUE", str(queue))

    def script_answers(answers):
        queue.write_text(json.dumps(answers), encoding="utf-8")
        return CodieFlowBuilder(codie_cli.Settings(argv0=[sys.executable, str(script)], timeout=60), sleep=lambda s: None)

    return script_answers


def test_two_stages_through_a_real_process_build_a_valid_workflow(fake, tmp_path):
    design = good_design(merged())
    builder = fake([{"result": design}, {"result": good_draft(design)}])
    result = builder.build(three_traces(), "tra-cuu", 1, "Tra cứu tài khoản")
    validate_workflow(result.workflow)
    assert result.method == "codie" and [c["mode"] for c in result.calls] == ["rookie-design", "rookie-workflow"] and all(c["ok"] for c in result.calls)
    seen = [json.loads(x) for x in (tmp_path / "queue.json.seen").read_text(encoding="utf-8").splitlines()]
    assert seen[0]["files"] == ["trace.json"] and seen[1]["files"] == ["design.json", "trace.json"]      # stage 2 reads the approved design


def test_a_wrong_answer_is_sent_back_with_the_problems_and_the_second_try_is_used(fake):
    design = good_design(merged())
    bad = copy.deepcopy(design)
    bad["steps"][2]["el_id"] = "e99"
    builder = fake([{"result": bad}, {"result": design}, {"result": good_draft(design)}])
    result = builder.build(three_traces(), "w", 1)
    assert [c["ok"] for c in result.calls] == [False, True, True]
    assert "chưa đạt kiểm chứng" in result.calls[0]["note"] and "đạt kiểm chứng" in result.calls[1]["note"]


def test_after_the_tries_are_used_up_the_builder_gives_up_with_the_first_problem(fake):
    design = good_design(merged())
    bad = copy.deepcopy(design)
    bad["steps"][2]["el_id"] = "e99"
    builder = fake([{"result": bad}] * 3)
    with pytest.raises(FlowBuildError) as error:
        builder.build(three_traces(), "w", 1)
    assert "e99" in error.value.reason and len(error.value.calls) == 3


@pytest.mark.parametrize("raw,needle", [("nothing here", "không có khối kết quả"),
                                        (codie_cli.OPEN + "\n{broken\n" + codie_cli.CLOSE, "không phải JSON")])
def test_an_answer_without_a_usable_block_ends_the_build_in_plain_words(fake, raw, needle):
    builder = fake([{"raw": raw}])
    with pytest.raises(FlowBuildError) as error:
        builder.build(three_traces(), "w", 1)
    assert needle in error.value.reason


def test_a_missing_codie_command_is_a_plain_reason_and_not_a_crash():
    builder = CodieFlowBuilder(codie_cli.Settings(command="no-such-codie-command-xyz"))
    assert not builder.available
    with pytest.raises(FlowBuildError) as error:
        builder.build(three_traces(), "w", 1)
    assert "no-such-codie-command-xyz" in error.value.reason


def test_a_trace_that_still_holds_a_long_number_is_never_sent():
    traces = three_traces()
    traces[0]["elements"]["e1"]["label"] = "Tai khoan 01234567890123"
    with pytest.raises(FlowBuildError) as error:
        CodieFlowBuilder(codie_cli.Settings(argv0=["does-not-run"])).build(traces, "w", 1)
    assert "chưa che" in error.value.reason


def test_the_model_can_be_turned_off_by_the_environment(monkeypatch):
    monkeypatch.setenv("ROOKIE_CODIE_ENABLED", "0")
    assert not CodieFlowBuilder().available
