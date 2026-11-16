import pytest

from app.risk import Risk, mode_for, risk_of
from tests.helpers import java_transfer_session, web_report_session


def java_click(label: str, screen: str, tag: str = "push button") -> dict:
    event = java_transfer_session("s")[0]
    event.update(type="click", url=screen)
    event["target"].update(label=label, tag=tag)
    return event


def web_call(method: str, path: str) -> dict:
    event = web_report_session("s", "2026-11-10")[2]
    event["api_calls"] = [{"method": method, "path": path, "status": 200}]
    return event


@pytest.mark.parametrize(
    ("label", "screen", "expected"),
    [
        ("Tra cứu CIF", "Mock TPSS - Khách hàng (CIF)", Risk("read")),
        ("Tải lại", "Mock TPSS - Phê duyệt", Risk("read")),
        ("Đăng nhập", "Mock TPSS - Đăng nhập", Risk("read")),
        ("Mở CIF", "Mock TPSS - Khách hàng (CIF)", Risk("write")),
        ("Gửi duyệt", "Mock TPSS - Chuyển tiền", Risk("money")),
        ("Chuyển duyệt", "Mock TPSS - Chuyển tiền", Risk("money")),
        ("Duyệt", "Mock TPSS - Phê duyệt", Risk("money", human_only=True)),
        ("Từ chối", "Mock TPSS - Phê duyệt", Risk("money", human_only=True)),
        ("Một nút lạ", "Mock TPSS - Màn hình lạ", Risk("write")),  # unknown button that changes data: write
    ],
)
def test_java_clicks_are_classified_by_screen_and_label(label, screen, expected):
    assert risk_of(java_click(label, screen)) == expected


def test_java_typing_choosing_and_tabs_are_read():
    session = java_transfer_session("s")
    assert {risk_of(e).level for e in session if e["type"] in ("input", "select")} == {"read"}
    assert risk_of(session[2]) == Risk("read")  # page tab


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/api/report", Risk("read")),
        ("POST", "/api/cif", Risk("write")),
        ("POST", "/api/transfers", Risk("money")),
        ("POST", "/api/transfers/LCT00001/approve", Risk("money", human_only=True)),
        ("DELETE", "/api/something-else", Risk("write")),  # unknown change: default write
    ],
)
def test_web_risk_follows_the_api_that_was_called(method, path, expected):
    assert risk_of(web_call(method, path)) == expected


def test_modes_follow_the_hard_rules():
    assert (mode_for("read"), mode_for("write"), mode_for("money")) == ("auto", "approve", "approve")


@pytest.mark.parametrize(
    ("label", "screen", "expected"),
    [
        ("Mật khẩu", "Mock TPSS - Đăng nhập", Risk("read")),
        ("Số CIF hoặc CCCD", "Mock TPSS - Khách hàng (CIF)", Risk("read")),
        ("Số tiền", "Mock TPSS - Chuyển tiền", Risk("money")),  # Enter in any field of a money screen may send the order
        ("Nội dung", "Mock TPSS - Màn hình lạ", Risk("write")),  # an unknown field: the safe default
    ],
)
def test_enter_in_a_field_is_classified_by_screen_and_field(label, screen, expected):
    event = java_click(label, screen, tag="text")
    event["type"] = "submit"
    assert risk_of(event) == expected


def ie_event(kind: str, label: str, screen: str = "TouchPoint/Main", tag: str = "button") -> dict:
    return {"schema_version": 2, "engine": "ie", "session_id": "s", "seq": 0, "ts": "2026-11-16T03:00:00.000Z", "type": kind,
            "url": screen, "target": {"selectors": ["label=x"], "label": label, "tag": tag}, "value": None, "value_class": None, "api_calls": []}


@pytest.mark.parametrize(
    "label,screen,expected",
    [
        ("XEM CHỮ KÝ", "TouchPoint/Main", Risk("read")),
        ("TRA CỨU", "TouchPoint/Main", Risk("read")),
        ("ĐĂNG XUẤT", "TouchPoint/Desktop View", Risk("read")),
        ("LƯU", "TouchPoint/Main", Risk("write")),
        ("NÚT LẠ", "TouchPoint/Main", Risk("write")),  # not classified: write, never read
        ("XÁC NHẬN", "TouchPoint/Chuyển tiền", Risk("money")),
        ("DUYỆT", "TouchPoint/Phê duyệt", Risk("money", human_only=True)),
    ],
)
def test_ie_clicks_are_classified_by_screen_and_label_since_there_is_no_api_to_see(label, screen, expected):
    assert risk_of(ie_event("click", label, screen)) == expected


def test_ie_typing_and_links_that_are_not_buttons_change_nothing():
    assert risk_of(ie_event("input", "Mã khách hàng", tag="input")) == Risk("read")
    assert risk_of(ie_event("click", "Một ô bất kỳ", tag="div")) == Risk("read")


@pytest.mark.parametrize(
    "kind,label,screen,expected",
    [
        ("click", "dòng 2", "TouchPoint/Main", Risk("read")),           # a row of a list: looking at a customer's account
        ("click", "dòng 12", "TouchPoint/Main", Risk("read")),
        ("submit", "Mã khách hàng", "TouchPoint/Main", Risk("read")),   # Enter in the customer id: an enquiry
        ("click", "Hồ sơ", "TouchPoint/Main", Risk("read")),            # tabs that only show
        ("click", "Thông tin tài khoản", "TouchPoint/Main", Risk("read")),
        ("click", "Lịch sử sự kiện", "TouchPoint/Main", Risk("read")),
        ("click", "Người liên hệ", "TouchPoint/Main", Risk("read")),
        ("click", "LƯU", "TouchPoint/Main", Risk("write")),             # still write
        ("click", "Cập nhật hồ sơ", "TouchPoint/Main", Risk("write")),  # a label that merely starts like a tab
        ("click", "Chuyển tiền", "TouchPoint/Chuyển tiền", Risk("money")),
        ("submit", "Số tiền", "TouchPoint/Chuyển tiền", Risk("money")),
        ("submit", "Ghi chú", "TouchPoint/Main", Risk("write")),        # Enter in an unknown field stays write
        ("click", "DUYỆT", "TouchPoint/Phê duyệt", Risk("money", human_only=True)),
    ],
)
def test_ie_read_only_navigation_is_read_and_everything_else_keeps_its_risk(kind, label, screen, expected):
    assert risk_of(ie_event(kind, label, screen)) == expected
