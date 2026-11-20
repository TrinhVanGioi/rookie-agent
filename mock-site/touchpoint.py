"""A TouchPoint look-alike for Internet Explorer (task 11.1). Synthetic data only; nothing real is reached.

Standard library only, so the same pages are served by the mock site (FastAPI, for demos and the sandbox) and by the real-IE tests
(http.server). It holds every pattern of the real system that made recording or learning hard:

- a sign-in form, then a frameset (toolbar, menu, work, rhidden) in quirks mode, scripts in ES3 for document modes 5, 8 and 9;
- each service call is two requests: `postAuthentication.fisglobal?method=getToken` answers a bare token (only the newest one is
  accepted), then `TPClassLoader` with `Authorization: Bearer <token>` and a GWT-RPC body (`7|0|n|…|Service|method|args|`);
- an account looked up with Enter or with the button; the transaction history between two dates; rows ticked with check boxes;
- «IN BÁO NỢ/CÓ» opens a dialog (`showModalDialog`) whose form posts into a frame and gets a PDF; «XUẤT SAO KÊ» opens a PDF with
  `window.open`; «TẢI EXCEL» posts a form into a hidden frame and gets a file (attachment);
- «XUẤT BÁO CÁO» (`/tp/report`) answers with a code only (`application/octet-stream`, a GWT string table). The code names the file
  on this same site (`/tp/rpt/file.pdf?key=…`); the page then opens that address. A wrong or missing key is not a file;
- «IN SAO KÊ ĐỘT XUẤT» (`/tp/stmt`, `statement_flow.py`) is the print flow: a dialog, an XML post per step (fee, transactions,
  build the report, a local note), and the answer names a PDF on this site which the page then opens;
- the walk a teller records (`/tp/role`, then `/tp/desk`): choose a role, the account tab, click the account, the transaction tab,
  a date range, tick one row, In, then In again in the dialog. The dialog is the same print flow; the file address is a query key;
- a date is chosen the way TouchPoint's `monthCalendar` does it: the icon beside the field, then a day number in the month grid
  (the two presses are one date; `?ro=1` makes «Từ ngày» read-only so a run stops and asks);
- the page's own message box (`/tp/utilities/dlgMessageBox.jsp`) after a mistaken press (a date in the wrong format, nothing ticked);
- the page asks the server by itself every few seconds (`keepalive`);
- a transfer screen (money: «GỬI DUYỆT») and the checker's approval screen («DUYỆT», a person's own press).

A dialog opens with `showModalDialog` as in TouchPoint. `dlg=inline` (a cookie set by `/tp/?dlg=inline`) opens it in a frame of
the page instead: an IE driven through COM in the background cannot open a modal window, and the tests run it that way. The real
modal dialog is tested on its own (tests/test_ie_real.py, with an HTA).
"""

from __future__ import annotations

import hashlib
import json
import random
import secrets
import threading
import time
import unicodedata
from datetime import date, timedelta
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import parse_qs, urlsplit

USERS = {"gdv01": ("demo-only-1234", "GDV Mot", "maker"), "ksv01": ("demo-only-5678", "KSV Mot", "checker")}
STRONG = "B4D2C1A0F00D5EED0123456789ABCDEF"
_FAMILY = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ", "Đặng", "Bùi"]
_MIDDLE = ["Văn", "Thị", "Minh", "Thu", "Quốc", "Ngọc"]
_GIVEN = ["An", "Bình", "Chi", "Dũng", "Giang", "Hà", "Khánh", "Lan", "Nam", "Oanh"]
_BRANCH = ["CN Hà Nội", "CN Đống Đa", "CN Hoàn Kiếm", "CN Hồ Chí Minh"]
_DESC = ["Chuyển khoản đến", "Chuyển khoản đi", "Rút tiền ATM", "Nộp tiền mặt", "Phí dịch vụ", "Lãi tiền gửi"]


def plain(text: str) -> str:
    """ASCII without Vietnamese marks, for the PDF (its built-in font has no Vietnamese letters)."""
    text = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn" and ord(c) < 128)


def account_of(number: str) -> dict[str, Any] | None:
    """Any number of 6 to 14 digits is an account, made up from the number itself; one ending in 000 does not exist."""
    if not number.isdigit() or not 6 <= len(number) <= 14 or number.endswith("000"):
        return None
    rng = random.Random("acct:" + number)
    name = f"{rng.choice(_FAMILY)} {rng.choice(_MIDDLE)} {rng.choice(_GIVEN)}"
    return {"number": number, "name": name, "branch": rng.choice(_BRANCH), "balance": rng.randrange(5, 900) * 100_000, "currency": "VND"}


def parse_day(text: str) -> date | None:
    try:
        d, m, y = (int(x) for x in text.split("/"))
        return date(y, m, d)
    except (ValueError, TypeError):
        return None


def history_of(number: str, start: date, end: date) -> list[dict[str, Any]]:
    rows = []
    day = start
    rng = random.Random(f"hist:{number}")
    balance = (account_of(number) or {"balance": 10_000_000})["balance"]
    while day <= end and len(rows) < 30:
        r = random.Random(f"hist:{number}:{day.isoformat()}")
        for k in range(r.choice([0, 0, 1, 2])):
            amount = r.randrange(1, 200) * 10_000
            debit = r.random() < 0.5
            balance += -amount if debit else amount
            rows.append({"id": f"FT{day.strftime('%y%m%d')}{rng.randrange(1000, 9999)}{k}", "date": day.strftime("%d/%m/%Y"),
                         "desc": r.choice(_DESC), "debit": amount if debit else 0, "credit": 0 if debit else amount, "balance": balance})
        day += timedelta(days=1)
    return rows


def pdf(lines: list[str]) -> bytes:
    """A small valid one-page PDF with these lines (ASCII)."""
    text = "BT /F1 12 Tf 50 790 Td 16 TL " + " ".join("(" + plain(line).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") '"
                                                    for line in lines) + " ET"
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
               f"<< /Length {len(text)} >>\nstream\n{text}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def money(value: int) -> str:
    return f"{value:,}".replace(",", ".")


# ---- the pages (ES3: document modes 5, 8 and 9; no addEventListener, no JSON in mode 5) ------------------------------------------

TP_JS = r"""
function $(id) { return document.getElementById(id); }
function xhr() { try { return new XMLHttpRequest(); } catch (e) { return new ActiveXObject("Microsoft.XMLHTTP"); } }
function send(method, url, body, headers, done) {
  var r = xhr(), k;
  r.open(method, url, true);
  for (k in headers) { if (headers.hasOwnProperty(k)) { r.setRequestHeader(k, headers[k]); } }
  r.onreadystatechange = function () { if (r.readyState === 4) { done(r.status, r.responseText); } };
  r.send(body);
}
function esc(v) { return String(v).replace(/\\/g, "\\\\").replace(/\|/g, "\\!"); }
// a service call is two requests: a fresh token, then the call with it
function call(service, method, args, done) {
  send("POST", "/tp/postAuthentication.fisglobal?method=getToken&claims=" + service, "", {}, function (status, token) {
    if (status !== 200) { done(null, "Không lấy được mã xác thực (" + status + ")"); return; }
    var parts = ["7", "0", String(4 + args.length), location.protocol + "//" + location.host + "/tp/", "STRONG", "com.fis.tp.client." + service, method], i;
    for (i = 0; i < args.length; i++) { parts.push(esc(args[i])); }
    send("POST", "/tp/TPClassLoader", parts.join("|") + "|", {"Content-Type": "text/x-gwt-rpc; charset=utf-8", "Authorization": "Bearer " + token.replace(/\s/g, "")},
      function (s, text) {
        if (s !== 200) { done(null, "Máy chủ từ chối (" + s + ")"); return; }
        if (text.indexOf("//EX") === 0) { done(null, decode(text)[0]); return; }
        done(decode(text), null);
      });
  });
}
// GWT-RPC: numbers pointing (1-based) into the string table, then the table, the flags and the version
function decode(text) {
  var a = eval("(" + text.substring(4) + ")"), table = a[a.length - 3], out = [], i;
  for (i = 0; i < a.length - 3; i++) { out.push(table[a[i] - 1]); }
  return out;
}
function inline() { return document.cookie.indexOf("TPDLG=inline") >= 0; }
// a dialog of the page: modal as in TouchPoint, or (dlg=inline) a frame over the page
function openDialog(url) {
  if (!inline() && window.showModalDialog) { window.showModalDialog(url, window, "dialogWidth:760px;dialogHeight:560px;status:no"); return; }
  var box = $("dlgBox");
  if (!box) { box = document.createElement("div"); box.id = "dlgBox"; box.style.cssText = "position:absolute;left:60px;top:40px;width:700px;height:480px;border:2px solid #345;background:#fff"; document.body.appendChild(box); }
  box.innerHTML = '<iframe name="dlg" id="dlgFrame" src="' + url + '" style="width:100%;height:100%;border:0"></iframe>';
  box.style.display = "block";
}
function closeDialog() { var box = $("dlgBox"); if (box) { box.innerHTML = ""; box.style.display = "none"; } }
function msgBox(text) { openDialog("/tp/utilities/dlgMessageBox.jsp?msg=" + encodeURIComponent(text)); }
function keepAlive() { send("GET", "/tp/keepalive?t=" + new Date().getTime(), null, {}, function () {}); }
function money(v) { var s = String(v), out = ""; while (s.length > 3) { out = "." + s.substring(s.length - 3) + out; s = s.substring(0, s.length - 3); } return s + out; }
function isDay(v) { return /^\d{2}\/\d{2}\/\d{4}$/.test(v); }
"""

STYLE = ("<style>body{font:13px Tahoma,Arial;margin:8px;background:#f3f5f8}h3{margin:4px 0 10px;color:#234}"
         "table.g{border-collapse:collapse;background:#fff}table.g td,table.g th{border:1px solid #c5ccd6;padding:3px 6px}"
         "input.b{background:#2b5797;color:#fff;border:1px solid #1d3d6b;padding:3px 10px;font-weight:bold}"
         ".err{color:#b00;font-weight:bold}.ok{color:#060}</style>")


def _doc(title: str, body: str, script: str = "", onload: str = "") -> bytes:
    head = f"<html><head><title>{title}</title><meta http-equiv='Content-Type' content='text/html; charset=utf-8'>{STYLE}"
    head += "<script src='/tp/tp.js'></script>" + (f"<script>{script}</script>" if script else "") + "</head>"
    return (head + f"<body{' onload=\"' + onload + '\"' if onload else ''}>{body}</body></html>").encode("utf-8")


LOGIN_BODY = """<h3>Quầy mẫu – Đăng nhập</h3><form method="post" action="/tp/login"><table>
<tr><td>Tên đăng nhập</td><td><input type="text" id="txtUser" name="txtUser"></td></tr>
<tr><td>Mật khẩu</td><td><input type="password" id="txtPw" name="txtPw"></td></tr></table>
<input type="submit" class="b" id="btnLogin" value="ĐĂNG NHẬP"> <span class="err">%s</span></form>
<p style="color:#678">Hệ thống giả lập, dữ liệu tự sinh. Tài khoản thử: gdv01 / demo-only-1234 (GDV), ksv01 / demo-only-5678 (KSV).</p>"""

ROLE_BODY = """<h3>Chọn vai trò</h3>
<p>Đăng nhập xong, chọn đúng vai trò của tài khoản rồi vào quầy.</p>
<form method="post" action="/tp/role" style="display:inline"><input type="hidden" name="role" value="maker">
<input type="submit" class="b" id="btnRoleMaker" value="GIAO DỊCH VIÊN"></form>
<form method="post" action="/tp/role" style="display:inline"><input type="hidden" name="role" value="checker">
<input type="submit" class="b" id="btnRoleChecker" value="KIỂM SOÁT VIÊN"></form>
<p class="err">%s</p>"""

ACCT_BODY = """<h3>Tra cứu tài khoản</h3>
<table><tr><td>Số tài khoản</td><td><input type="text" id="txtAcct" name="txtAcct" onkeydown="if (event.keyCode == 13) { findAcct(); return false; }"></td>
<td><input type="button" class="b" id="btnFind" value="TRA CỨU" onclick="findAcct()"></td></tr></table>
<div id="info"></div>
<div id="hist" style="display:none;margin-top:10px">
<table><tr><td>Từ ngày</td><td><input type="text" id="txtFrom" name="txtFrom" size="10"> <input type="button" class="cal" id="btnCalFrom" name="cal-txtFrom" value="Lịch" title="Chọn ngày" onclick="openCal('txtFrom')"></td>
<td>Đến ngày</td><td><input type="text" id="txtTo" name="txtTo" size="10"> <input type="button" class="cal" id="btnCalTo" name="cal-txtTo" value="Lịch" title="Chọn ngày" onclick="openCal('txtTo')"></td>
<td><input type="button" class="b" id="btnHistory" value="XEM LỊCH SỬ" onclick="showHistory()"></td></tr></table>
<div id="calBox" style="display:none;margin-top:6px;padding:4px;border:1px solid #234;background:#fff"><div>Tháng 11 năm 2026</div>%s
<input type="button" id="calClose" value="Đóng" onclick="closeCal()"></div>
<div id="rows"></div>
<p><input type="button" class="b" id="btnPrint" value="IN BÁO NỢ/CÓ" onclick="printSlips()">
<input type="button" class="b" id="btnPrintData" value="XEM BÁO NỢ/CÓ" onclick="printData()">
<input type="button" class="b" id="btnStatement" value="XUẤT SAO KÊ" onclick="statement()">
<input type="button" class="b" id="btnExcel" value="TẢI EXCEL" onclick="excel()"></p>
<form id="frmExcel" method="post" action="/tp/exportExcel" target="hidFrame"><input type="hidden" name="acct" id="hidAcct"><input type="hidden" name="from" id="hidFrom"><input type="hidden" name="to" id="hidTo"></form>
<iframe name="hidFrame" id="hidFrame" src="/tp/blank" style="width:0;height:0;border:0"></iframe>
</div>"""

ACCT_JS = """
var current = "";
function findAcct() {
  var v = $("txtAcct").value.replace(/\\s/g, "");
  $("info").innerHTML = "Đang tra cứu...";
  call("AcctService", "find", [v], function (data, err) {
    if (err) { $("info").innerHTML = '<span class="err">' + err + '</span>'; $("hist").style.display = "none"; return; }
    current = data[0];
    $("info").innerHTML = '<table class="g" id="tblInfo"><tr><th>Số TK</th><th>Chủ tài khoản</th><th>Chi nhánh</th><th>Số dư</th></tr><tr><td>'
      + data[0] + '</td><td>' + data[1] + '</td><td>' + data[2] + '</td><td>' + money(data[3]) + ' ' + data[4] + '</td></tr></table>';
    $("hist").style.display = "block"; $("rows").innerHTML = "";
    if (BIZ > 1) { msgBox("Theo quy định mới: xác nhận khách hàng đã xuất trình giấy tờ tuỳ thân trước khi xem lịch sử."); }
  });
}
function showHistory() {
  var a = $("txtFrom").value, b = $("txtTo").value;
  if (!isDay(a) || !isDay(b)) { msgBox("Sai định dạng ngày. Nhập theo dd/mm/yyyy."); return; }
  call("HistoryService", "list", [current, a, b], function (data, err) {
    if (err) { $("rows").innerHTML = '<span class="err">' + err + '</span>'; return; }
    var h = ['<table class="g" id="tblHistory"><tr><th></th><th>Mã GD</th><th>Ngày</th><th>Nội dung</th><th>Nợ</th><th>Có</th><th>Số dư</th></tr>'], i, r, n = parseInt(data[0], 10);
    for (i = 0; i < n; i++) {
      r = data.slice(1 + i * 6, 7 + i * 6);
      h.push('<tr><td><input type="checkbox" id="chkRow' + i + '" value="' + r[0] + '"></td><td>' + r[0] + '</td><td>' + r[1] + '</td><td>' + r[2]
        + '</td><td>' + money(r[3]) + '</td><td>' + money(r[4]) + '</td><td>' + money(r[5]) + '</td></tr>');
    }
    h.push('</table>');
    $("rows").innerHTML = n ? h.join("") : "Không có giao dịch trong khoảng này.";
  });
}
function ticked() { var out = [], i, c; for (i = 0; i < 40; i++) { c = $("chkRow" + i); if (c && c.checked) { out.push(c.value); } } return out; }
function printSlips() {
  var ids = ticked();
  if (!ids.length) { msgBox("Chọn ít nhất một giao dịch để in."); return; }
  openDialog("/tp/viewReport.jsp?acct=" + current + "&ids=" + ids.join(","));
}
// the debit advice is not a file: the dialog asks a service and fills its own fields with the answer
function printData() {
  var ids = ticked();
  if (!ids.length) { msgBox("Chọn ít nhất một giao dịch để xem."); return; }
  // the page asks the service and hands the answer to the dialog, which puts it into its own fields
  call("ReportService", "debitAdvice", [current, ids.join(",")], function (data, err) {
    if (err) { msgBox(err); return; }
    window.__advice = data;
    openDialog("/tp/viewData.jsp");
  });
}
function statement() {
  if (!isDay($("txtFrom").value) || !isDay($("txtTo").value)) { msgBox("Sai định dạng ngày. Nhập theo dd/mm/yyyy."); return; }
  window.open("/tp/statement.pdf?acct=" + current + "&from=" + encodeURIComponent($("txtFrom").value) + "&to=" + encodeURIComponent($("txtTo").value), "_blank");
}
function excel() {
  $("hidAcct").value = current; $("hidFrom").value = $("txtFrom").value; $("hidTo").value = $("txtTo").value;
  $("frmExcel").submit();
}
window.setInterval(keepAlive, 4000);
var calFor = "";
function openCal(id) {
  var input = $(id);
  if (!input) { return; }
  if (input.readOnly) { msgBox("Ô ngày chỉ đọc, không chọn được."); return; }
  calFor = id;
  $("calBox").style.display = "block";
}
function closeCal() { $("calBox").style.display = "none"; calFor = ""; }
function pickDay(btn) {
  var input = $(calFor);
  if (!input) { return; }
  if (input.readOnly) { msgBox("Ô ngày chỉ đọc, không nhập được."); closeCal(); return; }
  input.value = btn.name;
  try { input.fireEvent("onchange"); } catch (e) {}
  try {
    if (input.dispatchEvent && document.createEvent) {
      var ev = document.createEvent("HTMLEvents"); ev.initEvent("change", true, true); input.dispatchEvent(ev);
    }
  } catch (e2) {}
  closeCal();
}
"""

TRANSFER_BODY = """<h3>Lập lệnh chuyển tiền</h3><table>
<tr><td>Tài khoản chuyển</td><td><input type="text" id="txtFromAcct" name="txtFromAcct"></td></tr>
<tr><td>Tài khoản nhận</td><td><input type="text" id="txtToAcct" name="txtToAcct"></td></tr>
<tr><td>Số tiền</td><td><input type="text" id="txtAmount" name="txtAmount"></td></tr>
<tr><td>Nội dung</td><td><input type="text" id="txtContent" name="txtContent"></td></tr></table>
<input type="button" class="b" id="btnSubmit" value="GỬI DUYỆT" onclick="submitTransfer()"> <span id="result"></span>"""

TRANSFER_JS = """
function submitTransfer() {
  var amount = $("txtAmount").value.replace(/[.,\\s]/g, "");
  if (!/^\\d+$/.test(amount)) { msgBox("Số tiền không hợp lệ."); return; }
  call("TransferService", "create", [$("txtFromAcct").value, $("txtToAcct").value, amount, $("txtContent").value], function (data, err) {
    $("result").innerHTML = err ? '<span class="err">' + err + '</span>' : '<span class="ok">Đã gửi duyệt: ' + data[0] + '</span>';
  });
}
"""

EXPORT_BODY = """<h3>Xuất báo cáo giao dịch</h3>
<table><tr><td>Số tài khoản</td><td><input type="text" id="txtAcct" name="txtAcct"></td></tr>
<tr><td>Từ ngày</td><td><input type="text" id="txtFrom" name="txtFrom" size="10"> <input type="button" class="cal" id="btnCalFrom" name="cal-txtFrom" value="Lịch" title="Chọn ngày" onclick="openCal('txtFrom')"></td>
<td>Đến ngày</td><td><input type="text" id="txtTo" name="txtTo" size="10"> <input type="button" class="cal" id="btnCalTo" name="cal-txtTo" value="Lịch" title="Chọn ngày" onclick="openCal('txtTo')"></td></tr></table>
<div id="calBox" style="display:none;margin-top:6px;padding:4px;border:1px solid #234;background:#fff"><div>Tháng 11 năm 2026</div>%s
<input type="button" id="calClose" value="Đóng" onclick="closeCal()"></div>
<p><input type="button" class="b" id="btnExport" value="XUẤT BÁO CÁO" onclick="exportReport()"> <span id="rptStatus"></span></p>
<p class="err">Hệ thống trả về một mã. File báo cáo mở ở địa chỉ nằm trong mã đó.</p>"""

EXPORT_JS = """
var calFor = "";
function openCal(id) {
  var input = $(id);
  if (!input) { return; }
  calFor = id;
  $("calBox").style.display = "block";
}
function closeCal() { $("calBox").style.display = "none"; calFor = ""; }
function pickDay(btn) {
  var input = $(calFor);
  if (!input) { return; }
  input.value = btn.name;
  try { input.fireEvent("onchange"); } catch (e) {}
  try {
    if (input.dispatchEvent && document.createEvent) {
      var ev = document.createEvent("HTMLEvents"); ev.initEvent("change", true, true); input.dispatchEvent(ev);
    }
  } catch (e2) {}
  closeCal();
}
function exportReport() {
  var acct = $("txtAcct").value.replace(/\\s/g, ""), a = $("txtFrom").value, b = $("txtTo").value, i, url;
  if (!isDay(a) || !isDay(b)) { msgBox("Sai định dạng ngày. Nhập theo dd/mm/yyyy."); return; }
  $("rptStatus").innerHTML = "Đang xuất...";
  call("ReportService", "export", [acct, a, b], function (data, err) {
    if (err) { $("rptStatus").innerHTML = '<span class="err">' + err + '</span>'; return; }
    url = "";
    for (i = 0; i < data.length; i++) { if (String(data[i]).indexOf("/tp/rpt/") === 0) { url = String(data[i]); } }
    if (!url) { $("rptStatus").innerHTML = '<span class="err">Không có địa chỉ file</span>'; return; }
    $("rptStatus").innerHTML = "Đã nhận mã. Đang mở báo cáo...";
    window.open(url, "_blank");
  });
}
"""

APPROVE_BODY = """<h3>Phê duyệt lệnh</h3><input type="button" class="b" id="btnLoad" value="TẢI DANH SÁCH" onclick="load()"><div id="list"></div>"""

APPROVE_JS = """
function load() {
  call("ApproveService", "list", [], function (data, err) {
    if (err) { $("list").innerHTML = '<span class="err">' + err + '</span>'; return; }
    var h = ['<table class="g" id="tblPending"><tr><th>Mã lệnh</th><th>Từ</th><th>Đến</th><th>Số tiền</th><th></th></tr>'], i, r, n = parseInt(data[0], 10);
    for (i = 0; i < n; i++) {
      r = data.slice(1 + i * 4, 5 + i * 4);
      h.push('<tr><td>' + r[0] + '</td><td>' + r[1] + '</td><td>' + r[2] + '</td><td>' + money(r[3]) + '</td><td><input type="button" class="b" id="btnApprove' + i
        + '" value="DUYỆT" onclick="decide(\\'' + r[0] + '\\', true)"> <input type="button" id="btnReject' + i + '" value="TỪ CHỐI" onclick="decide(\\'' + r[0] + '\\', false)"></td></tr>');
    }
    h.push('</table>');
    $("list").innerHTML = n ? h.join("") : "Không có lệnh chờ duyệt.";
  });
}
function decide(id, ok) { call("ApproveService", "decide", [id, ok ? "1" : "0"], function () { load(); }); }
"""

REPORT_BODY = """<h3>Báo nợ/có</h3><p>Tài khoản %s · %d giao dịch</p>
<form id="frmReport" method="post" action="/tp/exportPdf" target="pdfFrame"><input type="hidden" name="acct" value="%s"><input type="hidden" name="ids" value="%s"></form>
<iframe name="pdfFrame" id="pdfFrame" src="/tp/blank" style="width:96%%;height:340px;border:1px solid #ccd"></iframe>
<p><input type="button" class="b" id="btnClose" value="ĐÓNG" onclick="closeMe()"></p>"""

DIALOG_JS = """
function closeMe() { if (window.parent && window.parent !== window && window.parent.closeDialog) { window.parent.closeDialog(); } else { window.close(); } }
"""

DATA_BODY = """<h3>Báo nợ/có</h3><table class="g" id="tblAdvice">
<tr><td>Tên khách hàng</td><td id="vName"></td><td>Số tài khoản</td><td id="vAcc"></td></tr>
<tr><td>Loại tiền</td><td id="vCur"></td><td>Số tiền</td><td id="vAmt"></td></tr>
<tr><td>Chi nhánh</td><td id="vBranch"></td><td>Bằng chữ</td><td id="vWords"></td></tr></table>
<p><input type="button" class="b" id="btnClose" value="ĐÓNG" onclick="closeMe()"></p><div id="err" class="err"></div>"""

DATA_JS = """
function fillAdvice() {
  var host = window.dialogArguments || window.parent, data = host && host.__advice;
  if (!data) { $("err").innerHTML = "Không có dữ liệu"; return; }
  $("vName").innerHTML = data[0]; $("vAcc").innerHTML = data[1]; $("vCur").innerHTML = data[2];
  $("vAmt").innerHTML = money(data[3]); $("vBranch").innerHTML = data[4]; $("vWords").innerHTML = data[5];
}
"""

def _month_days() -> str:
    """One month grid, the way TouchPoint's monthCalendar lays days out: a button per day, its name the date it writes."""
    return "".join(
        f'<input type="button" class="day" id="calD{n}" name="{n:02d}/11/2026" value="{n}" onclick="pickDay(this)">'
        for n in range(1, 32)
    )


def acct_body(ui: int = 1) -> str:
    """The account screen. Look 2 (Gate 12 demo): the same words, but new ids and the search button before the field."""
    if ui < 2:
        return ACCT_BODY % _month_days()
    moved = ACCT_BODY.replace(
        '<table><tr><td>Số tài khoản</td><td><input type="text" id="txtAcct" name="txtAcct" onkeydown="if (event.keyCode == 13) { findAcct(); return false; }"></td>\n'
        '<td><input type="button" class="b" id="btnFind" value="TRA CỨU" onclick="findAcct()"></td></tr></table>',
        '<table><tr><td><input type="button" class="b" id="btnFind" value="TRA CỨU" onclick="findAcct()"></td>\n'
        '<td>Số tài khoản</td><td><input type="text" id="txtAcct" name="txtAcct" onkeydown="if (event.keyCode == 13) { findAcct(); return false; }"></td></tr></table>')
    assert moved != ACCT_BODY
    return (moved % _month_days()).replace("txtAcct", "txtAccountNo").replace("btnFind", "btnSearchAccount")


def acct_js(ui: int = 1, biz: int = 1) -> str:
    script = f"var BIZ = {int(biz)};" + ACCT_JS
    return script.replace("txtAcct", "txtAccountNo") if ui >= 2 else script


MSGBOX_BODY ="""<h3>Thông báo</h3><p class="err" id="msgText">%s</p><input type="button" class="b" id="btnOK" value="ĐỒNG Ý" onclick="closeMe()">"""


class TouchPoint:
    """The pages and the services. `handle()` answers one request: (status, headers, body)."""

    def __init__(self, title_prefix: str = "") -> None:
        self.prefix = title_prefix
        self.sessions: dict[str, dict[str, Any]] = {}
        self.transfers: list[dict[str, Any]] = []
        self.seen: list[str] = []          # what the services were asked (for tests): service.method(args)
        self.lock = threading.Lock()
        # Gate 12 (SADPT demo): ui 2 is a new look of the account screen (ids renamed, the search button moved, same words); biz 2 is
        # a business change (a new confirmation box after the search). A test sets them here; a person uses /tp/?ui=2 or /tp/?biz=2.
        self.ui, self.biz, self.ro = 1, 1, False

    def _variant(self, headers: dict[str, str]) -> tuple[int, int]:
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get("cookie", ""))
        except Exception:  # noqa: BLE001
            pass
        pick = lambda name, own: max(own, int(cookie[name].value) if name in cookie and cookie[name].value in ("1", "2") else 1)   # noqa: E731
        return pick("TPUI", self.ui), pick("TPBIZ", self.biz)

    def _readonly_dates(self, headers: dict[str, str]) -> bool:
        """`?ro=1` (cookie TPRO): «Từ ngày» cannot be typed, so a run that fills it stops and asks."""
        if self.ro:
            return True
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get("cookie", ""))
        except Exception:  # noqa: BLE001
            return False
        return "TPRO" in cookie and cookie["TPRO"].value == "1"

    # ---- helpers ---------------------------------------------------------------------------------------------------------

    def _session(self, headers: dict[str, str]) -> dict[str, Any] | None:
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get("cookie", ""))
        except Exception:  # noqa: BLE001
            return None
        sid = cookie.get("TPSESS")
        return self.sessions.get(sid.value) if sid else None

    @staticmethod
    def _html(body: bytes, extra: list[tuple[str, str]] | None = None) -> tuple[int, list[tuple[str, str]], bytes]:
        return 200, [("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-cache")] + (extra or []), body

    @staticmethod
    def _text(text: str, kind: str = "text/plain; charset=utf-8", status: int = 200) -> tuple[int, list[tuple[str, str]], bytes]:
        return status, [("Content-Type", kind), ("Cache-Control", "no-cache")], text.encode("utf-8")

    @staticmethod
    def _pdf(data: bytes, name: str | None = None) -> tuple[int, list[tuple[str, str]], bytes]:
        headers = [("Content-Type", "application/pdf"), ("Content-Length", str(len(data)))]
        if name:
            headers.append(("Content-Disposition", f'attachment; filename="{name}"'))
        return 200, headers, data

    @staticmethod
    def encode(values: list[Any], kind: str = "com.fis.tp.client.dto.Result/1834569801") -> str:
        """GWT-RPC's own shape: a list of numbers pointing (1-based) into a string table of unique strings, then the table, the
        flags and the version: `[3,2,1,["type","a","b"],0,7]`. The type name is the first string, as in a real answer."""
        table: list[str] = [kind]
        refs: list[int] = []
        for value in values:
            text = str(value)
            if text not in table:
                table.append(text)
            refs.append(table.index(text) + 1)
        return json.dumps(refs + [table, 0, 7], ensure_ascii=False, separators=(",", ":"))

    def _gwt(self, values: list[Any]) -> tuple[int, list[tuple[str, str]], bytes]:
        return self._text("//OK" + self.encode(values), "text/x-gwt-rpc; charset=utf-8")

    def encode_reply(self, values: list[Any], kind: str) -> tuple[int, list[tuple[str, str]], bytes]:
        return self._text("//OK" + self.encode(values, kind), "text/x-gwt-rpc; charset=utf-8")

    def _gwt_error(self, message: str) -> tuple[int, list[tuple[str, str]], bytes]:
        return self._text("//EX" + self.encode([message], "com.google.gwt.user.client.rpc.StatusCodeException/3924434141"),
                          "text/x-gwt-rpc; charset=utf-8")

    # ---- one request ------------------------------------------------------------------------------------------------------

    def handle(self, method: str, target: str, headers: dict[str, str], body: bytes) -> tuple[int, list[tuple[str, str]], bytes]:
        headers = {k.lower(): v for k, v in headers.items()}
        parts = urlsplit(target)
        path, query = parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()}
        form = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace")).items()} if method == "POST" and b"|" not in body[:4] else {}
        title = self.prefix + "Quầy mẫu"

        if path in ("/tp", "/tp/", "/tp/login") and method == "GET":
            extra = [("Set-Cookie", "TPDLG=inline; path=/")] if query.get("dlg") == "inline" else (
                [("Set-Cookie", "TPDLG=modal; path=/")] if query.get("dlg") == "modal" else [])
            for key, name in (("ui", "TPUI"), ("biz", "TPBIZ")):     # Gate 12 demo: /tp/?ui=2 or /tp/?biz=2 (1 goes back)
                if query.get(key) in ("1", "2"):
                    extra.append(("Set-Cookie", f"{name}={query[key]}; path=/"))
            if query.get("ro") in ("0", "1"):                         # task 12.6: /tp/?ro=1 makes the from-date read-only
                extra.append(("Set-Cookie", f"TPRO={query['ro']}; path=/"))
            return self._html(_doc(title + " – Đăng nhập", LOGIN_BODY % "", onload="document.getElementById('txtUser').focus()"), extra)
        if path == "/tp/login" and method == "POST":
            user = USERS.get(form.get("txtUser", ""))
            if user is None or user[0] != form.get("txtPw"):
                return self._html(_doc(title + " – Đăng nhập", LOGIN_BODY % "Sai tên đăng nhập hoặc mật khẩu."))
            sid = secrets.token_hex(12)
            with self.lock:
                self.sessions[sid] = {"user": form["txtUser"], "name": user[1], "role": user[2], "token": "", "tokens": 0}
            return 302, [("Location", "/tp/role"), ("Set-Cookie", f"TPSESS={sid}; path=/")], b""
        if path == "/tp/tp.js":
            return self._text(TP_JS.replace('"STRONG"', json.dumps(STRONG)), "application/javascript; charset=utf-8")
        if path == "/tp/blank":
            return self._html(b"<html><body></body></html>")
        if path == "/tp/health":
            return self._text('{"status":"ok"}', "application/json")

        session = self._session(headers)
        if session is not None:
            import statement_flow

            answered = statement_flow.dispatch(self, method, path, query, body, session)
            if answered is not None:
                return answered
        if session is None:
            if path.startswith(("/tp/TPClassLoader", "/tp/postAuthentication", "/tp/keepalive")):
                return self._text("Phiên đã hết hạn", status=401)
            return self._html(_doc(title + " – Đăng nhập", LOGIN_BODY % "Phiên đã hết hạn, đăng nhập lại."))

        if path == "/tp/role" and method == "GET":
            return self._html(_doc(title + " – Vai trò", ROLE_BODY % ""))
        if path == "/tp/role" and method == "POST":
            if form.get("role") != session["role"]:
                return self._html(_doc(title + " – Vai trò", ROLE_BODY % "Tài khoản này không có vai trò đó."))
            return 302, [("Location", "/tp/main")], b""
        if path == "/tp/main":
            frames = ('<frameset rows="34,*,0"><frame name="toolbar" src="/tp/toolbar" scrolling="no">'
                      '<frameset cols="210,*"><frame name="menu" src="/tp/menu"><frame name="work" src="/tp/desk"></frameset>'
                      '<frame name="rhidden" src="/tp/blank"></frameset>')
            return self._html(f"<html><head><title>{title}</title></head>{frames}</html>".encode("utf-8"))
        if path == "/tp/toolbar":
            return self._html(_doc("toolbar", f"<b>Quầy mẫu</b> · {session['name']} · "
                                              "<a id='lnkLogout' href='/tp/logout' target='_top'>Đăng xuất</a>"))
        if path == "/tp/menu":
            links = [("mnuAcct", "/tp/acct", "Tra cứu tài khoản"), ("mnuStmt", "/tp/stmt", "In sao kê đột xuất"),
                     ("mnuReport", "/tp/report", "Xuất báo cáo"), ("mnuTransfer", "/tp/transfer", "Lập lệnh chuyển tiền")]
            if session["role"] == "checker":
                links.append(("mnuApprove", "/tp/approve", "Phê duyệt lệnh"))
            items = "".join(f"<p><a id='{i}' href='{h}' target='work'>{t}</a></p>" for i, h, t in links)
            return self._html(_doc("menu", "<h3>Chức năng</h3>" + items))
        if path == "/tp/home":
            return self._html(_doc("Trang chủ", "<h3>Trang chủ</h3><p>Chọn chức năng ở bên trái.</p>"))
        if path == "/tp/acct":
            ui, biz = self._variant(headers)
            body_html = acct_body(ui)
            if self._readonly_dates(headers):
                body_html = body_html.replace('id="txtFrom" name="txtFrom"', 'id="txtFrom" name="txtFrom" readonly', 1)
            return self._html(_doc("Tra cứu tài khoản", body_html, acct_js(ui, biz)))
        if path == "/tp/report":
            return self._html(_doc("Xuất báo cáo", EXPORT_BODY % _month_days(), EXPORT_JS))
        if path == "/tp/transfer":
            body_html = TRANSFER_BODY
            if self._variant(headers)[0] >= 2:   # look 2: the money button renamed, with a new button before it (same words)
                body_html = body_html.replace('<input type="button" class="b" id="btnSubmit"',
                                              '<input type="button" class="b" id="btnClear" value="NHẬP LẠI" onclick="location.reload()"> '
                                              '<input type="button" class="b" id="btnSendForApproval"')
            return self._html(_doc("Chuyển tiền", body_html, TRANSFER_JS))
        if path == "/tp/approve":
            return self._html(_doc("Phê duyệt", APPROVE_BODY, APPROVE_JS))
        if path == "/tp/logout":
            with self.lock:
                self.sessions = {k: v for k, v in self.sessions.items() if v is not session}
            return 302, [("Location", "/tp/"), ("Set-Cookie", "TPSESS=; path=/")], b""
        if path == "/tp/keepalive":
            return self._text('{"alive":true}', "application/json")

        if path == "/tp/postAuthentication.fisglobal" and query.get("method") == "getToken":
            with self.lock:
                session["tokens"] += 1
                payload = hashlib.sha256(f"{session['user']}:{session['tokens']}:{time.time()}".encode()).hexdigest()[:24]
                session["token"] = f"eyJhbGciOiJIUzI1NiJ9.{payload}.c2ln{session['tokens']}"
            return self._text("\n" + session["token"] + "\n")
        if path == "/tp/TPClassLoader" and method == "POST":
            if headers.get("authorization") != "Bearer " + session["token"] or not session["token"]:
                return self._text("Mã xác thực không hợp lệ", status=401)
            return self._service(session, body.decode("utf-8", "replace"))

        if path == "/tp/viewReport.jsp":
            ids = [x for x in query.get("ids", "").split(",") if x]
            body_html = REPORT_BODY % (query.get("acct", ""), len(ids), query.get("acct", ""), query.get("ids", ""))
            return self._html(_doc(title + " – Báo nợ/có", body_html, DIALOG_JS, onload="document.getElementById('frmReport').submit()"))
        if path == "/tp/viewData.jsp":
            return self._html(_doc(title + " – Báo nợ/có", DATA_BODY, DIALOG_JS + DATA_JS, onload="fillAdvice()"))
        if path == "/tp/utilities/dlgMessageBox.jsp":
            text = query.get("msg", "")
            safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return self._html(_doc(title + " – Thông báo", MSGBOX_BODY % safe, DIALOG_JS))
        if path == "/tp/rpt/file.pdf":
            held = (session.get("reports") or {}).get(query.get("key", ""))
            if not held:
                return self._text("Mã báo cáo không còn hoặc không đúng", status=404)
            start, end = parse_day(held["from"]), parse_day(held["to"])
            rows = history_of(held["acct"], start, end) if start and end else []
            lines = ["BAO CAO GIAO DICH (gia lap)", f"Tai khoan: {held['acct']}", f"Chu TK: {plain(held['name'])}",
                     f"Tu {held['from']} den {held['to']}"]
            lines += [f"{r['id']} {r['date']} {plain(r['desc'])} No {r['debit']} Co {r['credit']}" for r in rows[:12]]
            self.seen.append(f"reportFile({held['acct']})")
            return self._pdf(pdf(lines), "BaoCao.pdf")
        if path == "/tp/exportPdf" and method == "POST":
            ids = [x for x in form.get("ids", "").split(",") if x]
            self.seen.append(f"exportPdf({form.get('acct', '')},{len(ids)})")
            account = account_of(form.get("acct", "")) or {"number": form.get("acct", ""), "name": "?"}
            return self._pdf(pdf(["BAO NO / BAO CO (gia lap)", f"Tai khoan: {account['number']}", f"Chu TK: {account['name']}"]
                                 + [f"Giao dich: {i}" for i in ids]))
        if path == "/tp/statement.pdf":
            self.seen.append(f"statement({query.get('acct', '')},{query.get('from', '')},{query.get('to', '')})")
            return self._pdf(pdf(["SAO KE TAI KHOAN (gia lap)", f"Tai khoan: {query.get('acct', '')}",
                                  f"Tu {query.get('from', '')} den {query.get('to', '')}"]))
        if path == "/tp/exportExcel" and method == "POST":
            self.seen.append(f"excel({form.get('acct', '')},{form.get('from', '')},{form.get('to', '')})")
            rows = ["Ma GD,Ngay,Noi dung,No,Co,So du"]
            start, end = parse_day(form.get("from", "")), parse_day(form.get("to", ""))
            if start and end:
                rows += [f"{r['id']},{r['date']},{plain(r['desc'])},{r['debit']},{r['credit']},{r['balance']}" for r in history_of(form.get("acct", ""), start, end)]
            data = ("\n".join(rows) + "\n").encode("utf-8")
            return 200, [("Content-Type", "text/csv"), ("Content-Disposition", 'attachment; filename="SaoKe.csv"'), ("Content-Length", str(len(data)))], data
        return self._text("Không có trang này", status=404)

    # ---- services (GWT-RPC look-alike) ------------------------------------------------------------------------------------

    def _service(self, session: dict[str, Any], body: str) -> tuple[int, list[tuple[str, str]], bytes]:
        fields = [f.replace("\\!", "|").replace("\\\\", "\\") for f in body.split("|")]
        if len(fields) < 7 or fields[0] != "7":
            return self._gwt_error("Yêu cầu không hợp lệ")
        service, name, args = fields[5].rsplit(".", 1)[-1], fields[6], [f for f in fields[7:] if f != ""]
        self.seen.append(f"{service}.{name}({','.join(args)})")
        if service == "AcctService" and name == "find":
            account = account_of(args[0] if args else "")
            if account is None:
                return self._gwt_error("Không tìm thấy tài khoản")
            return self._gwt([account["number"], account["name"], account["branch"], account["balance"], account["currency"]])
        if service == "HistoryService" and name == "list" and len(args) == 3:
            start, end = parse_day(args[1]), parse_day(args[2])
            if start is None or end is None or start > end:
                return self._gwt_error("Khoảng ngày không hợp lệ")
            rows = history_of(args[0], start, end)
            return self._gwt([len(rows)] + [v for r in rows for v in (r["id"], r["date"], r["desc"], r["debit"], r["credit"], r["balance"])])
        if service == "ReportService" and name == "export" and len(args) >= 3:
            account = account_of(args[0])
            start, end = parse_day(args[1]), parse_day(args[2])
            if account is None:
                return self._gwt_error("Không tìm thấy tài khoản")
            if start is None or end is None or start > end:
                return self._gwt_error("Khoảng ngày không hợp lệ")
            key = secrets.token_hex(8)
            with self.lock:
                session.setdefault("reports", {})[key] = {"acct": account["number"], "name": account["name"], "from": args[1], "to": args[2]}
            # a code, not the file: the address of the file is one string of the answer, and the type is a document type so a
            # recording keeps it as a file. The bytes are the code; the PDF is the address it names.
            return self._text("//OK" + self.encode([f"/tp/rpt/file.pdf?key={key}"], "lab.counter.report.ReportKey/1000000001"),
                              "application/octet-stream")
        if service == "ReportService" and name == "debitAdvice" and args:
            account = account_of(args[0])
            if account is None:
                return self._gwt_error("Không tìm thấy tài khoản")
            amount = 10_944 + 137 * len([i for i in (args[1] if len(args) > 1 else "").split(",") if i])
            return self.encode_reply([account["name"], account["number"], "EUR", str(amount), account["branch"], f"So tien {amount} euro"],
                                     "com.fis.tp.client.dto.DebitAdvice/1234567890")
        if service == "TransferService" and name == "create" and len(args) >= 3:
            if account_of(args[0]) is None or account_of(args[1]) is None:
                return self._gwt_error("Tài khoản không hợp lệ")
            with self.lock:
                order = {"id": f"LX{len(self.transfers) + 1:05d}", "from": args[0], "to": args[1], "amount": int(args[2]), "status": "pending",
                         "maker": session["user"]}
                self.transfers.append(order)
            return self._gwt([order["id"], "Chờ duyệt"])
        if service == "ApproveService" and name == "list":
            if session["role"] != "checker":
                return self._gwt_error("Chỉ kiểm soát viên được duyệt")
            pending = [t for t in self.transfers if t["status"] == "pending"]
            return self._gwt([len(pending)] + [v for t in pending for v in (t["id"], t["from"], t["to"], t["amount"])])
        if service == "ApproveService" and name == "decide" and len(args) == 2:
            if session["role"] != "checker":
                return self._gwt_error("Chỉ kiểm soát viên được duyệt")
            for t in self.transfers:
                if t["id"] == args[0] and t["status"] == "pending":
                    t["status"] = "approved" if args[1] == "1" else "rejected"
                    return self._gwt([t["id"], t["status"]])
            return self._gwt_error("Không thấy lệnh")
        return self._gwt_error("Dịch vụ không có")
