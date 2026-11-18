import json

import pytest

from app.learner import LearnError, learn, normalize, slug
from app.schemas import validate_workflow
from tests.helpers import java_transfer_session, web_report_session

DAYS = ["2026-11-03", "2026-11-10", "2026-11-12"]


def web_sessions():
    return [web_report_session(f"s{i}", day) for i, day in enumerate(DAYS)]


def test_web_workflow_gets_a_date_parameter_from_three_sessions():
    workflow, warnings = learn(web_sessions(), "doi-chieu")
    validate_workflow(workflow)
    assert workflow["status"] == "draft" and workflow["engine"] == "web"
    assert workflow["inputs"] == [{"name": "ngay_bao_cao", "type": "date", "label": "Ngày báo cáo"}]
    fill = next(step for step in workflow["steps"] if step["action"] == "fill")
    assert fill["value"] == "{ngay_bao_cao}"
    assert warnings == []


def test_a_value_that_never_changes_stays_constant():
    sessions = web_sessions()
    for events in sessions:
        events[1]["value"] = "2026-11-10"
    workflow, _ = learn(sessions, "doi-chieu")
    assert workflow["inputs"] == []
    assert next(step for step in workflow["steps"] if step["action"] == "fill")["value"] == "2026-11-10"


def test_one_session_still_learns_but_warns():
    workflow, warnings = learn([web_report_session("s0", "2026-11-10")], "doi-chieu")
    assert workflow["inputs"][0]["name"] == "ngay_bao_cao"
    assert any("Chỉ có 1 phiên" in w for w in warnings)
    assert any("một giá trị mẫu" in w for w in warnings)


def test_java_transfer_learns_parameters_by_field_class_and_stops_before_nothing_it_may_do():
    sessions = [java_transfer_session(f"s{i}") for i in range(3)]
    workflow, warnings = learn(sessions, "chuyen-tien")
    validate_workflow(workflow)
    assert workflow["engine"] == "java"
    assert [(i["name"], i.get("value_class")) for i in workflow["inputs"]] == [
        ("so_cif_hoac_cccd", "cif_number"),
        ("tai_khoan_chuyen", "account_number"),
        ("tai_khoan_nhan", "account_number"),
        ("so_tien", "amount"),
    ]
    by_label = {step["target"]["label"]: step for step in workflow["steps"]}
    assert by_label["Loại tiền"]["value"] == "VND"  # same in all sessions: constant, not a parameter
    assert by_label["Gửi duyệt"]["risk"] == "money" and by_label["Gửi duyệt"]["mode"] == "approve"
    assert by_label["Tra cứu CIF"]["risk"] == "read" and by_label["Tra cứu CIF"]["mode"] == "auto"
    assert warnings == []


def test_parameters_carry_the_caption_the_gdv_sees_on_screen():
    sessions = [java_transfer_session(f"s{i}") for i in range(3)]
    workflow, _ = learn(sessions, "chuyen-tien")
    assert [i["label"] for i in workflow["inputs"]] == ["Số CIF hoặc CCCD", "Tài khoản chuyển", "Tài khoản nhận", "Số tiền"]


def test_sensitive_values_never_reach_the_workflow():
    sessions = [java_transfer_session(f"s{i}") for i in range(3)]
    dumped = json.dumps(learn(sessions, "chuyen-tien")[0], ensure_ascii=False)
    assert "00103840" not in dumped and "001012345678" not in dumped


def test_a_human_only_step_ends_the_workflow_with_a_warning():
    sessions = []
    for i in range(3):
        events = java_transfer_session(f"s{i}")
        last = dict(events[-1], seq=len(events), url="Mock TPSS - Phê duyệt")
        last["target"] = {"selectors": ["role=push button[name='Duyệt']"], "label": "Duyệt", "tag": "push button"}
        sessions.append(events + [last])
    workflow, warnings = learn(sessions, "chuyen-tien")
    assert workflow["steps"][-1]["target"]["label"] == "Gửi duyệt"
    assert all(step["target"]["label"] != "Duyệt" for step in workflow["steps"])
    assert any("chỉ người được thực hiện" in w for w in warnings)


def test_sessions_that_take_different_paths_are_refused_not_merged():
    sessions = [java_transfer_session("s0"), java_transfer_session("s1", extra_click=True), java_transfer_session("s2")]
    with pytest.raises(LearnError) as error:
        learn(sessions, "chuyen-tien")
    assert "Phiên ghi 2 khác phiên 1 ở bước 3" in str(error.value)


def test_mixed_engines_and_empty_input_are_refused():
    with pytest.raises(LearnError):
        learn([web_report_session("a", DAYS[0]), java_transfer_session("b")], "x")
    with pytest.raises(LearnError):
        learn([], "x")


def test_normalize_merges_repeated_edits_and_repeated_clicks():
    events = web_report_session("s", "2026-11-03")
    typed = dict(events[1], seq=2, value="2026-11-04")
    events = events[:2] + [typed, dict(events[2], seq=3), dict(events[2], seq=4)]
    merged = normalize(events)
    assert [e["type"] for e in merged] == ["click", "input", "click"]
    assert merged[1]["value"] == "2026-11-04"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Tài khoản chuyển", "tai_khoan_chuyen"), ("Đơn vị", "don_vi"), ("2 lần", "p_2_lan"), ("???", "gia_tri")],
)
def test_slug_makes_valid_input_names(text, expected):
    assert slug(text) == expected


def login_session(session_id: str):
    from tests.helpers import _event

    screen = "Mock TPSS - Đăng nhập"
    return [
        _event("java", session_id, 0, "input", screen, ["role=text[name='Tên đăng nhập']"], "Tên đăng nhập", "text", None, "username", []),
        _event("java", session_id, 1, "submit", screen, ["role=password text[name='Mật khẩu']"], "Mật khẩu", "password text", None, None, []),
    ]


def test_enter_in_a_field_is_learned_as_its_own_step_and_is_safe_by_rule():
    workflow, _ = learn([login_session(f"s{i}") for i in range(3)], "dang-nhap")
    validate_workflow(workflow)
    assert [(s["action"], s["target"]["label"], s["risk"], s["mode"]) for s in workflow["steps"]] == [
        ("fill", "Tên đăng nhập", "read", "auto"),
        ("submit", "Mật khẩu", "read", "auto"),
    ]
    assert workflow["inputs"] == [{"name": "ten_dang_nhap", "type": "string", "label": "Tên đăng nhập", "value_class": "username"}]


def _ie_session(session_id: str, cif: str) -> list[dict]:
    base = {"schema_version": 2, "engine": "ie", "session_id": session_id, "ts": "2026-11-16T03:00:00.000Z", "url": "TouchPoint/Main", "api_calls": [], "screenshot": None}
    field = {"selectors": ["frame=desktopFrame/rtop/main/fraProfileArea|id=txtCustomerId"], "label": "Mã khách hàng", "tag": "input"}
    button = lambda label, ident: {"selectors": [f"frame=desktopFrame/rtop/main/fraProfileArea|id={ident}"], "label": label, "tag": "button"}
    return [
        {**base, "seq": 0, "type": "input", "target": field, "value": None, "value_class": "cif_number"},
        {**base, "seq": 1, "type": "click", "target": button("XEM CHỮ KÝ", "btnVerifySignature"), "value": None, "value_class": None},
        {**base, "seq": 2, "type": "click", "target": button("LƯU", "btnSave"), "value": None, "value_class": None},
    ]


def test_learning_an_ie_recording_gives_a_version_2_workflow_with_the_save_waiting_for_approval():
    from app.learner import learn

    workflow, _ = learn([_ie_session("a", "1"), _ie_session("b", "2"), _ie_session("c", "3")], "tra-cif-ie")
    assert workflow["schema_version"] == 2 and workflow["engine"] == "ie"
    assert [step["risk"] for step in workflow["steps"]] == ["read", "read", "write"]
    assert workflow["steps"][2]["mode"] == "approve"
    assert workflow["inputs"][0]["value_class"] == "cif_number"


# ---- task 4.13: a field typed twice with other fields in between is one step; a button is the same button in any language ----

def ie_event(seq, kind, element, label=None, value=None, value_class=None, session="s"):
    return {
        "schema_version": 2, "engine": "ie", "session_id": session, "seq": seq, "ts": "2026-11-16T09:00:00.000Z", "type": kind,
        "url": "TouchPoint/Main",
        "target": {"selectors": [f"frame=top|id={element}", f"frame=top|label={label}"] if label else [f"frame=top|id={element}"],
                   "label": label, "tag": "button" if kind == "click" else "input"},
        "value": value, "value_class": value_class, "api_calls": [],
    }


def test_a_field_typed_twice_with_another_field_between_is_one_step_with_the_last_value():
    events = [ie_event(0, "input", "txtUser", "User Account", value_class="username"),
              ie_event(1, "input", "txtBranch", "Chi nhanh", value="HN01"),
              ie_event(2, "input", "txtUser", "User Account", value_class="username"),
              ie_event(3, "click", "btnOk", "OK")]
    merged = normalize(events)
    assert [e["target"]["selectors"][0] for e in merged] == ["frame=top|id=txtUser", "frame=top|id=txtBranch", "frame=top|id=btnOk"]


def test_a_click_between_two_edits_of_a_field_keeps_both_because_the_page_may_have_changed():
    events = [ie_event(0, "input", "txtUser", "User Account", value="a"),
              ie_event(1, "click", "btnNext", "Next"),
              ie_event(2, "input", "txtUser", "User Account", value="b")]
    assert len(normalize(events)) == 3


def test_the_same_button_with_a_different_caption_is_the_same_step():
    english = [ie_event(0, "input", "txtUser", "User Account", value_class="username"), ie_event(1, "click", "btnLogoff", "LOGOFF")]
    vietnamese = [ie_event(0, "input", "txtUser", "User Account", value_class="username", session="s2"), ie_event(1, "click", "btnLogoff", "ĐĂNG XUẤT", session="s2")]
    workflow, _ = learn([english, vietnamese], "wf-logoff")
    assert len(workflow["steps"]) == 2


# ---- tasks 4.15 and 4.16: steps that are not in every recording (the role the teller did not need to choose) ----

def signin_run(session, role=None, confirm=False):
    events = [ie_event(0, "input", "txtUser", "User Account", value_class="username", session=session)]
    if role:
        events.append(ie_event(len(events), "select", "currentRole", "Role", value=role, session=session))
    events.append(ie_event(len(events), "click", "btnOk", "OK", session=session))
    if confirm:
        events.append(ie_event(len(events), "click", "btnClose", "Đóng", session=session))
    return events


def test_a_choice_made_in_some_recordings_only_becomes_an_optional_step_with_an_optional_input():
    workflow, warnings = learn([signin_run("a", role="KSV"), signin_run("b"), signin_run("c", role="GDV")], "wf-signin")
    assert workflow["schema_version"] == 3
    assert [s["action"] for s in workflow["steps"]] == ["fill", "select", "click"]
    role_step = workflow["steps"][1]
    assert role_step["optional"] == {"mode": "if_different"}
    role_input = next(i for i in workflow["inputs"] if i["name"] == role_step["value"].strip("{}"))
    assert role_input["required"] is False
    assert all("optional" not in s for s in (workflow["steps"][0], workflow["steps"][2]))   # what is in every recording stays required
    assert any("tuỳ chọn" in w and "2/3" in w for w in warnings)


def test_a_read_only_click_that_appears_sometimes_is_a_click_if_the_element_is_there():
    workflow, _ = learn([signin_run("a", confirm=True), signin_run("b"), signin_run("c", confirm=True)], "wf-confirm")
    assert workflow["steps"][-1]["optional"]["mode"] == "if_present"


def test_recordings_that_are_alike_do_not_get_optional_steps_and_keep_their_old_version():
    workflow, _ = learn([signin_run("a", role="KSV"), signin_run("b", role="KSV"), signin_run("c", role="KSV")], "wf-same")
    assert workflow["schema_version"] == 2 and all("optional" not in s for s in workflow["steps"])


def test_a_write_step_missing_from_some_recordings_is_refused_never_made_optional():
    sessions = [signin_run("a"), signin_run("b")]
    sessions[0].insert(1, ie_event(9, "click", "btnLuu", "Lưu", session="a"))
    with pytest.raises(LearnError) as error:
        learn(sessions + [signin_run("c")], "wf-write")
    assert "Lưu" in str(error.value) or "ghi" in str(error.value)


def test_the_same_actions_in_a_different_order_are_refused_not_guessed():
    a = [ie_event(0, "click", "btnA", "A", session="a"), ie_event(1, "click", "btnB", "B", session="a")]
    b = [ie_event(0, "click", "btnB", "B", session="b"), ie_event(1, "click", "btnA", "A", session="b")]
    with pytest.raises(LearnError) as error:
        learn([a, b], "wf-order")
    assert "thứ tự" in str(error.value)


def test_recordings_with_too_little_in_common_are_not_one_task():
    a = [ie_event(i, "click", f"b{i}", f"B{i}", session="a") for i in range(6)]
    b = [ie_event(0, "click", "b0", "B0", session="b")] + [ie_event(i, "click", f"x{i}", f"X{i}", session="b") for i in range(1, 6)]
    with pytest.raises(LearnError) as error:
        learn([a, b], "wf-different")
    assert "cùng một việc" in str(error.value)
