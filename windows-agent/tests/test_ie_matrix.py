"""Task 11.2: the whole chain Ghi → Học → Chạy on a REAL Internet Explorer, on the TouchPoint look-alike (mock-site/touchpoint.py).

Each scenario signs in, opens the screen, records the teller's work two times with other data (with the noise tellers make: a date in
the wrong format and its message box, a press too many), learns it, then runs it with new data and checks what the services were
asked. Change Ghi or Học: run this in document modes 8 and 9 (scripts/run-ie-matrix.ps1). Its own hidden IE window, never another.

    $env:ROOKIE_REAL_IE = "1"; $env:RK_DOCMODE = "8"; pytest tests/test_ie_matrix.py
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load_touchpoint():
    """mock-site/touchpoint.py by its path: putting mock-site on sys.path would make its app.py hide the server's `app` package."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("rk_touchpoint", REPO / "mock-site" / "touchpoint.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


touchpoint = _load_touchpoint()

pytestmark = pytest.mark.skipif(sys.platform != "win32" or os.environ.get("ROOKIE_REAL_IE") != "1",
                                reason="Chạy trên IE thật: đặt ROOKIE_REAL_IE=1")
TITLE = "RookieE2E TouchPoint"


def base():
    import test_ie_real                       # sibling module (tests/ has no package: the server has one named `tests`)
    return test_ie_real


def drive(action, **env):
    for key, value in env.items():
        os.environ["RK_" + key.upper()] = str(value)
    return base().drive(action, TITLE)


def ask(frame, expression):
    """The value of a script expression in a frame of the test window ('' when it fails)."""
    return drive("fr-js", frame=frame, js=f"try {{ window.__res = String({expression}); }} catch (e) {{ window.__res = ''; }}")


def wait_for(frame, expression, seconds=15.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if ask(frame, expression) in ("true", "1"):
            return
        time.sleep(0.3)
    raise AssertionError(f"chờ quá lâu: {frame}: {expression}")


def serve(tp):
    class Handler(BaseHTTPRequestHandler):
        def _go(self, method):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) if method == "POST" else b""
            status, headers, data = tp.handle(method, self.path, dict(self.headers), body)
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            if any(n.lower() == "content-type" and "html" in v for n, v in headers):
                self.send_header("X-UA-Compatible", "IE=" + os.environ.get("RK_DOCMODE", "8"))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._go("GET")

        def do_POST(self):
            self._go("POST")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@contextlib.contextmanager
def touchpoint_ie():
    """The look-alike, signed in as a teller, on the account screen, in an own hidden IE window; everything closed after."""
    from rookie_agent.ie.bridge import IeBridge

    for _ in range(10):
        if base().drive("quit") == "no window":
            break
    tp = touchpoint.TouchPoint(title_prefix="RookieE2E ")
    server = serve(tp)
    port = server.server_address[1]
    opened = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                             "try { $ie = New-Object -ComObject InternetExplorer.Application } catch { exit 3 }; $ie.Visible = $false; "
                             f"$ie.Navigate2('http://127.0.0.1:{port}/tp/?dlg=inline'); $t = 0; while ($ie.Busy -and $t -lt 100) {{ Start-Sleep -Milliseconds 200; $t++ }}; Start-Sleep 1"],
                            timeout=60)
    if opened.returncode == 3:
        server.shutdown()
        pytest.skip("Máy này không có Internet Explorer dùng được qua COM")
    watchdog = threading.Timer(280, lambda: base().drive("quit"))
    watchdog.daemon = True
    watchdog.start()
    bridge = IeBridge().open()
    try:
        bridge.test_port = port
        drive("e-type", id="txtUser", value="gdv01")
        drive("e-type", id="txtPw", value="demo-only-1234")
        drive("e-click", id="btnLogin")
        wait_for("menu", "document.getElementById('mnuAcct') != null")
        drive("fr-click", frame="menu", id="mnuAcct")
        wait_for("work", "document.getElementById('txtAcct') != null")
        yield bridge, tp
    finally:
        watchdog.cancel()
        bridge.close()
        base()._quit_windows_of_this_site(port)
        base().drive("quit")
        server.shutdown()


def tab_of(bridge):
    for _ in range(50):
        tab = next((t for t in bridge.tabs() if TITLE in t["title"]), None)
        if tab:
            return tab
        time.sleep(0.2)
    raise AssertionError(bridge.tabs())


def core_with(tmp_path, bridge, server):
    from test_webui import make_core

    core, _ = make_core(tmp_path, ie_bridge=lambda: bridge, server_client=lambda url: base()._InProcessServer(server))
    core.store.put("download_folder", str(tmp_path / "Rookie"))
    return core


def server_app(tmp_path):
    sys.path.insert(0, str(REPO / "server"))
    from app.main import create_app

    app = create_app(tmp_path / "server.db")
    app.state.flow_builder = None          # the rule-based learner; the model is tested on its own
    return app


# ---- what a teller does on the account screen ---------------------------------------------------------------------------------

def find_account(number, enter=False):
    if enter:
        drive("fr-enter", frame="work", id="txtAcct", value=number)
    else:
        drive("fr-type", frame="work", id="txtAcct", value=number)
        drive("fr-click", frame="work", id="btnFind")
    wait_for("work", "document.getElementById('tblInfo') != null")


def history(start, end, mistake=False):
    if mistake:                                 # a date in the wrong format: the page's own message box, closed with ĐỒNG Ý
        drive("fr-type", frame="work", id="txtFrom", value=start.replace("/", "-"))
        drive("fr-type", frame="work", id="txtTo", value=end)
        drive("fr-click", frame="work", id="btnHistory")
        wait_for("work/dlg", "document.getElementById('btnOK') != null")
        drive("fr-click", frame="work/dlg", id="btnOK")
        time.sleep(0.5)
    drive("fr-type", frame="work", id="txtFrom", value=start)
    drive("fr-type", frame="work", id="txtTo", value=end)
    drive("fr-click", frame="work", id="btnHistory")
    wait_for("work", "document.getElementById('tblHistory') != null")


def print_first_row():
    drive("fr-click", frame="work", id="chkRow0")
    drive("fr-click", frame="work", id="btnPrint")
    wait_for("work/dlg", "document.getElementById('btnClose') != null")
    time.sleep(5.0)                             # the dialog posts its form into its frame; the answer is the PDF
    drive("fr-click", frame="work/dlg", id="btnClose")
    time.sleep(0.5)


def record(core, tab, name, work):
    assert core.dispatch("POST", "/api/record/start", {"window": f"ie-tab:{tab['id']}", "requests": True})[0] == 200
    time.sleep(1.0)
    work()
    time.sleep(1.0)
    status, saved = core.dispatch("POST", "/api/record/stop", {"name": name})
    assert status == 200, saved
    return saved["id"]


def run(core, tab, title, inputs, mode="simulate", seconds=60):
    status, reply = core.dispatch("POST", "/api/run/start", {"title": title, "mode": mode, "window": f"ie-tab:{tab['id']}", "inputs": inputs})
    assert status == 200, reply
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        state = core.dispatch("GET", "/api/run/status", {})[1]
        if state.get("result"):
            return state
        time.sleep(0.3)
    raise AssertionError(core.dispatch("GET", "/api/run/status", {})[1])


def inputs_for(flow, values):
    """The flow's inputs filled by what each one is (account, from, to), whatever the learner named them."""
    out = {}
    for item in flow["workflow"]["inputs"]:
        label = (item.get("label") or item["name"]).lower()
        key = "acct" if "tài khoản" in label or "tai_khoan" in item["name"] else "from" if "từ" in label or "tu_ngay" in item["name"] \
            else "to" if "đến" in label or "den_ngay" in item["name"] else None
        if key:
            out[item["name"]] = values[key]
    return out


def show(core, *ids, force=False):
    """RK_SHOW=1 (or a failure): what each recording holds, for reading it (values are the synthetic ones of the look-alike)."""
    if not os.environ.get("RK_SHOW") and not force:
        return
    for i in ids:
        doc = core.store.load(i)
        print("\nEVENTS", i, [(e["seq"], e["type"], (e.get("target") or {}).get("label"), e.get("value")) for e in doc["events"]])
        print("REQUESTS", [(r.get("after_seq"), r.get("kind"), r.get("method"), r.get("url")[-60:], r.get("status"), (r.get("body") or "")[:80], bool(r.get("file")))
                           for r in doc.get("requests") or []])


# ---- the scenarios --------------------------------------------------------------------------------------------------------------

def test_statement_slips_printed_in_a_dialog_recorded_twice_with_a_mistake_learned_and_run_by_request_for_another_account(tmp_path):
    from fastapi.testclient import TestClient

    with TestClient(server_app(tmp_path)) as server, touchpoint_ie() as (bridge, tp):
        core = core_with(tmp_path, bridge, server)
        tab = tab_of(bridge)
        first = record(core, tab, "in bao no co 1", lambda: (find_account("0123456789"), history("01/11/2026", "15/11/2026"), print_first_row()))
        second = record(core, tab, "in bao no co 2", lambda: (find_account("5566778899", enter=True), history("02/11/2026", "20/11/2026", mistake=True),
                                                              print_first_row()))
        show(core, first, second)
        status, shown = core.dispatch("POST", "/api/learn", {"ids": [first, second], "title": "In báo nợ có"})
        if status != 200:
            show(core, first, second, force=True)
        assert status == 200, shown
        flow = core.store.get("flows")[0]
        names = "\n".join(f"{n['label']} [{n['kind']}] {n['url']}" for n in flow["api"])
        if os.environ.get("RK_SHOW"):
            print("\nNODES\n" + names)
        assert not any("dlgMessageBox" in n["url"] for n in flow["api"]), names          # the message box is not learned
        assert any(n["kind"] == "file" for n in flow["api"]), names                      # the PDF of the dialog is
        steps = flow["workflow"]["steps"]                                                # task 12.1: what the screen showed, as postconditions
        assert flow["workflow"]["schema_version"] == 4 and any(s.get("expect") for s in steps), steps
        assert any({"kind": "table", "name": "tblInfo"}.items() <= a.items() for s in steps for a in (s.get("expect") or {}).get("appears", [])), steps
        values = {"acct": "9988776655", "from": "03/11/2026", "to": "18/11/2026"}
        inputs = inputs_for(flow, values)
        assert set(inputs.values()) == set(values.values()), (flow["workflow"]["inputs"], inputs)
        tp.seen.clear()
        state = run(core, tab, "In báo nợ có", inputs)
    assert state["result"]["status"] == "finished", state["result"]
    asked = list(tp.seen)
    assert "AcctService.find(9988776655)" in asked and "HistoryService.list(9988776655,03/11/2026,18/11/2026)" in asked, asked
    assert any(s.startswith("exportPdf(9988776655,1)") for s in asked), asked                # the row's id came from this run's history
    assert len(list((tmp_path / "Rookie").glob("*.pdf"))) == 1


def learn_and_run(tmp_path, title, recordings, values, check):
    """Record each `work` (a function of the teller's moves), learn them, run by request with `values`, then `check(asked, folder)`."""
    from fastapi.testclient import TestClient

    with TestClient(server_app(tmp_path)) as server, touchpoint_ie() as (bridge, tp):
        core = core_with(tmp_path, bridge, server)
        tab = tab_of(bridge)
        ids = [record(core, tab, f"{title} {n}", work) for n, work in enumerate(recordings, 1)]
        show(core, *ids)
        status, shown = core.dispatch("POST", "/api/learn", {"ids": ids, "title": title})
        assert status == 200, shown
        flow = core.store.get("flows")[0]
        tp.seen.clear()
        state = run(core, tab, title, inputs_for(flow, values))
        assert state["result"]["status"] == "finished", (state["result"], [(n["label"], n["kind"], n["url"]) for n in flow["api"]])
        check(list(tp.seen), tmp_path / "Rookie")
        _quit_new_windows = base()._quit_windows_of_this_site
        _quit_new_windows(bridge.test_port)


def statement(start, end):
    drive("fr-type", frame="work", id="txtFrom", value=start)
    drive("fr-type", frame="work", id="txtTo", value=end)
    drive("fr-click", frame="work", id="btnStatement")
    time.sleep(6.0)                              # window.open of a PDF: no document comes; the recorder waits a few seconds


def excel(start, end):
    drive("fr-type", frame="work", id="txtFrom", value=start)
    drive("fr-type", frame="work", id="txtTo", value=end)
    drive("fr-click", frame="work", id="btnExcel")
    time.sleep(6.0)                              # a form into a hidden frame, the answer an attachment: no document comes


def test_a_statement_opened_with_window_open_is_learned_and_run_for_another_account(tmp_path):
    learn_and_run(tmp_path, "Xuất sao kê",
                  [lambda: (find_account("0123456789"), statement("01/11/2026", "15/11/2026")),
                   lambda: (find_account("5566778899", enter=True), statement("02/11/2026", "20/11/2026"))],
                  {"acct": "9988776655", "from": "03/11/2026", "to": "18/11/2026"},
                  lambda asked, folder: (
                      _expect("statement(9988776655,03/11/2026,18/11/2026)" in asked, asked),
                      _expect(len(list(folder.glob("*.pdf"))) == 1, list(folder.glob("*")))))


def test_an_excel_file_from_a_form_into_a_hidden_frame_is_learned_and_run_for_another_account(tmp_path):
    learn_and_run(tmp_path, "Tải Excel sao kê",
                  [lambda: (find_account("0123456789"), excel("01/11/2026", "15/11/2026")),
                   lambda: (find_account("5566778899"), excel("02/11/2026", "20/11/2026"))],
                  {"acct": "9988776655", "from": "03/11/2026", "to": "18/11/2026"},
                  lambda asked, folder: (
                      _expect("excel(9988776655,03/11/2026,18/11/2026)" in asked, asked),
                      _expect(len(list(folder.glob("*.csv"))) == 1, list(folder.glob("*")))))


def _expect(ok, detail):
    assert ok, detail


def view_data(start, end):
    history(start, end)
    drive("fr-click", frame="work", id="chkRow0")
    drive("fr-click", frame="work", id="btnPrintData")
    wait_for("work/dlg", "document.getElementById('vName') != null && document.getElementById('vName').innerHTML != ''")
    time.sleep(3.0)
    drive("fr-click", frame="work/dlg", id="btnClose")
    time.sleep(0.5)


def _printed_page(folder):
    pages = list(folder.glob("*(bản in).html"))
    _expect(len(pages) == 1, list(folder.glob("*")))
    text = pages[0].read_text(encoding="utf-8")
    _expect("Số tài khoản" in text and "9988776655" in text and "Tên khách hàng" in text, text[:600])


def test_a_screen_the_page_fills_from_an_answer_is_learned_and_printed_again_with_its_labels(tmp_path):
    learn_and_run(tmp_path, "In báo nợ có từ dữ liệu",
                  [lambda: (find_account("0123456789"), view_data("01/11/2026", "15/11/2026")),
                   lambda: (find_account("5566778899"), view_data("02/11/2026", "20/11/2026"))],
                  {"acct": "9988776655", "from": "03/11/2026", "to": "18/11/2026"},
                  lambda asked, folder: _printed_page(folder))


def transfer(source, target, amount):
    drive("fr-click", frame="menu", id="mnuTransfer")
    wait_for("work", "document.getElementById('txtFromAcct') != null")
    drive("fr-type", frame="work", id="txtFromAcct", value=source)
    drive("fr-type", frame="work", id="txtToAcct", value=target)
    drive("fr-type", frame="work", id="txtAmount", value=amount)
    drive("fr-type", frame="work", id="txtContent", value="Chuyen tien thu")
    drive("fr-click", frame="work", id="btnSubmit")
    wait_for("work", "document.getElementById('result').innerHTML.indexOf('LX') >= 0")


def test_a_transfer_is_learned_as_money_never_sent_by_request_and_on_the_screen_waits_for_a_person(tmp_path):
    from fastapi.testclient import TestClient

    with TestClient(server_app(tmp_path)) as server, touchpoint_ie() as (bridge, tp):
        core = core_with(tmp_path, bridge, server)
        tab = tab_of(bridge)
        ids = [record(core, tab, "lap lenh 1", lambda: transfer("0123456789", "0987654321", "1500000")),
               record(core, tab, "lap lenh 2", lambda: transfer("5566778899", "1122334455", "2700000"))]
        show(core, *ids)
        status, shown = core.dispatch("POST", "/api/learn", {"ids": ids, "title": "Lập lệnh chuyển tiền"})
        assert status == 200, shown
        flow = core.store.get("flows")[0]
        last = flow["workflow"]["steps"][-1]
        assert (last["risk"], last["mode"]) == ("money", "approve"), flow["workflow"]["steps"]
        by_label = {"Tài khoản chuyển": "9988776655", "Tài khoản nhận": "1231231231", "Số tiền": "500000", "Nội dung": "Chuyen tien thu"}
        inputs = {i["name"]: by_label[i["label"]] for i in flow["workflow"]["inputs"] if i.get("label") in by_label}
        made = [s for s in tp.seen if s.startswith("TransferService.create")]
        tp.seen.clear()
        # by request: money is never sent that way (an unclassified step asks «chỉ xem?» first: the person says no)
        status, reply = core.dispatch("POST", "/api/run/start", {"title": "Lập lệnh chuyển tiền", "mode": "simulate", "window": f"ie-tab:{tab['id']}", "inputs": inputs})
        assert status == 200, reply
        end = time.monotonic() + 60
        while time.monotonic() < end:
            refused = core.dispatch("GET", "/api/run/status", {})[1]
            if refused.get("ask"):
                core.dispatch("POST", "/api/run/decide", {"ask_id": refused["ask"]["id"], "approve": False})
            if refused.get("result"):
                break
            time.sleep(0.3)
        assert refused["result"]["status"] in ("refused", "needs_help", "stopped"), refused["result"]
        assert not [s for s in tp.seen if s.startswith("TransferService")], tp.seen
        assert core.dispatch("POST", "/api/flow/approve", {"title": "Lập lệnh chuyển tiền"})[0] == 200
        drive("fr-click", frame="menu", id="mnuTransfer")
        wait_for("work", "document.getElementById('txtFromAcct') != null")
        status, reply = core.dispatch("POST", "/api/run/start", {"title": "Lập lệnh chuyển tiền", "window": f"ie-tab:{tab['id']}", "inputs": inputs})
        assert status == 200, reply
        asked, risks = [], []
        end = time.monotonic() + 60
        while time.monotonic() < end:
            state = core.dispatch("GET", "/api/run/status", {})[1]
            if state.get("ask") and state["ask"]["id"] not in asked:
                asked.append(state["ask"]["id"])
                risks.append(state["ask"].get("risk"))
                # the menu step (unclassified, so write) is let through on the mock; at the money step the person says no
                core.dispatch("POST", "/api/run/decide", {"ask_id": state["ask"]["id"], "approve": state["ask"].get("risk") != "money"})
            if state.get("result"):
                break
            time.sleep(0.3)
    assert len(made) == 2                                                                  # the two recordings really sent their orders
    assert risks[-1] == "money", risks                                                     # the run stopped at the money step for a person
    assert state["result"]["status"] in ("rejected", "stopped"), state["result"]
    assert not [s for s in tp.seen if s.startswith("TransferService")], tp.seen           # no order without the person's yes


# ---- Gate 12 (SADPT): the application changes, Rookie keeps working within what it may do ----------------------------------------

def lookup(acct, start, end):
    find_account(acct)
    history(start, end)


def run_to_end(core, tab, title, inputs, answer=None, seconds=90):
    """A run on the screen; `answer(ask)` decides each question (none expected when it is None: the test fails on the first one)."""
    status, reply = core.dispatch("POST", "/api/run/start", {"title": title, "window": f"ie-tab:{tab['id']}", "inputs": inputs})
    assert status == 200, reply
    asked = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        state = core.dispatch("GET", "/api/run/status", {})[1]
        if state.get("result"):
            return state, asked
        if state.get("ask"):
            asked.append(state["ask"])
            assert answer is not None, state["ask"]
            reply = answer(state["ask"])
            if reply is None:
                core.dispatch("POST", "/api/run/stop", {})
            else:
                core.dispatch("POST", "/api/run/decide", {"ask_id": state["ask"]["id"], **reply})
        time.sleep(0.3)
    raise AssertionError(core.dispatch("GET", "/api/run/status", {})[1])


def open_screen(menu, element):
    drive("fr-click", frame="menu", id=menu)
    wait_for("work", f"document.getElementById('{element}') != null")


def test_sadpt_a_new_look_of_the_screen_is_found_again_without_recording_again_checked_and_kept_as_a_draft(tmp_path):
    from fastapi.testclient import TestClient

    title = "Tra cứu lịch sử"
    with TestClient(server_app(tmp_path)) as server, touchpoint_ie() as (bridge, tp):
        core = core_with(tmp_path, bridge, server)
        tab = tab_of(bridge)
        open_screen("mnuAcct", "txtAcct")
        ids = [record(core, tab, "tra cuu 1", lambda: lookup("0123456789", "01/11/2026", "15/11/2026")),
               record(core, tab, "tra cuu 2", lambda: lookup("5566778899", "02/11/2026", "20/11/2026"))]
        assert core.dispatch("POST", "/api/learn", {"ids": ids, "title": title})[0] == 200
        flow = core.store.get("flows")[0]
        assert flow["workflow"]["schema_version"] == 4, flow["workflow"]
        assert core.dispatch("POST", "/api/flow/approve", {"title": title})[0] == 200
        inputs = inputs_for(flow, {"acct": "9988776655", "from": "03/11/2026", "to": "18/11/2026"})
        open_screen("mnuAcct", "txtAcct")
        first, _ = run_to_end(core, tab, title, inputs)                       # version 1 on the old look: as learned
        assert first["result"]["status"] == "finished", first["result"]
        tp.ui = 2                                                              # the bank changes the screen: new ids, the button moved
        open_screen("mnuAcct", "txtAccountNo")
        tp.seen.clear()
        state, asked = run_to_end(core, tab, title, inputs)                   # no question: the agent finds the button again itself
        result = state["result"]
        assert result["status"] == "finished", result
        assert "AcctService.find(9988776655)" in tp.seen and "HistoryService.list(9988776655,03/11/2026,18/11/2026)" in tp.seen, tp.seen
        again = [d for d in result.get("decisions") or [] if d["action"] == "reresolve"]
        assert again and all(d["outcome"] == "done" and d["change"] == "technical" for d in again), result.get("decisions")
        kept = core.store.get("flows")[0]
        assert kept["workflow"]["status"] == "approved" and kept["repair"]["workflow"]["status"] == "draft"    # nothing published by itself
        assert any("btnSearchAccount" in sel for s in kept["repair"]["workflow"]["steps"] for sel in (s.get("target") or {}).get("selectors", []))
        audit = (core.store.home / "audit.jsonl").read_text(encoding="utf-8")
        assert '"by": "agent"' in audit and '"reresolve"' in audit and "9988776655" not in audit
        _quit_new_windows = base()._quit_windows_of_this_site
        _quit_new_windows(bridge.test_port)


def test_sadpt_a_new_look_of_a_money_screen_is_never_found_again_by_the_agent_it_asks(tmp_path):
    from fastapi.testclient import TestClient

    title = "Lập lệnh chuyển tiền"
    with TestClient(server_app(tmp_path)) as server, touchpoint_ie() as (bridge, tp):
        core = core_with(tmp_path, bridge, server)
        tab = tab_of(bridge)
        ids = [record(core, tab, "lap lenh 1", lambda: transfer("0123456789", "0987654321", "1500000")),
               record(core, tab, "lap lenh 2", lambda: transfer("5566778899", "1122334455", "2700000"))]
        assert core.dispatch("POST", "/api/learn", {"ids": ids, "title": title})[0] == 200
        flow = core.store.get("flows")[0]
        assert flow["workflow"]["steps"][-1]["adapt"] == {"reresolve": False}, flow["workflow"]["steps"][-1]
        assert core.dispatch("POST", "/api/flow/approve", {"title": title})[0] == 200
        by_label = {"Tài khoản chuyển": "9988776655", "Tài khoản nhận": "1231231231", "Số tiền": "500000", "Nội dung": "Chuyen tien thu"}
        inputs = {i["name"]: by_label[i["label"]] for i in flow["workflow"]["inputs"] if i.get("label") in by_label}
        tp.ui = 2
        open_screen("mnuTransfer", "btnSendForApproval")
        tp.seen.clear()
        kinds = []

        def answer(ask):
            kinds.append(ask.get("kind") or ask.get("type"))
            return {"approve": True} if not ask.get("candidates") else None    # the approval yes; the pick: the person stops here
        state, asked = run_to_end(core, tab, title, inputs, answer=answer)
        assert any(a.get("candidates") for a in asked), asked                  # the money button was put to the person, never taken
        assert not [s for s in tp.seen if s.startswith("TransferService")], tp.seen
        assert not any(d.get("action") == "reresolve" for d in state["result"].get("decisions") or []), state["result"]


def test_sadpt_a_business_change_stops_at_the_new_box_the_teller_teaches_only_that_part_and_version_2_runs_after_duyet(tmp_path):
    from fastapi.testclient import TestClient

    title = "Tra cứu lịch sử"
    with TestClient(server_app(tmp_path)) as server, touchpoint_ie() as (bridge, tp):
        core = core_with(tmp_path, bridge, server)
        tab = tab_of(bridge)
        open_screen("mnuAcct", "txtAcct")
        ids = [record(core, tab, "tra cuu 1", lambda: lookup("0123456789", "01/11/2026", "15/11/2026")),
               record(core, tab, "tra cuu 2", lambda: lookup("5566778899", "02/11/2026", "20/11/2026"))]
        assert core.dispatch("POST", "/api/learn", {"ids": ids, "title": title})[0] == 200
        assert core.dispatch("POST", "/api/flow/approve", {"title": title})[0] == 200
        flow = core.store.get("flows")[0]
        inputs = inputs_for(flow, {"acct": "9988776655", "from": "03/11/2026", "to": "18/11/2026"})
        tp.biz = 2                                                             # a new rule: a confirmation box after the search
        open_screen("mnuAcct", "txtAcct")
        tp.seen.clear()
        state, _ = run_to_end(core, tab, title, inputs)
        stopped = state["result"]
        assert stopped["status"] == "needs_help" and "chưa từng thấy" in stopped["message"] and stopped.get("teach_after"), stopped
        assert not [s for s in tp.seen if s.startswith("HistoryService")], tp.seen       # it stopped at the safe point, before going on
        assert any(d["change"] == "business" for d in stopped["decisions"]), stopped["decisions"]
        # the box is on the screen: the teller teaches only that part
        status, reply = core.dispatch("POST", "/api/teach/start", {"title": title, "after_step": stopped["teach_after"], "window": f"ie-tab:{tab['id']}"})
        assert status == 200, reply
        time.sleep(1.0)
        drive("fr-click", frame="work/dlg", id="btnOK")
        time.sleep(1.0)
        status, made = core.dispatch("POST", "/api/teach/stop", {})
        assert status == 200 and made["version"] == 2 and made["added"], made
        kept = core.store.get("flows")[0]
        assert kept["workflow"]["version"] == 1 and kept["repair"]["kind"] == "teach"             # version 1 stays in use until Duyệt
        assert core.dispatch("POST", "/api/flow/approve", {"title": title})[0] == 200
        kept = core.store.get("flows")[0]
        assert kept["workflow"]["version"] == 2 and kept["previous"][-1]["version"] == 1           # version 1 kept to go back to
        open_screen("mnuAcct", "txtAcct")
        tp.seen.clear()
        state, asked = run_to_end(core, tab, title, inputs, answer=lambda ask: {"approve": True})   # the new press waits for Duyệt
        assert state["result"]["status"] == "finished", state["result"]
        assert "HistoryService.list(9988776655,03/11/2026,18/11/2026)" in tp.seen, tp.seen
        assert asked and all(a.get("kind") == "approve" for a in asked), asked
        _quit_new_windows = base()._quit_windows_of_this_site
        _quit_new_windows(bridge.test_port)
