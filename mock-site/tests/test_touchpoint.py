"""Task 11.1: the TouchPoint look-alike answers like the real one (without a browser; tests/test_ie_matrix.py drives it in IE)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import touchpoint
from app import app


@pytest.fixture
def tp():
    return touchpoint.TouchPoint()


def decode(raw):
    a = json.loads(raw[4:])
    return [a[-3][i - 1] for i in a[:-3]]


def signed_in(tp, user="gdv01", password="demo-only-1234"):
    status, headers, _ = tp.handle("POST", "/tp/login", {}, f"txtUser={user}&txtPw={password}".encode())
    assert status == 302
    cookie = dict(headers)["Set-Cookie"].split(";")[0]
    return {"Cookie": cookie}


def service(tp, auth, svc, method, *args):
    _, _, token = tp.handle("POST", f"/tp/postAuthentication.fisglobal?method=getToken&claims={svc}", auth, b"")
    body = "|".join(["7", "0", str(4 + len(args)), "http://x/tp/", touchpoint.STRONG, f"com.fis.tp.client.{svc}", method, *args]) + "|"
    return tp.handle("POST", "/tp/TPClassLoader", {**auth, "Authorization": "Bearer " + token.decode().strip()}, body.encode())


def test_a_wrong_password_stays_on_the_sign_in_page_and_nothing_works_without_signing_in(tp):
    status, _, page = tp.handle("POST", "/tp/login", {}, b"txtUser=gdv01&txtPw=x")
    assert status == 200 and "Sai tên đăng nhập".encode() in page
    assert tp.handle("POST", "/tp/TPClassLoader", {}, b"7|0|")[0] == 401
    assert b"txtPw" in tp.handle("GET", "/tp/acct", {}, b"")[2]


def test_the_main_page_is_a_frameset_with_the_work_frame(tp):
    page = tp.handle("GET", "/tp/main", signed_in(tp), b"")[2].decode()
    assert '<frame name="work"' in page and '<frame name="menu"' in page and "Quầy mẫu" in page


def test_a_call_needs_the_newest_token_as_a_bearer(tp):
    auth = signed_in(tp)
    status, _, answer = service(tp, auth, "AcctService", "find", "0123456789")
    assert status == 200 and answer.startswith(b"//OK")
    assert decode(answer)[0] == "0123456789"
    _, _, old = tp.handle("POST", "/tp/postAuthentication.fisglobal?method=getToken&claims=x", auth, b"")
    tp.handle("POST", "/tp/postAuthentication.fisglobal?method=getToken&claims=x", auth, b"")       # a newer one: the old one is no good
    refused = tp.handle("POST", "/tp/TPClassLoader", {**auth, "Authorization": "Bearer " + old.decode().strip()},
                        f"7|0|5|x|{touchpoint.STRONG}|com.fis.tp.client.AcctService|find|0123456789|".encode())
    assert refused[0] == 401


def test_an_account_is_the_same_each_time_and_one_ending_in_000_does_not_exist(tp):
    auth = signed_in(tp)
    one = decode(service(tp, auth, "AcctService", "find", "0123456789")[2])
    again = decode(service(tp, auth, "AcctService", "find", "0123456789")[2])
    assert one == again and one[1]
    assert service(tp, auth, "AcctService", "find", "0123456000")[2].startswith(b"//EX")


def test_the_history_lists_rows_between_two_days_and_refuses_a_bad_range(tp):
    auth = signed_in(tp)
    rows = decode(service(tp, auth, "HistoryService", "list", "0123456789", "01/11/2026", "15/11/2026")[2])
    assert int(rows[0]) > 0 and len(rows) == 1 + 6 * int(rows[0])
    assert service(tp, auth, "HistoryService", "list", "0123456789", "15/11/2026", "01/11/2026")[2].startswith(b"//EX")


def test_the_three_ways_a_file_comes_back(tp):
    auth = signed_in(tp)
    status, headers, data = tp.handle("POST", "/tp/exportPdf", auth, b"acct=0123456789&ids=FT1,FT2")
    assert status == 200 and dict(headers)["Content-Type"] == "application/pdf" and data.startswith(b"%PDF")
    status, headers, data = tp.handle("GET", "/tp/statement.pdf?acct=0123456789&from=01%2F11%2F2026&to=15%2F11%2F2026", auth, b"")
    assert data.startswith(b"%PDF")
    status, headers, data = tp.handle("POST", "/tp/exportExcel", auth, b"acct=0123456789&from=01/11/2026&to=15/11/2026")
    assert "attachment" in dict(headers)["Content-Disposition"] and data.startswith(b"Ma GD")
    assert tp.seen[-3:] == ["exportPdf(0123456789,2)", "statement(0123456789,01/11/2026,15/11/2026)", "excel(0123456789,01/11/2026,15/11/2026)"]


def test_the_message_box_and_the_report_dialog_are_pages_of_their_own(tp):
    auth = signed_in(tp)
    box = tp.handle("GET", "/tp/utilities/dlgMessageBox.jsp?msg=Sai%20%3Cngay%3E", auth, b"")[2].decode()
    assert "btnOK" in box and "Sai &lt;ngay&gt;" in box
    report = tp.handle("GET", "/tp/viewReport.jsp?acct=0123456789&ids=FT1,FT2", auth, b"")[2].decode()
    assert 'action="/tp/exportPdf"' in report and 'target="pdfFrame"' in report and "2 giao dịch" in report


def test_a_transfer_waits_for_the_checker_and_only_the_checker_decides(tp):
    maker = signed_in(tp)
    made = decode(service(tp, maker, "TransferService", "create", "0123456789", "0987654321", "1500000", "Thu")[2])
    assert made[1] == "Chờ duyệt"
    assert service(tp, maker, "ApproveService", "list")[2].startswith(b"//EX")
    checker = signed_in(tp, "ksv01", "demo-only-5678")
    assert decode(service(tp, checker, "ApproveService", "list")[2])[1] == made[0]
    assert decode(service(tp, checker, "ApproveService", "decide", made[0], "1")[2])[1] == "approved"


def test_dlg_inline_is_remembered_by_a_cookie(tp):
    assert ("Set-Cookie", "TPDLG=inline; path=/") in tp.handle("GET", "/tp/?dlg=inline", {}, b"")[1]


def test_the_mock_site_serves_the_look_alike():
    with TestClient(app) as client:
        assert "ĐĂNG NHẬP" in client.get("/tp/").text
        reply = client.post("/tp/login", data={"txtUser": "gdv01", "txtPw": "demo-only-1234"}, follow_redirects=False)
        assert reply.status_code == 302 and reply.headers["location"] == "/tp/main"
        assert 'name="work"' in client.get("/tp/main").text


def test_gate_12_a_new_look_keeps_the_words_but_not_the_ids_and_a_business_change_adds_a_box(tp):
    """The SADPT demo: ui 2 renames the ids and moves the search button (same words); biz 2 adds a confirmation box after the search."""
    auth = signed_in(tp)
    page = tp.handle("GET", "/tp/acct", auth, b"")[2].decode()
    assert 'id="btnFind"' in page and 'id="txtAcct"' in page and "var BIZ = 1;" in page
    tp.ui = 2
    page = tp.handle("GET", "/tp/acct", auth, b"")[2].decode()
    assert 'id="btnFind"' not in page and 'id="txtAcct"' not in page and 'value="TRA CỨU"' in page and "Số tài khoản" in page
    assert page.index('id="btnSearchAccount"') < page.index('id="txtAccountNo"') and '$("txtAccountNo")' in page
    transfer = tp.handle("GET", "/tp/transfer", auth, b"")[2].decode()
    assert 'id="btnSubmit"' not in transfer and transfer.index('id="btnClear"') < transfer.index('id="btnSendForApproval"') and "GỬI DUYỆT" in transfer
    tp.ui, tp.biz = 1, 2
    assert "var BIZ = 2;" in tp.handle("GET", "/tp/acct", auth, b"")[2].decode()
    fresh = touchpoint.TouchPoint()
    assert ("Set-Cookie", "TPUI=2; path=/") in fresh.handle("GET", "/tp/?ui=2", {}, b"")[1]


def test_a_date_is_chosen_from_a_month_grid_and_a_read_only_field_is_marked(tp):
    """TouchPoint's monthCalendar: an icon beside the field, then a day number whose name is the date it writes."""
    auth = signed_in(tp)
    page = tp.handle("GET", "/tp/acct", auth, b"")[2].decode()
    assert 'id="btnCalFrom" name="cal-txtFrom"' in page and 'id="btnCalTo" name="cal-txtTo"' in page
    assert 'id="calD15" name="15/11/2026" value="15"' in page and "Tháng 11 năm 2026" in page and "function pickDay" in page
    assert "readonly" not in page.split('id="txtFrom"')[1][:40]
    fresh = touchpoint.TouchPoint()
    assert ("Set-Cookie", "TPRO=1; path=/") in fresh.handle("GET", "/tp/?ro=1", {}, b"")[1]
    cookie = signed_in(fresh)["Cookie"] + "; TPRO=1"
    locked = fresh.handle("GET", "/tp/acct", {"Cookie": cookie}, b"")[2].decode()
    assert 'id="txtFrom" name="txtFrom" readonly' in locked
    cookie = signed_in(fresh)["Cookie"] + "; TPUI=2"
    assert 'id="btnSearchAccount"' in fresh.handle("GET", "/tp/acct", {"Cookie": cookie}, b"")[2].decode()
