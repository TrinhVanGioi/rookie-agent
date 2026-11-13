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
