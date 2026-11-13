"""Mock business site: login and the two end-of-day reports.

Synthetic data only. The "giao diện mới" switch changes element ids, the search
button name and the layout so self-healing has something to recover from.
"""

import csv
import io
import re
import secrets
from datetime import date as date_type
from html import escape
from typing import Literal
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from data import Row, generate_reports

DEMO_USER = "gdv01"
DEMO_PASSWORD = "demo-only-1234"
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


def _session(request: Request) -> dict[str, str] | None:
    return _sessions.get(request.cookies.get(SESSION_COOKIE, ""))


def _require_session(request: Request) -> dict[str, str]:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    return session


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 24px; }}
  .bar {{ display: flex; gap: 12px; align-items: end; margin: 12px 0; }}
  .bar.reverse {{ flex-direction: row-reverse; justify-content: flex-end; }}
  .tabs button[aria-selected="true"] {{ font-weight: bold; }}
  table {{ border-collapse: collapse; }}
  th, td {{ border: 1px solid #999; padding: 4px 8px; }}
  td.num {{ text-align: right; }}
  .error {{ color: #b00020; }}
</style>
</head>
<body>
{body}
</body>
</html>"""


def _login_page(error: str = "") -> str:
    error_html = f'<p class="error" role="alert">{escape(error)}</p>' if error else ""
    return _page(
        "Đăng nhập",
        f"""<h1>Đăng nhập</h1>
{error_html}
<form method="post" action="/login">
  <p><label for="username">Tên đăng nhập</label><br><input id="username" name="username" autocomplete="username"></p>
  <p><label for="password">Mật khẩu</label><br><input id="password" name="password" type="password" autocomplete="current-password"></p>
  <button id="btn-login" type="submit">Đăng nhập</button>
</form>""",
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
    return _page(
        "Báo cáo cuối ngày",
        f"""<h1>Báo cáo cuối ngày</h1>
<p><a id="ui-toggle" href="/ui/toggle">{switch_label}</a> · <a id="logout" href="/logout">Đăng xuất</a></p>
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
    if not (
        secrets.compare_digest(username, DEMO_USER) and secrets.compare_digest(password, DEMO_PASSWORD)
    ):
        return HTMLResponse(_login_page("Sai tên đăng nhập hoặc mật khẩu."), status_code=401)
    token = secrets.token_urlsafe(24)
    _sessions[token] = {"user": username, "ui": "v1"}
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
