"""Build recorded sessions the way the Windows agent and the extension produce them."""

from __future__ import annotations

from typing import Any


def _event(engine: str, session_id: str, seq: int, kind: str, url: str, selectors, label, tag, value, value_class, api_calls):
    return {
        "schema_version": 1,
        "engine": engine,
        "session_id": session_id,
        "seq": seq,
        "ts": "2026-11-12T09:15:03.000Z",
        "type": kind,
        "url": url,
        "target": None if selectors is None else {"selectors": selectors, "label": label, "tag": tag},
        "value": value,
        "value_class": value_class,
        "api_calls": api_calls,
    }


def java_transfer_session(session_id: str, cif_class: bool = True, extra_click: bool = False) -> list[dict[str, Any]]:
    """Look up a CIF, then create a transfer order and send it for approval (Java)."""
    screen_cif, screen_transfer = "Mock TPSS - Khách hàng (CIF)", "Mock TPSS - Chuyển tiền"
    rows: list[tuple] = [
        ("input", screen_cif, ["role=text[name='Số CIF hoặc CCCD']", "path=frame/a[1]"], "Số CIF hoặc CCCD", "text", None, "cif_number"),
        ("click", screen_cif, ["role=push button[name='Tra cứu CIF']", "path=frame/a[2]"], "Tra cứu CIF", "push button", None, None),
        ("click", screen_cif, ["role=page tab[name='Chuyển tiền']", "path=frame/a[3]"], "Chuyển tiền", "page tab", None, None),
        ("input", screen_transfer, ["role=text[name='Tài khoản chuyển']", "path=frame/b[1]"], "Tài khoản chuyển", "text", None, "account_number"),
        ("input", screen_transfer, ["role=text[name='Tài khoản nhận']", "path=frame/b[2]"], "Tài khoản nhận", "text", None, "account_number"),
        ("input", screen_transfer, ["role=text[name='Số tiền']", "path=frame/b[3]"], "Số tiền", "text", None, "amount"),
        ("select", screen_transfer, ["role=combo box[name='Loại tiền']", "path=frame/b[4]"], "Loại tiền", "combo box", "VND", None),
        ("click", screen_transfer, ["role=push button[name='Gửi duyệt']", "path=frame/b[5]"], "Gửi duyệt", "push button", None, None),
    ]
    if extra_click:
        rows.insert(2, ("click", screen_cif, ["role=push button[name='Tải lại']", "path=frame/a[9]"], "Tải lại", "push button", None, None))
    events = []
    for seq, (kind, url, selectors, label, tag, value, value_class) in enumerate(rows):
        events.append(_event("java", session_id, seq, kind, url, selectors, label, tag, value, value_class, []))
    return events


def web_report_session(session_id: str, day: str) -> list[dict[str, Any]]:
    """Open report A for a day and search it (web)."""
    url = "/baocao/cuoingay"
    read = [{"method": "GET", "path": "/api/report", "status": 200}]
    rows = [
        ("click", ["#tab-a", "role=tab[name='Báo cáo A']"], "Báo cáo A", "button", None, []),
        ("input", ["#f-date", "label=Ngày báo cáo"], "Ngày báo cáo", "input", day, []),
        ("click", ["#btn-search", "role=button[name='Tìm kiếm']"], "Tìm kiếm", "button", None, read),
    ]
    return [
        _event("web", session_id, seq, kind, url, selectors, label, tag, value, None, calls)
        for seq, (kind, selectors, label, tag, value, calls) in enumerate(rows)
    ]


def payload(session_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": 1, "engine": events[0]["engine"], "session_id": session_id, "events": events}
