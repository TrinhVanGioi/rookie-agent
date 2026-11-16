"""What the agent keeps of the actions it sees in an Internet Explorer page (docs/design.md 3C).

The page-side recorder (page_recorder.js) hands over raw lines; this turns them into events of schemas/event.schema.json.
All decisions about what may be kept are made here, on the teller's PC, before anything is saved or sent.
"""

import json
from pathlib import Path

import pytest

from rookie_agent.ie.recorder import IeRecorder

SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "event.schema.json").read_text(encoding="utf-8"))
FRAME = "desktopFrame/rtop/main/fraProfileArea"


def raw(kind, **fields):
    base = {"t": 1000, "kind": kind, "frame": FRAME, "title": "Main", "tag": "input", "type": "text",
            "id": "", "name": "", "label": "", "pos": 0, "value": None}
    base.update(fields)
    return base


def recorder():
    return IeRecorder(app_title="TouchPoint", session_id="s-test")


def test_a_button_click_becomes_a_click_event_with_layered_selectors():
    r = recorder()
    r.handle(raw("click", tag="button", type="button", id="btnMore", name="btnMore", label="THÊM"))
    [event] = r.stop()
    assert event["engine"] == "ie" and event["schema_version"] == 2 and event["type"] == "click"
    assert event["url"] == "TouchPoint/Main"
    assert event["target"]["label"] == "THÊM" and event["target"]["tag"] == "button"
    assert event["target"]["selectors"][0] == f"frame={FRAME}|id=btnMore"
    assert f"frame={FRAME}|name=btnMore" in event["target"]["selectors"]
    assert f"frame={FRAME}|label=THÊM" in event["target"]["selectors"]
    assert event["api_calls"] == []


def test_a_sensitive_field_keeps_its_class_and_never_its_value():
    r = recorder()
    r.handle(raw("input", id="txtCustomerId", name="txtPartyID", label="Mã khách hàng", value="0123456789"))
    r.handle(raw("input", id="amt", label="Số tiền", value="5000000"))
    events = r.stop()
    assert [e["value_class"] for e in events] == ["cif_number", "amount"]
    assert all(e["value"] is None for e in events)
    assert "0123456789" not in json.dumps(events) and "5000000" not in json.dumps(events)


def test_a_field_nobody_classified_is_sensitive_not_plain():
    r = recorder()
    r.handle(raw("input", id="txtBlank", label="", name="txtBlank", value="whatever"))
    [event] = r.stop()
    assert event["value"] is None and event["value_class"] == "unclassified"


def test_a_plain_field_keeps_its_value_so_recordings_can_be_compared():
    r = recorder()
    r.handle(raw("select", tag="select", type="select-one", label="Loại báo cáo", value="Tháng"))
    [event] = r.stop()
    assert event["type"] == "select" and event["value"] == "Tháng" and event["value_class"] is None


@pytest.mark.parametrize("fields", [
    {"type": "password", "id": "pw", "label": "Mật khẩu", "value": "TOPSECRET"},
    {"type": "hidden", "name": "appPasswd", "value": "SECRET1"},
    {"type": "text", "id": "otp", "label": "Mã OTP", "value": "123456"},
    {"type": "text", "id": "x", "name": "userPassword", "label": "Ô gì đó", "value": "SECRET2"},
])
def test_passwords_otp_and_hidden_fields_leave_no_event_and_no_value(fields):
    r = recorder()
    r.handle(raw("input", **fields))
    assert r.stop() == []


def test_enter_in_a_password_field_keeps_the_action_only():
    r = recorder()
    r.handle(raw("submit", type="password", id="pw", label="Mật khẩu", value=None))
    [event] = r.stop()
    assert event["type"] == "submit" and event["value"] is None and "SECRET" not in json.dumps(event)


def test_numbers_in_labels_and_titles_are_masked():
    r = recorder()
    r.handle(raw("click", tag="button", type="button", id="b", label="Tài khoản 0123456789012", title="Khách 0123456789 - Main"))
    [event] = r.stop()
    assert "0123456789" not in json.dumps(event)


def test_lines_from_different_frames_are_put_in_the_order_they_happened():
    r = recorder()
    r.handle(raw("click", t=3000, tag="button", type="button", id="b2", label="Hai"))
    r.handle(raw("click", t=1000, tag="button", type="button", id="b1", label="Một"))
    events = r.stop()
    assert [e["target"]["label"] for e in events] == ["Một", "Hai"]
    assert [e["seq"] for e in events] == [0, 1]


def test_every_event_conforms_to_the_event_schema():
    jsonschema = pytest.importorskip("jsonschema")
    r = recorder()
    r.handle(raw("input", id="txtCustomerId", label="Mã khách hàng", value="1"))
    r.handle(raw("input", id="d", label="Ngày", value="2026-11-16"))
    r.handle(raw("submit", id="d", label="Ngày"))
    r.handle(raw("click", tag="a", type="", id="lnk", label="Xem"))
    for event in r.stop():
        jsonschema.validate(event, SCHEMA)


def test_the_same_press_reported_twice_in_a_moment_is_one_click():
    r = recorder()
    r.handle(raw("click", t=1000, tag="button", type="button", id="b", label="LƯU"))
    r.handle(raw("click", t=1200, tag="button", type="button", id="b", label="LƯU"))
    r.handle(raw("click", t=3000, tag="button", type="button", id="b", label="LƯU"))
    assert len(r.stop()) == 2
