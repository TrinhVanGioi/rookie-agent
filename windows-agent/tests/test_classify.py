import pytest

from rookie_agent.classify import FieldClass, classify


@pytest.mark.parametrize("label", ["Mật khẩu", "Password", "Mã OTP", "Nhập mã PIN", "Mã xác thực"])
def test_secrets_are_ignored_by_label(label):
    assert classify(label, "text") == FieldClass("ignore")


def test_password_role_is_ignored_whatever_the_label():
    assert classify("Ngày báo cáo", "password text") == FieldClass("ignore")
    assert classify("", "password text") == FieldClass("ignore")


@pytest.mark.parametrize(
    ("label", "value_class"),
    [
        ("Tài khoản chuyển", "account_number"),
        ("Tài khoản nhận", "account_number"),
        ("Số CIF hoặc CCCD", "cif_number"),
        ("Số CCCD", "id_number"),
        ("Họ và tên", "customer_name"),
        ("Tên khách hàng", "customer_name"),
        ("Số tiền", "amount"),
        ("Số điện thoại", "phone"),
        ("Tên đăng nhập", "username"),
        ("Nội dung", "free_text"),
        ("Ngày sinh", "birth_date"),
    ],
)
def test_sensitive_fields_keep_only_their_class(label, value_class):
    assert classify(label, "text") == FieldClass("sensitive", value_class)


@pytest.mark.parametrize("label", ["Ngày báo cáo", "NGÀY  GIAO DỊCH", "Loại báo cáo", "Trạng thái", "Chi nhánh"])
def test_plain_fields(label):
    assert classify(label, "text").kind == "plain"


@pytest.mark.parametrize("label", ["", "Trường lạ chưa biết", "xyz"])
def test_unknown_fields_default_to_sensitive(label):
    assert classify(label, "text") == FieldClass("sensitive", "unclassified")
