"""Ad-hoc statement print for the lab counter (Quầy mẫu).

The same shape as the legacy print flow, with synthetic data only: a dialog, one XML post for each step
(fee, transactions, build the report, a local note), then the answer names a PDF on this site and the page opens it.
Nothing here is the production desktop, and the file is only served inside the signed-in session.
"""

from __future__ import annotations

import secrets
import xml.etree.ElementTree as ET
from typing import Any

import touchpoint

FEE = 20_000
VAT_RATE = 10


def dispatch(tp: touchpoint.TouchPoint, method: str, path: str, query: dict[str, str], body: bytes,
             session: dict[str, Any]) -> tuple[int, list[tuple[str, str]], bytes] | None:
    """The statement pages and their posts. None when the path is not part of this flow."""
    if path == "/tp/stmt":
        return tp._html(touchpoint._doc("In sao kê đột xuất", STMT_BODY, STMT_JS))
    if path == "/tp/print/dlgStatement.jsp":
        page = DLG_BODY.replace("__DAYS__", touchpoint._month_days())
        return tp._html(touchpoint._doc("In sao kê đột xuất", page, DLG_JS, onload="start()"))
    if path == "/tp/facade" and method == "POST":
        return _facade(tp, session, body)
    if path == "/tp/stmt/note" and method == "POST":
        return _xml(ET.Element("OK"))
    held = _held(session, path)
    if held is not None:
        return _pdf(tp, held)
    return None


def _held(session: dict[str, Any], path: str) -> dict[str, Any] | None:
    name = path.rsplit("/", 1)[-1]
    for prefix in ("saoKe", "bienLai"):
        if name.startswith(prefix) and name.endswith(".pdf"):
            key = name[len(prefix):-4]
            return (session.get("statements") or {}).get(key)
    return None


def _pdf(tp: touchpoint.TouchPoint, held: dict[str, Any]) -> tuple[int, list[tuple[str, str]], bytes]:
    account = touchpoint.account_of(held["acct"]) or {"number": held["acct"], "name": "?"}
    start, end = touchpoint.parse_day(held["from"]), touchpoint.parse_day(held["to"])
    rows = touchpoint.history_of(held["acct"], start, end) if start and end else []
    if held.get("kind") == "fee":
        lines = ["BIEN LAI THU PHI (gia lap)", f"Tai khoan: {account['number']}", f"Phi: {FEE}", f"VAT: {FEE * VAT_RATE // 100}"]
        tp.seen.append(f"feeVoucher({account['number']})")
        return tp._pdf(touchpoint.pdf(lines), "BienLai.pdf")
    opening = rows[0]["balance"] - rows[0]["credit"] + rows[0]["debit"] if rows else account.get("balance", 0)
    closing = rows[-1]["balance"] if rows else opening
    lines = ["SAO KE TAI KHOAN (gia lap)", f"Tai khoan: {account['number']}", f"Chu TK: {touchpoint.plain(account['name'])}",
             f"Tu {held['from']} den {held['to']}", f"So du dau: {opening}", f"So du cuoi: {closing}"]
    lines += [f"{r['date']} {touchpoint.plain(r['desc'])} No {r['debit']} Co {r['credit']} Du {r['balance']}" for r in rows[:12]]
    tp.seen.append(f"statementPdf({account['number']})")
    return tp._pdf(touchpoint.pdf(lines), "SaoKe.pdf")


def _facade(tp: touchpoint.TouchPoint, session: dict[str, Any], body: bytes) -> tuple[int, list[tuple[str, str]], bytes]:
    text = body.decode("utf-8", "replace")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        return _error("Yêu cầu không hợp lệ")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return _error("Yêu cầu không hợp lệ")
    service = root.find(".//SERVICE")
    name = service.get("name") if service is not None else ""
    params = {el.get("name"): (el.text or "").strip() for el in root.iter("PARAM") if el.get("name")}
    for el in root.iter("FORM_DETAIL"):
        for child in list(el):
            if child.tag != "TRAN_DETAILS":
                params.setdefault(child.tag, (child.text or "").strip())
    if name == "StmtFeeRq":
        account = touchpoint.account_of(params.get("ACCT_NBR", ""))
        tp.seen.append(f"feeInq({params.get('ACCT_NBR', '')})")
        if account is None:
            return _error("Không tìm thấy tài khoản")
        return _xml(_fee(account))
    if name == "StmtHistoryRq":
        return _transactions(tp, params)
    if name == "StmtFeePostRq":
        tp.seen.append(f"xferAdd({params.get('ACCT_NBR', '')})")
        return _issue(tp, session, params, "bienLai", "fee")
    if root.find(".//FORM_TEMPLATE") is not None:
        return _issue(tp, session, params, "saoKe", "statement")
    return _error("Dịch vụ không có")


def _transactions(tp: touchpoint.TouchPoint, params: dict[str, str]) -> tuple[int, list[tuple[str, str]], bytes]:
    account = touchpoint.account_of(params.get("ACCT_NBR", ""))
    start, end = touchpoint.parse_day(params.get("START_DATE", "")), touchpoint.parse_day(params.get("END_DATE", ""))
    tp.seen.append(f"depAcctTrnInq({params.get('ACCT_NBR', '')})")
    if account is None:
        return _error("Không tìm thấy tài khoản")
    if start is None or end is None or start > end or (end - start).days > 365:
        return _error("Khoảng ngày không hợp lệ")
    out = ET.Element("TRANS_OUTPUT")
    ET.SubElement(out, "StatusCode").text = "0"
    box = ET.SubElement(out, "TRANSACTIONS")
    for row in touchpoint.history_of(account["number"], start, end):
        item = ET.SubElement(box, "TRANSACTION")
        ET.SubElement(item, "TRANS_DATE").text = row["date"]
        ET.SubElement(item, "TRANS_DESCRIPTION").text = row["desc"]
        ET.SubElement(item, "TRANS_AMT").text = str(row["debit"] or row["credit"])
        ET.SubElement(item, "TRANS_TYPE").text = "D" if row["debit"] else "C"
        ET.SubElement(item, "TRANS_TOT_BAL").text = str(row["balance"])
    return _xml(out)


def _issue(tp: touchpoint.TouchPoint, session: dict[str, Any], params: dict[str, str], prefix: str,
           kind: str) -> tuple[int, list[tuple[str, str]], bytes]:
    acct = params.get("ACCT_NUM") or params.get("ACCT_NBR") or ""
    start_text, end_text = params.get("TRN_FROM_DATE", ""), params.get("TRN_TO_DATE", "")
    account = touchpoint.account_of(acct)
    start, end = touchpoint.parse_day(start_text), touchpoint.parse_day(end_text)
    if account is None:
        return _error("Không tìm thấy tài khoản")
    if kind == "statement" and (start is None or end is None or start > end or (end - start).days > 365):
        return _error("Khoảng ngày không hợp lệ")
    key = secrets.token_hex(8)
    with tp.lock:
        session.setdefault("statements", {})[key] = {"acct": account["number"], "from": start_text, "to": end_text, "kind": kind}
    path = f"/tp/rpt/{prefix}{key}.pdf"
    tp.seen.append(f"generate({kind},{account['number']})")
    out = ET.Element("REPORT")
    ET.SubElement(out, "FILE_PATH").text = path
    return _xml(out)


def _fee(account: dict[str, Any]) -> ET.Element:
    root = ET.Element("FEE_DETAILS")
    ET.SubElement(root, "FEE_AMT").text = str(FEE)
    ET.SubElement(root, "VAT_PERCENTAGE").text = str(VAT_RATE)
    ET.SubElement(root, "VAT_AMT").text = str(FEE * VAT_RATE // 100)
    ET.SubElement(root, "FEE_CONFIGURED").text = "Y"
    ET.SubElement(root, "ACCT_TITLE").text = account["name"]
    ET.SubElement(root, "BRANCH_NAME").text = account["branch"]
    return root


def _error(message: str) -> tuple[int, list[tuple[str, str]], bytes]:
    root = ET.Element("ERROR")
    ET.SubElement(root, "StatusCode").text = "1"
    ET.SubElement(root, "Message").text = message
    return _xml(root)


def _xml(root: ET.Element) -> tuple[int, list[tuple[str, str]], bytes]:
    data = ET.tostring(root, encoding="utf-8")
    return 200, [("Content-Type", "text/xml; charset=utf-8"), ("Cache-Control", "no-cache")], data


STMT_BODY = """<h3>In sao kê đột xuất</h3>
<table><tr><td>Số tài khoản</td><td><input type="text" id="txtAcct" name="txtAcct"></td>
<td><input type="button" class="b" id="btnOpen" value="IN SAO KÊ ĐỘT XUẤT" onclick="openStmt()"></td></tr></table>
<p>Mở hộp thoại, chọn ngày, rồi bấm In sao kê. Hệ thống trả về mã file. Trang tự mở PDF của mã đó.</p>"""

STMT_JS = """
function openStmt() {
  var v = $("txtAcct").value.replace(/\\s/g, "");
  if (!/^\\d{6,14}$/.test(v)) { msgBox("Nhập số tài khoản (6 đến 14 chữ số)."); return; }
  openDialog("/tp/print/dlgStatement.jsp?acct=" + encodeURIComponent(v));
}
"""

DLG_BODY = """<h3>In sao kê đột xuất</h3>
<p>Tài khoản <b id="vAcct"></b> · <span id="vName"></span> · <span id="vBranch"></span></p>
<table><tr><td>Từ ngày</td><td><input type="text" id="dtFrom" size="10"> <input type="button" class="cal" id="btnCalFrom" name="cal-dtFrom" value="Lịch" onclick="openCal('dtFrom')"></td>
<td>Đến ngày</td><td><input type="text" id="dtTo" size="10"> <input type="button" class="cal" id="btnCalTo" name="cal-dtTo" value="Lịch" onclick="openCal('dtTo')"></td></tr></table>
<div id="calBox" style="display:none;margin-top:6px;padding:4px;border:1px solid #234;background:#fff"><div>Tháng 11 năm 2026</div>__DAYS__
<input type="button" id="calClose" value="Đóng" onclick="closeCal()"></div>
<table class="g" id="tblAccounts"><tr><th></th><th>Số tài khoản</th><th>Loại</th><th>Chủ tài khoản</th></tr>
<tr><td><input type="checkbox" id="chkAcct0"></td><td id="acct0"></td><td>Tiền gửi</td><td id="name0"></td></tr></table>
<table><tr><td>Phí</td><td><input id="txtFeeAmt" size="10" readonly></td><td>VAT %</td><td><input id="txtVatRate" size="4" readonly></td>
<td>VAT</td><td><input id="txtVatAmt" size="10" readonly></td><td>Tổng</td><td><input id="txtTotalFeeAmt" size="10" readonly></td></tr>
<tr><td colspan="4"><input type="checkbox" id="chkWaive"> Miễn phí</td><td>Lý do</td><td colspan="3"><select id="cboReason">
<option value=""></option><option value="1">Khách hàng ưu tiên</option><option value="2">Lỗi hệ thống</option></select></td></tr></table>
<p><input type="button" class="b" id="btnPrint" value="IN SAO KÊ" onclick="printClicked()">
<input type="button" id="btnFee" value="HẠCH TOÁN PHÍ" onclick="chargeFee()">
<input type="button" id="btnClose" value="ĐÓNG" onclick="closeMe()"> <span id="stmtStatus"></span></p>"""

DLG_JS = r"""
var acct = "", calFor = "";
function tag(xml, name) { var m = new RegExp("<" + name + ">([^<]*)</" + name + ">").exec(xml); return m ? m[1] : ""; }
function postXml(url, body) {
  var r = xhr();
  r.open("POST", url, false);
  r.setRequestHeader("Content-Type", "text/xml; charset=utf-8");
  r.send(body);
  return r.responseText || "";
}
function queryAcct() { var m = /acct=(\d+)/.exec(String(window.location.search)); return m ? m[1] : ""; }
function dayOf(v) { var p = String(v).split("/"); if (p.length !== 3) { return null; } return new Date(parseInt(p[2], 10), parseInt(p[1], 10) - 1, parseInt(p[0], 10)); }
function openCal(id) { calFor = id; $("calBox").style.display = "block"; }
function closeCal() { $("calBox").style.display = "none"; calFor = ""; }
function pickDay(btn) {
  var input = $(calFor); if (!input) { return; } input.value = btn.name; closeCal();
}
function fillFee() {
  var xml = postXml("/tp/facade", '<REMOTE><CALLS><SERVICE name="StmtFeeRq"><PARAM name="ACCT_NBR">' + acct + "</PARAM></SERVICE></CALLS></REMOTE>");
  var fee = tag(xml, "FEE_AMT"), vat = tag(xml, "VAT_AMT"), title = tag(xml, "ACCT_TITLE");
  $("txtFeeAmt").value = fee; $("txtVatRate").value = tag(xml, "VAT_PERCENTAGE"); $("txtVatAmt").value = vat;
  $("txtTotalFeeAmt").value = String((parseInt(fee, 10) || 0) + (parseInt(vat, 10) || 0));
  $("vName").innerHTML = title; $("vBranch").innerHTML = tag(xml, "BRANCH_NAME"); $("name0").innerHTML = title;
}
function printClicked() {
  var from = $("dtFrom").value, to = $("dtTo").value, a = dayOf(from), b = dayOf(to), xml, file, err;
  if (!a || !b) { msgBox("Sai định dạng ngày. Nhập theo dd/mm/yyyy."); return; }
  if (b.getTime() < a.getTime()) { msgBox("Từ ngày phải trước hoặc bằng đến ngày."); return; }
  if ((b.getTime() - a.getTime()) / 86400000 > 365) { msgBox("Khoảng ngày không được quá 365 ngày."); return; }
  if ($("chkWaive").checked && $("cboReason").value === "") { msgBox("Chọn lý do miễn phí."); return; }
  if (!$("chkAcct0").checked) { msgBox("Chọn ít nhất một tài khoản."); return; }
  $("stmtStatus").innerHTML = "Đang lấy giao dịch...";
  xml = postXml("/tp/facade", '<REMOTE><CALLS><SERVICE name="StmtHistoryRq"><PARAM name="ACCT_NBR">' + acct
    + '</PARAM><PARAM name="START_DATE">' + from + '</PARAM><PARAM name="END_DATE">' + to + "</PARAM></SERVICE></CALLS></REMOTE>");
  err = tag(xml, "Message"); if (err) { msgBox(err); return; }
  $("stmtStatus").innerHTML = "Đang tạo báo cáo...";
  xml = postXml("/tp/facade", "<REMOTE><FORM_DETAILS><FORM_DETAIL><FORM_TEMPLATE>saoKe</FORM_TEMPLATE><DOCUMENT_TYPE>PDF</DOCUMENT_TYPE><ACCT_NUM>"
    + acct + "</ACCT_NUM><TRN_FROM_DATE>" + from + "</TRN_FROM_DATE><TRN_TO_DATE>" + to + "</TRN_TO_DATE></FORM_DETAIL></FORM_DETAILS></REMOTE>");
  file = tag(xml, "FILE_PATH"); err = tag(xml, "Message");
  if (!file) { msgBox(err || "Không tạo được báo cáo."); return; }
  postXml("/tp/stmt/note", "<REMOTE><ACCOUNT_STATEMENT><ACCT_NO>" + acct + "</ACCT_NO><HIST_FROM_DATE>" + from + "</HIST_FROM_DATE><HIST_TO_DATE>" + to + "</HIST_TO_DATE></ACCOUNT_STATEMENT></REMOTE>");
  $("stmtStatus").innerHTML = "Đã nhận mã. Đang mở báo cáo...";
  window.open(file, "_blank");
}
function chargeFee() {
  var from = $("dtFrom").value, to = $("dtTo").value, xml, file;
  if (!$("chkAcct0").checked) { msgBox("Chọn tài khoản thu phí."); return; }
  xml = postXml("/tp/facade", '<REMOTE><CALLS><SERVICE name="StmtFeePostRq"><PARAM name="ACCT_NBR">' + acct
    + '</PARAM><PARAM name="TRN_FROM_DATE">' + from + '</PARAM><PARAM name="TRN_TO_DATE">' + to + "</PARAM></SERVICE></CALLS></REMOTE>");
  file = tag(xml, "FILE_PATH");
  if (!file) { msgBox(tag(xml, "Message") || "Không thu được phí."); return; }
  window.open(file, "_blank");
}
function start() {
  acct = queryAcct(); $("vAcct").innerHTML = acct; $("acct0").innerHTML = acct;
  fillFee();
}
"""
