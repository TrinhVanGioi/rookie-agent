import json

from rookie_agent.recorder import Recorder
from rookie_agent.selectors import Element, Step

WINDOW = "Mock TPSS - Chuyển tiền"
SECRETS = ["demo-only-1234", "001012345678", "002098765432", "5000000", "Nguyễn Văn An"]


def element(role: str, name: str, index: int = 0) -> Element:
    path = (Step("frame", -1), Step("root pane", 0), Step("panel", 0), Step(role, index))
    return Element(role, name, path, WINDOW)


def recorder() -> Recorder:
    return Recorder(session_id="s-test", clock=lambda: "2026-11-12T09:15:03.000Z")


def typed(rec: Recorder, field: Element, value: str) -> None:
    """Simulate typing: one text change per character while the field has focus."""
    for end in range(1, len(value) + 1):
        rec.text_changed(field, value[:end], focused=True)
    rec.focus_lost(field)


def test_transfer_flow_produces_valid_events_without_sensitive_values(assert_valid_events):
    rec = recorder()
    typed(rec, element("text", "Tài khoản chuyển", 1), "001012345678")
    typed(rec, element("text", "Tài khoản nhận", 3), "002098765432")
    typed(rec, element("text", "Số tiền", 5), "5000000")
    rec.clicked(element("push button", "Gửi duyệt", 9))
    events = rec.stop()

    assert_valid_events(events)
    assert [e["type"] for e in events] == ["input", "input", "input", "click"]
    assert [e["value_class"] for e in events] == ["account_number", "account_number", "amount", None]
    assert all(e["value"] is None for e in events)
    assert all(e["engine"] == "java" and e["api_calls"] == [] and e["url"] == WINDOW for e in events)
    assert events[3]["target"]["selectors"][0] == "role=push button[name='Gửi duyệt']"
    dumped = json.dumps(events, ensure_ascii=False)
    assert not any(secret in dumped for secret in SECRETS)


def test_password_field_produces_no_event_at_all():
    rec = recorder()
    typed(rec, element("password text", "Mật khẩu"), "demo-only-1234")
    typed(rec, element("text", "Mật khẩu OTP"), "123456")
    rec.clicked(element("push button", "Đăng nhập"))
    events = rec.stop()
    assert [e["type"] for e in events] == ["click"]
    assert "demo-only-1234" not in json.dumps(events) and "123456" not in json.dumps(events)


def test_plain_field_keeps_its_value(assert_valid_events):
    rec = recorder()
    typed(rec, element("text", "Ngày báo cáo"), "2026-11-10")
    events = rec.stop()
    assert_valid_events(events)
    assert events[0]["value"] == "2026-11-10"
    assert events[0]["value_class"] is None


def test_typing_many_characters_gives_one_input_event():
    rec = recorder()
    typed(rec, element("text", "Ngày báo cáo"), "2026-11-10")
    assert len(rec.stop()) == 1


def test_unknown_field_is_treated_as_sensitive():
    rec = recorder()
    typed(rec, element("text", "Trường lạ"), "bí mật")
    events = rec.stop()
    assert events[0]["value"] is None
    assert events[0]["value_class"] == "unclassified"


def test_form_cleared_by_the_application_is_not_recorded():
    rec = recorder()
    # The application empties the field after a submit; the field does not have focus.
    rec.text_changed(element("text", "Số tiền"), "", focused=False)
    assert rec.stop() == []


def test_pending_edit_is_written_before_a_click_and_on_stop():
    rec = recorder()
    amount = element("text", "Số tiền", 5)
    rec.text_changed(amount, "1", focused=True)
    rec.clicked(element("push button", "Gửi duyệt", 9))  # no focus_lost seen yet
    assert [e["type"] for e in rec.events] == ["input", "click"]

    rec.text_changed(amount, "2", focused=True)
    assert [e["type"] for e in rec.stop()] == ["input", "click", "input"]


def test_clicks_on_non_actions_are_ignored():
    rec = recorder()
    for role in ["text", "panel", "label", "table", "page tab list", "scroll bar", "check box"]:
        rec.clicked(element(role, "x"))
    assert rec.stop() == []


def test_tab_toggle_and_row_selection(assert_valid_events):
    rec = recorder()
    rec.tab_selected(element("page tab", "Phê duyệt"))
    rec.toggled(element("check box", "Giao diện mới"))
    rec.row_selected(element("table", "Hàng chờ phê duyệt"), 2)
    rec.row_selected(element("table", "Hàng chờ phê duyệt"), -1)  # selection cleared
    events = rec.stop()
    assert_valid_events(events)
    assert [(e["type"], e["value"]) for e in events] == [("click", None), ("click", None), ("select", "2")]


def test_events_are_copies():
    rec = recorder()
    rec.clicked(element("push button", "Tải lại"))
    rec.events.clear()
    assert len(rec.stop()) == 1


def test_repeated_selection_reports_are_recorded_once():
    rec = recorder()
    table = element("table", "Hàng chờ phê duyệt")
    rec.row_selected(table, 0)
    rec.row_selected(table, 0)  # the bridge reports a selection twice
    rec.row_selected(table, 1)
    assert [e["value"] for e in rec.stop()] == ["0", "1"]


def test_combo_box_choice_keeps_plain_values_only(assert_valid_events):
    rec = recorder()
    rec.option_selected(element("combo box", "Loại tiền", 7), "USD", focused=True)
    rec.option_selected(element("combo box", "Loại tiền", 7), "USD", focused=True)
    rec.option_selected(element("combo box", "Tài khoản nguồn", 8), "001012345678", focused=True)
    events = rec.stop()
    assert_valid_events(events)
    assert [(e["type"], e["value"], e["value_class"]) for e in events] == [
        ("select", "USD", None),
        ("select", None, "account_number"),
    ]
    assert "001012345678" not in json.dumps(events)


def test_combo_box_reset_by_the_application_is_not_recorded():
    rec = recorder()
    rec.option_selected(element("combo box", "Loại tiền"), "VND", focused=False)
    assert rec.stop() == []


def test_a_press_reported_twice_is_one_click():
    now = [0.0]
    rec = Recorder(session_id="s-test", clock=lambda: "2026-11-12T09:15:03.000Z", monotonic=lambda: now[0])
    button = element("push button", "Gửi duyệt", 9)
    rec.clicked(button)   # focus gained while pressed
    now[0] = 0.05
    rec.clicked(button)   # state change to pressed
    now[0] = 2.0
    rec.clicked(button)   # a real second press, later
    rec.clicked(element("push button", "Tải lại", 3))  # another button right after: not a duplicate
    assert [e["target"]["label"] for e in rec.stop()] == ["Gửi duyệt", "Gửi duyệt", "Tải lại"]
