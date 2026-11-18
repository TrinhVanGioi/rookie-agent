"""Tasks 4.39 and 4.40: the IE driver of the runner. A fake bridge answers; what the driver turns the answers into is tested here."""

import pytest

from rookie_agent import runner
from rookie_agent.ie.driver import IeDriver


class FakeBridge:
    def __init__(self, answers, host="uat.example", title="TouchPoint - Home"):
        self.answers, self.calls, self.host, self.title = list(answers), [], host, title

    def bind(self, tab_id):
        self.bound = tab_id
        return {"ok": True}

    def tabs(self):
        return [{"id": 3, "title": self.title, "host": self.host}]

    def act(self, op, selectors, value=""):
        self.calls.append((op, list(selectors), value))
        return self.answers.pop(0)


def driver(*answers, **kw):
    bridge = FakeBridge(answers, **kw)
    return IeDriver(bridge, 3), bridge


class LocatingBridge(FakeBridge):
    def __init__(self, frames, answers=({"ok": True, "value": "v"},)):
        super().__init__(answers)
        self.frames = frames

    def locate(self, selectors):
        return self.frames


def test_the_action_goes_to_the_one_element_the_evidence_points_at():
    bridge = LocatingBridge([{"frame": "main", "probes": [{"kind": "id", "m": []}, {"kind": "label", "m": [41]}, {"kind": "pos", "m": [41]}], "fields": {"41": 1}}])
    IeDriver(bridge, 3).fill(["frame=main|id=old", "frame=main|label=So CIF", "frame=main|input[2]"], "v")
    assert bridge.calls == [("fill", ["frame=main|src=41"], "v")]


@pytest.mark.parametrize("frames,code", [
    ([{"frame": "main", "probes": [{"kind": "label", "m": [41]}, {"kind": "pos", "m": [7]}], "fields": {"41": 1, "7": 1}}], "low_confidence"),
    ([{"frame": "main", "probes": [{"kind": "label", "m": [41, 7]}], "fields": {"41": 1, "7": 1}}], "ambiguous"),
])
def test_weak_or_split_evidence_stops_to_ask_and_nothing_is_done(frames, code):
    bridge = LocatingBridge(frames)
    with pytest.raises(runner.NeedsHelp) as stopped:
        IeDriver(bridge, 3).fill(["frame=main|label=So CIF", "frame=main|input[2]"], "v")
    assert stopped.value.code == code and bridge.calls == []


def test_no_frame_with_the_selectors_is_not_found():
    with pytest.raises(runner.ElementNotFound):
        IeDriver(LocatingBridge([{"frame": "other", "probes": [{"kind": "id", "m": [1]}], "fields": {}}]), 3).click(["frame=main|id=x"])


def test_a_missing_element_is_the_runners_own_not_found():
    d, _ = driver({"ok": False, "error": "not_found"})
    with pytest.raises(runner.ElementNotFound):
        d.click(["frame=top|id=x"])


@pytest.mark.parametrize("error,code", [("ambiguous", "ambiguous"), ("disabled", "disabled"), ("secret", "secret"),
                                       ("no_option", "no_option"), ("readonly", "readonly")])
def test_what_the_agent_must_not_guess_stops_the_run_to_ask(error, code):
    d, _ = driver({"ok": False, "error": error, "options": ["A", "B"]})
    with pytest.raises(runner.NeedsHelp) as stopped:
        d.fill(["frame=top|id=x"], "v")
    assert stopped.value.code == code and stopped.value.message


def test_a_value_the_page_did_not_keep_is_not_a_success():
    d, _ = driver({"ok": True, "value": "something else"})
    with pytest.raises(runner.NeedsHelp) as stopped:
        d.fill(["frame=top|id=x"], "0123456789")
    assert stopped.value.code == "value_not_set"
    assert "0123456789" not in stopped.value.message and "something else" not in stopped.value.message   # a value never appears in a message


def test_a_page_that_only_reformats_what_was_typed_is_accepted():
    d, _ = driver({"ok": True, "value": "5.000.000"}, {"ok": True, "value": "  abc "})
    d.fill(["frame=top|id=x"], "5000000")
    d.fill(["frame=top|id=y"], "abc")


def test_a_list_must_end_on_the_asked_entry():
    d, _ = driver({"ok": True, "value": "s", "text": "SAV"}, {"ok": True, "value": "d", "text": "DDA"})
    d.select(["frame=top|id=k"], "s")
    with pytest.raises(runner.NeedsHelp):
        d.select(["frame=top|id=k"], "s")


def test_read_value_returns_the_text_and_exists_is_a_yes_or_no():
    d, _ = driver({"ok": True, "value": "NGUYEN"}, {"ok": False, "error": "not_found"}, {"ok": True})
    assert d.read_value(["frame=top|id=n"]) == "NGUYEN"
    assert d.exists(["frame=top|id=n"]) is False and d.exists(["frame=top|id=n"]) is True


def test_a_local_host_is_a_mock_and_a_bank_host_is_not():
    local, _ = driver(host="localhost", title="Chuyen tien")
    bank, _ = driver(host="uat2bds.vietinbank.vn", title="TouchPoint")
    assert runner._is_mock(local.window_title()) and not runner._is_mock(bank.window_title())
    assert "Chuyen tien" in local.window_title()


def test_the_runner_accepts_a_learned_ie_flow_and_still_refuses_the_wrong_version():
    flow = {"schema_version": 2, "engine": "ie", "id": "f", "version": 1, "status": "approved", "inputs": [],
            "steps": [{"id": "s1", "action": "click", "target": {"selectors": ["frame=top|id=b"]}, "risk": "read", "mode": "auto"}]}
    runner.check_workflow(flow, {}, sandbox=False, engine="ie", versions=(2, 3))
    with pytest.raises(runner.WorkflowRefused):
        runner.check_workflow({**flow, "schema_version": 1}, {}, sandbox=False, engine="ie", versions=(2, 3))
    with pytest.raises(runner.WorkflowRefused):
        runner.check_workflow(flow, {}, sandbox=False)       # the Java runner still refuses an IE flow


def test_a_step_that_needs_help_ends_the_run_with_the_reason_and_runs_nothing_after_it():
    flow = {"schema_version": 2, "engine": "ie", "id": "f", "version": 1, "status": "approved", "inputs": [{"name": "acct", "type": "string"}],
            "steps": [{"id": "s1", "action": "fill", "value": "{acct}", "target": {"selectors": ["frame=top|id=a"]}, "risk": "read", "mode": "auto"},
                      {"id": "s2", "action": "click", "target": {"selectors": ["frame=top|id=b"]}, "risk": "read", "mode": "auto"}]}
    d, bridge = driver({"ok": False, "error": "ambiguous", "count": 2})
    result = runner.run_workflow(flow, {"acct": "0123456789"}, d, runner.AutoController(), engine="ie", versions=(2, 3))
    assert result["status"] == "needs_help" and len(bridge.calls) == 1
    assert "0123456789" not in str(result)


# ---- signing in is the teller's own step: the agent never types a password, so it never presses Enter in that field either ----

def _signin_flow():
    return {"schema_version": 2, "engine": "ie", "id": "f", "version": 1, "status": "approved",
            "inputs": [{"name": "user", "type": "string"}],
            "steps": [{"id": "s1", "action": "fill", "value": "{user}", "target": {"selectors": ["frame=top|id=txtUser"], "label": "User Account"}, "risk": "read", "mode": "auto"},
                      {"id": "s2", "action": "submit", "target": {"selectors": ["frame=top|id=txtPw", "frame=top|name=txtPw"], "label": "Password"}, "risk": "read", "mode": "auto"},
                      {"id": "s3", "action": "click", "target": {"selectors": ["frame=top|id=btnOk"], "label": "OK"}, "risk": "read", "mode": "auto"}]}


class _Person:
    def __init__(self, go=True):
        self.go, self.asked, self.log = go, [], []

    def approve(self, step, index, total):
        return True

    def review(self, step, index, total):
        self.asked.append((step["id"], bool(step.get("manual"))))
        return self.go

    def progress(self, step_id, status, detail):
        self.log.append((step_id, status))


def test_the_step_that_presses_enter_in_the_password_field_waits_for_the_teller_and_the_agent_does_nothing_there():
    d, bridge = driver({"ok": True}, {"ok": True, "value": "teller01"}, {"ok": True})
    person = _Person()
    result = runner.run_workflow(_signin_flow(), {"user": "teller01"}, d, person, engine="ie", versions=(2, 3))
    assert result["status"] == "finished"
    assert person.asked == [("s2", True)]                                         # the person is asked, marked as a manual step
    assert [c[0] for c in bridge.calls] == ["exists", "fill", "click"]            # no submit was sent to the page


def test_a_teller_who_does_not_go_on_ends_the_run_there():
    d, bridge = driver({"ok": True}, {"ok": True, "value": "teller01"})
    result = runner.run_workflow(_signin_flow(), {"user": "teller01"}, d, _Person(go=False), engine="ie", versions=(2, 3))
    assert result["status"] == "rejected" and len(bridge.calls) == 2


# ---- tasks 4.17 and 4.19: optional steps ----

def _optional_flow():
    return {"schema_version": 3, "engine": "ie", "id": "f", "version": 1, "status": "approved",
            "inputs": [{"name": "role", "type": "string", "required": False}],
            "steps": [{"id": "s1", "action": "select", "value": "{role}", "optional": {"mode": "if_different"},
                       "target": {"selectors": ["frame=top|id=currentRole"], "label": "Role"}, "risk": "read", "mode": "auto"},
                      {"id": "s2", "action": "click", "optional": {"mode": "if_present", "wait_ms": 50},
                       "target": {"selectors": ["frame=top|id=btnClose"], "label": "Dong"}, "risk": "read", "mode": "auto"},
                      {"id": "s3", "action": "click", "target": {"selectors": ["frame=top|id=btnOk"], "label": "OK"}, "risk": "read", "mode": "auto"}]}


class _ByElement(FakeBridge):
    """Answers by element: the close button is not on the screen, everything else is."""

    def act(self, op, selectors, value=""):
        self.calls.append((op, list(selectors), value))
        return {"ok": False, "error": "not_found"} if "btnClose" in selectors[0] else {"ok": True}


def test_an_optional_list_left_empty_is_not_touched_and_a_missing_optional_button_is_skipped():
    bridge = _ByElement([])
    d = IeDriver(bridge, 3)
    result = runner.run_workflow(_optional_flow(), {}, d, runner.AutoController(), engine="ie", versions=(2, 3))
    assert result["status"] == "finished"
    assert all(c[0] == "exists" for c in bridge.calls[:-1]) and bridge.calls[-1][:2] == ("click", ["frame=top|id=btnOk"])
    assert not any(c[0] == "select" for c in bridge.calls)                          # the empty list was not touched
    assert [(s["id"], s["status"]) for s in result["steps"]] == [("s1", "skipped"), ("s2", "skipped"), ("s3", "done")]


def test_an_optional_list_with_a_value_is_chosen_and_an_optional_button_that_is_there_is_pressed():
    d, bridge = driver({"ok": True, "value": "ksv", "text": "KSV"}, {"ok": True}, {"ok": True}, {"ok": True})
    result = runner.run_workflow(_optional_flow(), {"role": "ksv"}, d, runner.AutoController(), engine="ie", versions=(2, 3))
    assert result["status"] == "finished"
    assert [c[0] for c in bridge.calls] == ["select", "exists", "click", "click"]


def test_the_runner_does_not_ask_for_an_input_that_is_not_required():
    runner.check_workflow(_optional_flow(), {}, sandbox=False, engine="ie", versions=(2, 3))
    assert runner.required_inputs(_optional_flow()) == []


# ---- UAT is for steps that only read: a step that writes runs on a mock page only (unless the owner turns the switch on) ----

def _write_flow():
    return {"schema_version": 2, "engine": "ie", "id": "f", "version": 1, "status": "approved", "inputs": [],
            "steps": [{"id": "s1", "action": "click", "target": {"selectors": ["frame=top|id=find"]}, "risk": "read", "mode": "auto"},
                      {"id": "s2", "action": "click", "target": {"selectors": ["frame=top|id=save"]}, "risk": "write", "mode": "approve"}]}


def test_a_write_step_is_refused_on_a_page_that_is_not_a_mock_and_nothing_after_the_reads_is_done():
    d, bridge = driver({"ok": True}, host="uat.example")
    person = runner.AutoController()
    result = runner.run_workflow(_write_flow(), {}, d, person, engine="ie", versions=(2, 3))
    assert result["status"] == "refused" and len(bridge.calls) == 1             # the read step ran; the write step did not
    assert "UAT" in result["message"] or "mock" in result["message"]


def test_a_write_step_runs_on_a_mock_page_and_the_owner_can_switch_the_rule_off_for_a_real_page():
    d, bridge = driver({"ok": True}, {"ok": True}, host="localhost")
    assert runner.run_workflow(_write_flow(), {}, d, runner.AutoController(), engine="ie", versions=(2, 3))["status"] == "finished"
    d, bridge = driver({"ok": True}, {"ok": True}, host="uat.example")
    assert runner.run_workflow(_write_flow(), {}, d, runner.AutoController(), engine="ie", versions=(2, 3), allow_write_on_real=True)["status"] == "finished"


# ---- reading the screen into a variable and calling its values in later steps ----

def _data_flow(call="{kq.grid.1.so_tk}"):
    return {"schema_version": 3, "engine": "ie", "id": "f", "version": 1, "status": "approved",
            "inputs": [{"name": "acct", "type": "string"}],
            "steps": [{"id": "s1", "action": "fill", "value": "{acct}", "target": {"selectors": ["frame=main|id=txtAcct"]}, "risk": "read", "mode": "auto"},
                      {"id": "s2", "action": "read_fields", "save_as": "kq", "risk": "read", "mode": "auto"},
                      {"id": "s3", "action": "fill", "value": call, "target": {"selectors": ["frame=main|id=txtCopy"]}, "risk": "read", "mode": "auto"}]}


class _Screen(FakeBridge):
    def __init__(self, frames):
        super().__init__([])
        self.frames = frames

    def act(self, op, selectors, value=""):
        self.calls.append((op, list(selectors), value))
        return {"ok": True, "value": value}

    def read(self):
        return self.frames


def _result_screen():
    import json as _json

    return [_json.dumps({"frame": "main", "title": "T", "fields": [{"label": "So tai khoan", "value": "0123"}],
                         "tables": [{"id": "grid", "headers": ["So TK", "Loai"], "rows": [["0123", "DDA"], ["9002", "SAV"]], "row_count": 2}], "messages": []})]


def test_a_value_read_from_the_screen_is_called_by_a_later_step():
    bridge = _Screen(_result_screen())
    result = runner.run_workflow(_data_flow(), {"acct": "0123"}, IeDriver(bridge, 3), runner.AutoController(), engine="ie", versions=(2, 3))
    assert result["status"] == "finished", result
    assert bridge.calls[-1] == ("fill", ["frame=main|id=txtCopy"], "9002")        # the second row's account number, found by its path


def test_a_name_that_is_not_on_the_screen_stops_the_run_and_never_types_a_guess():
    bridge = _Screen(_result_screen())
    result = runner.run_workflow(_data_flow("{kq.grid.5.so_tk}"), {"acct": "0123"}, IeDriver(bridge, 3), runner.AutoController(), engine="ie", versions=(2, 3))
    assert result["status"] == "needs_help" and not any(c[2] == "" for c in bridge.calls[1:])
    assert bridge.calls[-1][0] == "fill" and len(bridge.calls) == 1               # only the first step acted


def test_a_variable_read_by_no_step_is_refused_before_anything_runs():
    flow = _data_flow()
    flow["steps"].pop(1)
    result = runner.run_workflow(flow, {"acct": "0123"}, IeDriver(_Screen(_result_screen()), 3), runner.AutoController(), engine="ie", versions=(2, 3))
    assert result["status"] == "refused" and "kq" in result["message"]


def test_the_values_read_never_reach_the_result_or_the_steps_log():
    bridge = _Screen(_result_screen())
    person = runner.AutoController()
    result = runner.run_workflow(_data_flow(), {"acct": "0123"}, IeDriver(bridge, 3), person, engine="ie", versions=(2, 3))
    assert "9002" not in str(result) and "9002" not in str(person.log)


def test_a_teller_already_signed_in_skips_the_sign_in_steps_and_the_ok_that_is_not_there(monkeypatch):
    monkeypatch.setattr(runner, "LOGIN_CHECK_SECONDS", 0)
    flow = _signin_flow()
    flow["steps"].append({"id": "s4", "action": "click", "target": {"selectors": ["frame=top|id=btnFind"], "label": "Tìm"}, "risk": "read", "mode": "auto"})
    missing = {"ok": False, "error": "not_found"}
    d, bridge = driver(missing, missing, {"ok": True})
    person = _Person()
    result = runner.run_workflow(flow, {"user": ""}, d, person, engine="ie", versions=(2, 3))
    assert result["status"] == "finished" and person.asked == []                 # no sign-in question, no user name needed
    assert [(c[0], c[1][0]) for c in bridge.calls] == [("exists", "frame=top|id=txtUser"), ("exists", "frame=top|id=btnOk"), ("click", "frame=top|id=btnFind")]
    assert [s["status"] for s in result["steps"]][:3] == ["skipped"] * 3


def test_a_button_still_locked_right_after_the_fill_is_waited_for_not_unlocked():
    flow = {"schema_version": 2, "engine": "ie", "id": "f", "version": 1, "status": "approved", "inputs": [],
            "steps": [{"id": "s1", "action": "click", "target": {"selectors": ["frame=top|id=btnFind"]}, "risk": "read", "mode": "auto"}]}
    locked = {"ok": False, "error": "disabled"}
    d, bridge = driver(locked, locked, {"ok": True})
    result = runner.run_workflow(flow, {}, d, runner.AutoController(), engine="ie", versions=(2, 3))
    assert result["status"] == "finished" and [c[0] for c in bridge.calls] == ["click"] * 3
