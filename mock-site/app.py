"""Mock business site: login, end-of-day reports, CIF, transfers and approvals.

Synthetic data only. The "giao diện mới" switch changes element ids, the search
button name and the layout so self-healing has something to recover from.
"""

import csv
import io
import secrets
from datetime import date as date_type
from html import escape
from typing import Literal
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from pydantic import BaseModel

import banking_pages
from banking import Bank, BankError, Customer, Transfer
from data import Row, generate_reports
from layout import page

DEMO_USER = "gdv01"
DEMO_PASSWORD = "demo-only-1234"
CHECKER_USER = "ksv01"
CHECKER_PASSWORD = "demo-only-5678"
# username -> (password, role). Synthetic accounts for the mock only.
USERS = {
    DEMO_USER: (DEMO_PASSWORD, "maker"),
    CHECKER_USER: (CHECKER_PASSWORD, "checker"),
}
SEED = 42
SESSION_COOKIE = "session"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
CSV_COLUMNS = ["id", "account", "customer", "amount", "status"]

UI_IDS: dict[str, dict[str, str]] = {
    "v1": {
        "tab_a": "tab-a",
        "tab_b": "tab-b",
        "date": "f-date",
        "account": "f-account",
        "search": "btn-search",
        "export": "btn-export",
        "table": "tbl-report",
    },
    "v2": {
        "tab_a": "nav-report-a",
        "tab_b": "nav-report-b",
        "date": "filter-ngay",
        "account": "filter-tai-khoan",
        "search": "action-lookup",
        "export": "action-download",
        "table": "grid-ket-qua",
    },
}
SEARCH_LABEL = {"v1": "Tìm kiếm", "v2": "Tra cứu"}

app = FastAPI(title="Rookie Agent Mock Site")

# token -> session state. In-memory is enough for a mock.
_sessions: dict[str, dict[str, str]] = {}

bank = Bank(seed=SEED)


def reset_bank() -> None:
    """Put customers and transfers back to the seeded state (used by tests and demos)."""
    global bank
    bank = Bank(seed=SEED)


@app.exception_handler(BankError)
def bank_error_handler(_: Request, error: BankError) -> JSONResponse:
    return JSONResponse({"detail": error.message}, status_code=error.status)


def _session(request: Request) -> dict[str, str] | None:
    return _sessions.get(request.cookies.get(SESSION_COOKIE, ""))


def _require_session(request: Request) -> dict[str, str]:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    return session


def _login_page(error: str = "") -> str:
    error_html = f'<p class="error" role="alert">{escape(error)}</p>' if error else ""
    return page(
        "Đăng nhập",
        f"""<h1>Đăng nhập</h1>
{error_html}
<form method="post" action="/login">
  <p><label for="username">Tên đăng nhập</label><br><input id="username" name="username" autocomplete="username"></p>
  <p><label for="password">Mật khẩu</label><br><input id="password" name="password" type="password" autocomplete="current-password"></p>
  <button id="btn-login" type="submit">Đăng nhập</button>
</form>""",
        nav=False,
    )


def _report_page(ui: str) -> str:
    ids = UI_IDS[ui]
    tabs = f"""<div class="tabs" role="tablist">
  <button id="{ids['tab_a']}" role="tab" data-source="a" aria-selected="true">Báo cáo A</button>
  <button id="{ids['tab_b']}" role="tab" data-source="b" aria-selected="false">Báo cáo B</button>
</div>"""
    filters = f"""<div class="bar{' reverse' if ui == 'v2' else ''}">
  <div><label for="{ids['date']}">Ngày báo cáo</label><br><input id="{ids['date']}" name="report_date" type="date"></div>
  <div><label for="{ids['account']}">Số tài khoản</label><br><input id="{ids['account']}" name="account" inputmode="numeric"></div>
  <button id="{ids['search']}" type="button">{SEARCH_LABEL[ui]}</button>
  <button id="{ids['export']}" type="button">Xuất CSV</button>
</div>"""
    # New UI moves the filters above the tabs.
    controls = filters + tabs if ui == "v2" else tabs + filters
    switch_label = "Về giao diện cũ" if ui == "v2" else "Giao diện mới"
    return page(
        "Báo cáo cuối ngày",
        f"""<h1>Báo cáo cuối ngày</h1>
<p><a id="ui-toggle" href="/ui/toggle">{switch_label}</a></p>
{controls}
<p id="status" role="status"></p>
<table id="{ids['table']}">
  <thead><tr><th>Mã giao dịch</th><th>Số tài khoản</th><th>Khách hàng</th><th>Số tiền</th><th>Trạng thái</th></tr></thead>
  <tbody></tbody>
</table>
<script>
  const ids = {ids!r};
  let source = "a";
  const el = (key) => document.getElementById(ids[key]);
  function query() {{
    const params = new URLSearchParams({{source, date: el("date").value}});
    if (el("account").value) params.set("account", el("account").value);
    return params.toString();
  }}
  async function search() {{
    const status = document.getElementById("status");
    const body = el("table").querySelector("tbody");
    body.replaceChildren();
    if (!el("date").value) {{ status.textContent = "Chọn ngày báo cáo."; return; }}
    const response = await fetch("/api/report?" + query());
    if (!response.ok) {{ status.textContent = "Không tải được báo cáo."; return; }}
    const rows = (await response.json()).rows;
    for (const row of rows) {{
      const tr = document.createElement("tr");
      for (const key of ["id", "account", "customer", "amount", "status"]) {{
        const td = document.createElement("td");
        td.textContent = row[key];
        if (key === "amount") td.className = "num";
        tr.appendChild(td);
      }}
      body.appendChild(tr);
    }}
    status.textContent = "Báo cáo " + source.toUpperCase() + ": " + rows.length + " dòng";
  }}
  for (const key of ["tab_a", "tab_b"]) {{
    el(key).addEventListener("click", () => {{
      source = el(key).dataset.source;
      el("tab_a").setAttribute("aria-selected", String(source === "a"));
      el("tab_b").setAttribute("aria-selected", String(source === "b"));
      el("table").querySelector("tbody").replaceChildren();
      document.getElementById("status").textContent = "";
    }});
  }}
  el("search").addEventListener("click", search);
  el("export").addEventListener("click", () => {{
    if (el("date").value) window.location.href = "/api/report.csv?" + query();
  }});
</script>""",
    )


def _rows(source: str, date: str, account: str | None) -> list[Row]:
    try:
        date_type.fromisoformat(date)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Ngày không hợp lệ") from error
    report_a, report_b = generate_reports(date, seed=SEED)
    rows = report_a if source == "a" else report_b
    if account:
        rows = [row for row in rows if row["account"] == account]
    return rows


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "mock-site"}


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse("/baocao/cuoingay", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_form() -> str:
    return _login_page()


@app.post("/login")
async def login(request: Request):
    # Parsed by hand so the mock does not need python-multipart.
    form = parse_qs((await request.body()).decode("utf-8"))
    username = form.get("username", [""])[0]
    password = form.get("password", [""])[0]
    expected_password, role = USERS.get(username, ("", ""))
    if not role or not secrets.compare_digest(password.encode(), expected_password.encode()):
        return HTMLResponse(_login_page("Sai tên đăng nhập hoặc mật khẩu."), status_code=401)
    token = secrets.token_urlsafe(24)
    _sessions[token] = {"user": username, "role": role, "ui": "v1"}
    response = RedirectResponse("/baocao/cuoingay", status_code=303)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
    return response


@app.get("/logout")
def logout(request: Request) -> RedirectResponse:
    _sessions.pop(request.cookies.get(SESSION_COOKIE, ""), None)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/ui/toggle")
def toggle_ui(request: Request) -> RedirectResponse:
    session = _session(request)
    if session is None:
        return RedirectResponse("/login", status_code=303)
    session["ui"] = "v1" if session["ui"] == "v2" else "v2"
    return RedirectResponse("/baocao/cuoingay", status_code=303)


@app.get("/baocao/cuoingay")
def report_page(request: Request):
    session = _session(request)
    if session is None:
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse(_report_page(session["ui"]))


@app.get("/api/report")
def api_report(
    request: Request,
    source: Literal["a", "b"],
    date: str = Query(pattern=DATE_PATTERN),
    account: str | None = None,
) -> dict[str, object]:
    _require_session(request)
    return {"source": source, "date": date, "rows": _rows(source, date, account)}


@app.get("/api/report.csv")
def api_report_csv(
    request: Request,
    source: Literal["a", "b"],
    date: str = Query(pattern=DATE_PATTERN),
    account: str | None = None,
) -> PlainTextResponse:
    _require_session(request)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(_rows(source, date, account))
    return PlainTextResponse(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="bao-cao-{source}-{date}.csv"'},
    )


class OpenCifRequest(BaseModel):
    name: str
    id_number: str
    phone: str


class TransferRequest(BaseModel):
    from_account: str
    to_account: str
    amount: int
    note: str = ""


def _html_or_login(request: Request, html: str):
    if _session(request) is None:
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse(html)


@app.get("/cif")
def cif_page(request: Request):
    return _html_or_login(request, banking_pages.cif_page())


@app.get("/chuyentien")
def transfer_page(request: Request):
    return _html_or_login(request, banking_pages.transfer_page())


@app.get("/pheduyet")
def approval_page(request: Request):
    return _html_or_login(request, banking_pages.approval_page())


@app.get("/api/cif")
def api_find_cif(request: Request, q: str) -> dict[str, list[Customer]]:
    _require_session(request)
    return {"customers": bank.find_customers(q)}


@app.post("/api/cif", status_code=201)
def api_open_cif(request: Request, payload: OpenCifRequest) -> Customer:
    _require_session(request)
    return bank.open_cif(payload.name, payload.id_number, payload.phone)


@app.get("/api/transfers")
def api_list_transfers(
    request: Request, status: Literal["pending", "approved", "rejected"] | None = None
) -> dict[str, list[Transfer]]:
    _require_session(request)
    return {"transfers": bank.list_transfers(status)}


@app.post("/api/transfers", status_code=201)
def api_create_transfer(request: Request, payload: TransferRequest) -> Transfer:
    session = _require_session(request)
    return bank.create_transfer(
        session["user"], payload.from_account, payload.to_account, payload.amount, payload.note
    )


def _decide(request: Request, transfer_id: str, approve: bool) -> Transfer:
    session = _require_session(request)
    if session["role"] != "checker":
        raise BankError(403, "Chỉ kiểm soát viên được phê duyệt")
    return bank.decide_transfer(transfer_id, session["user"], approve)


@app.post("/api/transfers/{transfer_id}/approve")
def api_approve_transfer(request: Request, transfer_id: str) -> Transfer:
    return _decide(request, transfer_id, approve=True)


@app.post("/api/transfers/{transfer_id}/reject")
def api_reject_transfer(request: Request, transfer_id: str) -> Transfer:
    return _decide(request, transfer_id, approve=False)
