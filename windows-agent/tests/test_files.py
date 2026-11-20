"""A call whose answer is a file (a report exported as PDF): recorded as its facts only, learned as a node of kind "file", run by request with
the bytes saved exactly on this PC, in the Rookie folder only (docs/design.md 6.4). Real IE part: test_ie_real.py."""

import json
import threading
from datetime import datetime
from pathlib import Path

import pytest

from rookie_agent.ie import files, replay, twin
from rookie_agent.ie.bridge import IeBridge
from rookie_agent.ie.session import IeSession
from test_replay import Shown, flow, recorded
from test_webui import FakeIeBridge, make_core

PDF_BYTES = b"%PDF-1.4\n" + bytes(range(256)) * 4 + b"\r\n\x00\xff%%EOF"   # every byte value, CR LF and a NUL: nothing may change them
SECRET_TEXT = "SO TAI KHOAN 0123456789 NGUYEN VAN A"


def export_requests():
    """The recording of `recorded()` with one more call after the last click: the export, whose answer is a PDF (the recorder gave its facts)."""
    raw, events, requests = recorded()
    requests = requests[:2]                      # the screen opening and the search; the form and the sign-in of `recorded()` are left out
    requests.append({"kind": "xhr", "frame": "main", "method": "POST", "url": "/rpt/export", "status": 200, "req": "from=2026-01-01&to=2026-01-31",
                     "res": SECRET_TEXT, "hdr": "Content-Type:application/x-www-form-urlencoded\n",
                     "file": {"ctype": "application/pdf", "size": 1234, "name": "A_#.pdf"}, "after": {"t": 1_700_000_003_000}})
    return raw, events, requests


def file_nodes():
    raw, events, requests = export_requests()
    return replay.build_api(flow(), events, replay.templates(raw, events, requests))


def export_group(nodes=None):
    nodes = nodes or file_nodes()
    return [n for n in nodes if n["kind"] == "file"]


# ---- recording and learning ----------------------------------------------------------------------------------------------

def test_a_file_answer_is_kept_as_its_facts_only_no_bytes_no_text_no_shape_no_link():
    raw, events, requests = export_requests()
    found = replay.templates(raw, events, requests)
    last = found[-1]
    assert last["answer"] == "file" and last["file"] == {"ctype": "application/pdf", "size": 1234, "name": "A_#.pdf", "guess": False}
    assert last["shape"] == {"v": 1, "kind": "file", "body": None}
    assert SECRET_TEXT not in json.dumps(found) and "0123456789" not in json.dumps(found)


def test_text_of_a_file_answer_is_never_searched_for_values_to_link():
    raw, events, requests = export_requests()
    requests.append({"kind": "xhr", "frame": "main", "method": "POST", "url": "/rpt/next", "status": 200, "req": "acct=ACCT777666555", "res": "", "after": None})
    requests[2]["res"] = "ACCT777666555"          # the file answer carried this text: it must not be a source of links
    found = replay.templates(raw, events, requests)
    assert found[-1]["links"] == {} and "ACCT777666555" in found[-1]["body"]


def test_build_api_marks_the_node_as_a_file_and_keeps_how_it_was_sent():
    node = export_group()[0]
    assert node["kind"] == "file" and node["via"] == "xhr" and node["file"]["ctype"] == "application/pdf"
    assert node["method"] == "POST" and node["body"] == "from=2026-01-01&to=2026-01-31"
    assert twin.has_twin(file_nodes())                       # a file node has a twin: the placeholder


def test_a_recording_session_keeps_a_file_answer_as_facts_and_a_download_that_no_page_answered_as_a_guess():
    class Bridge:
        def start_recording(self, *a, **k):
            return {}

        def poll(self):
            return []

        def stop_recording(self):
            return []

    session = IeSession(Bridge(), 1, "App")
    click = {"kind": "click", "t": 1000, "uid": "c1", "frame": "top", "tag": "button", "type": "button", "id": "go", "label": "Xuat", "pos": 0, "ctl": True}
    ajax = {"kind": "ajax", "uid": "a1", "t": 1100, "frame": "top", "method": "GET", "url": "/r.pdf", "status": 200, "ms": 5, "req": "", "res": "LEAK",
            "hdr": "", "file": {"ctype": "application/pdf", "size": 10, "name": "A.pdf"}}
    form = {"kind": "form", "uid": "f1", "t": 1200, "frame": "top", "method": "POST", "url": "/export", "target": "", "req": "d=1"}
    go = {"kind": "formgo", "uid": "g1", "t": 1250, "frame": "top"}
    stopped_form = {"kind": "form", "uid": "f2", "t": 1300, "frame": "top", "method": "POST", "url": "/never", "req": "x=1"}   # the page's script stopped it: no formgo
    opened = {"kind": "open", "uid": "o1", "t": 1400, "frame": "top", "method": "GET", "url": "/pdf?id=1", "target": ""}
    page_opened = {"kind": "open", "uid": "o2", "t": 1410, "frame": "top", "method": "GET", "url": "/page.html", "target": "w2"}
    nav = {"kind": "nav", "uid": "n1", "t": 1420, "frame": "top", "url": "http://x/page.html", "title": "t"}
    session._take([click, ajax, form, go])
    session._flush_quiet(force=True)
    session._take([stopped_form])
    session._flush_quiet(force=True)
    assert "/never" not in [r["url"] for r in session.requests]                         # a form that did not go is not a request (a page's script stopped it)
    session._form = None
    session._take([opened, page_opened, nav])
    session._flush_quiet(force=True)
    by_url = {r["url"]: r for r in session.requests}
    assert by_url["/r.pdf"]["file"]["ctype"] == "application/pdf" and by_url["/r.pdf"]["res"] == ""        # the text that came along is dropped
    assert by_url["/export"]["file"]["guess"] is True and by_url["/export"]["req"] == "d=1" and by_url["/export"]["kind"] == "form"
    assert by_url["/pdf?id=1"]["kind"] == "open" and by_url["/pdf?id=1"]["method"] == "GET" and by_url["/pdf?id=1"]["file"]["guess"]
    assert "/page.html" not in by_url or by_url["/page.html"]["kind"] == "page"        # a window that showed a page is its page request, not a file


# ---- the run: exact bytes in the Rookie folder -----------------------------------------------------------------------

def saver(folder, title="Xuất báo cáo giao dịch", when=None):
    made = []

    def save(data, ctype, disposition):
        path = files.save(folder, files.file_name(title, ctype, disposition, when or datetime(2026, 11, 19, 10, 15, 30), data=data), data)
        made.append(path)
        return {"name": path.name, "path": str(path)}

    return save, made


def file_send(data=PDF_BYTES, ctype="application/pdf", disposition='attachment; filename="BaoCao_20261119.pdf"'):
    def send(node, url, headers, body):
        if node["kind"] == "file":
            return {"ok": True, "status": 200, "ms": 7, "text": "", "file": {"data": data, "ctype": ctype, "disposition": disposition}}
        return {"ok": True, "status": 200, "ms": 1, "text": "{}"}
    return send


def run_export(tmp_path, send, nodes=None, **kw):
    save, made = saver(tmp_path / "Rookie")
    nodes = nodes or [n for n in file_nodes() if n["kind"] == "file"]
    shown = Shown()
    result = replay.run_api(flow(), nodes, {"cif": "1"}, send, shown, threading.Event(), save_file=save, **kw)
    return result, shown, made


def _zip_with(*names):
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "x")
    return buffer.getvalue()


@pytest.mark.parametrize("data, kind", [
    (PDF_BYTES, "pdf"), (b"\x89PNG\r\n\x1a\n\x00\x00", "png"), (b"\xff\xd8\xff\xe0abc", "jpg"), (b"GIF89a....", "gif"), (b"{\\rtf1\\ansi x}", "rtf"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 20, "ole"),
    (_zip_with("[Content_Types].xml", "xl/workbook.xml"), "xlsx"), (_zip_with("word/document.xml"), "docx"), (_zip_with("a.txt"), "zip"),
    (b"<!DOCTYPE html><html><body>Het phien</body></html>", "html"), (b"  <HTML><head>", "html"),
    (b'<?xml version="1.0"?><IFX><Status>0</Status></IFX>', "xml"), (b'{"status": "ok"}', "json"), ("Ma GD,Ngay\n1,2\n".encode("utf-8"), "text"),
    ("Báo cáo giao dịch".encode("utf-8"), "text"), (b"\x00\x01\x02\x03\x04\x05" * 50, ""), (b"", ""),
])
def test_a_file_is_known_by_its_first_bytes_whatever_the_server_called_it(data, kind):
    assert files.sniff(data) == kind


def test_the_extension_follows_what_the_bytes_are_and_never_makes_text_a_pdf():
    octet = "application/octet-stream"
    assert files.extension(octet, "", PDF_BYTES) == "pdf"                                  # the server gave no name and a general type
    assert files.extension("application/pdf", 'attachment; filename="x.bin"', PDF_BYTES) == "pdf"
    assert files.extension(octet, "", _zip_with("xl/a.xml")) == "xlsx"
    assert files.extension(octet, "", b'<?xml version="1.0"?><a/>') == "xml"                 # data as XML is kept as it came
    assert files.extension(octet, "", b'{"status": "ok"}') == "txt"
    assert files.extension("application/pdf", 'attachment; filename="x.pdf"', b'{"error": "no"}') == "txt"     # text called a PDF would not open
    assert files.extension("text/csv", "", b"a,b\n1,2\n") == "csv"
    assert files.extension("application/vnd.ms-excel", "", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 9) == "xls"   # an old Office file: the type decides
    assert files.extension(octet, "", b"\x00\x01\x02\x03" * 20) == "bin"                    # nothing known: still bin
    assert files.extension(octet, "") == "bin" and files.extension("application/pdf", "") == "pdf"      # no bytes: as before


def test_a_pdf_a_server_called_octet_stream_is_saved_as_a_pdf_and_says_so(tmp_path):
    result, shown, made = run_export(tmp_path, file_send(ctype="application/octet-stream", disposition=""))
    assert result["status"] == "finished" and made[0].suffix == ".pdf"
    sent = shown.details["g3"]["requests"][0]["file"]
    assert (sent["kind"], sent["kind_text"], sent["warn"]) == ("pdf", "PDF", "")


def test_a_file_that_is_only_text_is_saved_as_text_and_the_teller_is_told_it_is_not_a_report(tmp_path):
    result, shown, made = run_export(tmp_path, file_send(data=b'{"status": "NOT-A-REPORT"}', ctype="application/octet-stream", disposition=""))
    assert result["status"] == "finished" and made[0].suffix == ".txt"
    sent = shown.details["g3"]["requests"][0]["file"]
    assert sent["kind"] == "json" and "không phải PDF" in sent["warn"] and "NOT-A-REPORT" not in json.dumps(sent)       # said in words, never the content


IFX = ('<?xml version="1.0" encoding="UTF-8"?><IFX xmlns="http://ifx.example/x"><Status><StatusCode>0</StatusCode><Severity>Success</Severity></Status>'
       '<DepAcctTrnRs><Customer><Title>Customer Title 1</Title><Account>116000002248</Account></Customer>'
       '<Trn><Amt>10944</Amt><Cur>EUR</Cur></Trn><Trn><Amt>2714</Amt><Cur>EUR</Cur></Trn>'
       '<Memo>Một nghìn euro &lt;script&gt;alert(1)&lt;/script&gt;</Memo></DepAcctTrnRs></IFX>').encode("utf-8")


def test_xml_rows_read_the_tree_number_repeated_names_and_refuse_what_is_unsafe():
    rows = files.xml_rows(IFX)
    names = [(depth, name, leaf) for depth, name, _, leaf in rows]
    assert (0, "IFX", False) in names and (1, "Status", False) in names and (3, "Account", True) in names
    assert (2, "Trn (1)", False) in names and (2, "Trn (2)", False) in names and (3, "Amt", True) in names       # a name repeated among siblings is numbered
    pairs = files.xml_pairs(rows)
    assert ["Account", "116000002248"] in pairs and ["Cur", "EUR"] in pairs and not any(v == "" for _, v in pairs)
    for bad in (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>', b"<a><b></a>", b"", b"<a>" + b"x" * (files.XML_MAX + 1) + b"</a>"):
        assert files.xml_rows(bad) is None


def test_the_report_of_an_xml_is_a_page_of_ours_with_every_text_escaped_and_no_script():
    page = files.xml_report_html("Sao kê <b>", files.xml_rows(IFX), datetime(2026, 11, 20, 14, 5))
    assert page.startswith(files.REPORT_MARK) and "20/11/2026 14:05" in page
    assert "<script" not in page.lower() and "&lt;script&gt;" in page and "Sao kê &lt;b&gt;" in page      # the value that was a script is only text
    assert "Customer Title 1" in page and "116000002248" in page and "http://" not in page and "src=" not in page and "href=" not in page


def test_xml_data_is_saved_as_xml_with_a_readable_report_beside_it_and_its_values_are_in_the_result(tmp_path, monkeypatch):
    core = export_core(tmp_path, monkeypatch, {"ok": True, "status": 200, "ms": 5, "text": "", "file": {"data": IFX, "ctype": "application/octet-stream", "disposition": ""}})
    run = run_to_end(core)
    assert run["result"]["status"] == "finished", run
    folder = tmp_path / "profile" / "Downloads" / "Rookie"
    raw = list(folder.glob("*.xml"))
    pages = list(folder.glob("*(bản đọc).html"))
    assert len(raw) == 1 and raw[0].read_bytes() == IFX and len(pages) == 1 and not list(folder.glob("*.bin"))
    assert files.is_report(pages[0]) and raw[0].stem in pages[0].name
    request = next(r for d in run["details"].values() for r in d["requests"] if r.get("file"))
    assert request["file"]["kind"] == "xml" and request["file"]["warn"] == "" and request["file"]["report"]["path"] == str(pages[0])
    assert ["Account", "116000002248"] in request["view"]["pairs"]                       # the values are in the result, as any data answer
    audit = (core.store.home / "audit.jsonl").read_text(encoding="utf-8")
    assert "116000002248" not in audit and "Customer Title" not in audit                  # never in the log
    # the page opens and prints the report; a page of anyone else's, or the raw XML, is not opened from here
    opened = []
    core._open_path = lambda path: opened.append(Path(path))
    core._print_path = lambda path: opened.append(("print", Path(path))) or True
    assert core.dispatch("POST", "/api/file/open", {"path": str(pages[0])})[0] == 200
    assert core.dispatch("POST", "/api/file/open", {"path": str(pages[0]), "print": True})[1]["printed"] is True
    assert opened == [pages[0], ("print", pages[0])]
    stranger = folder / "stranger.html"
    stranger.write_text("<html><script>alert(1)</script></html>", encoding="utf-8")
    assert core.dispatch("POST", "/api/file/open", {"path": str(stranger)})[0] == 400
    assert core.dispatch("POST", "/api/file/open", {"path": str(raw[0])})[0] == 400


def test_xml_answered_with_the_headers_of_a_page_is_still_taken_as_the_data_of_a_file_node(tmp_path):
    def send(node, url, headers, body):
        if node["kind"] == "file":
            return {"ok": True, "status": 200, "ms": 7, "text": IFX.decode("utf-8")}            # text/xml: no sign of a file in its headers
        return {"ok": True, "status": 200, "ms": 1, "text": "{}"}

    result, shown, made = run_export(tmp_path, send)
    assert result["status"] == "finished" and made[0].suffix == ".xml" and made[0].read_bytes() == IFX
    assert shown.details["g3"]["requests"][0]["file"]["kind"] == "xml"
    html_answer = lambda node, url, headers, body: {"ok": True, "status": 200, "ms": 7, "text": "<html><body>Het phien</body></html>"}   # noqa: E731
    assert run_export(tmp_path / "b", html_answer)[0]["status"] == "needs_help"                  # a page is still no file


def test_a_page_a_server_called_a_file_is_not_saved_and_the_run_stops(tmp_path):
    result, shown, made = run_export(tmp_path, file_send(data=b"<html><body>Phien lam viec het han</body></html>", ctype="application/octet-stream", disposition=""))
    assert result["status"] == "needs_help" and made == [] and "trang web" in result["message"]
    assert "het han" not in json.dumps(shown.details, ensure_ascii=False)


def test_a_run_saves_the_exact_bytes_and_names_the_file_after_the_flow_and_the_time(tmp_path):
    result, shown, made = run_export(tmp_path, file_send())
    assert result["status"] == "finished", result
    assert len(made) == 1 and made[0].read_bytes() == PDF_BYTES                              # bytes 0..255, CR LF, NUL: all as they came
    assert made[0].name == "Xuất báo cáo giao dịch-20261119-101530.pdf" and made[0].parent == tmp_path / "Rookie"
    sent = shown.details["g3"]["requests"][0]
    assert sent["file"]["saved"] is True and sent["file"]["name"] == made[0].name and sent["file"]["size"] == len(PDF_BYTES)
    assert "view" not in sent and "body" in sent and sent["file"]["size_text"].endswith("KB")
    assert "view" not in json.dumps(shown.details)


def test_the_file_name_follows_the_pattern_and_its_extension_comes_from_the_headers():
    moment = datetime(2026, 1, 2, 3, 4, 5)
    assert files.file_name("Xuất báo cáo", "application/pdf", "", moment) == "Xuất báo cáo-20260102-030405.pdf"
    assert files.file_name("a", "application/octet-stream", 'attachment; filename="x.XLSX"', moment) == "a-20260102-030405.xlsx"
    assert files.file_name("a", "application/octet-stream", "attachment; filename*=UTF-8''B%C3%A1o%20c%C3%A1o.pdf", moment).endswith(".pdf")
    assert files.file_name("a", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "", moment).endswith(".xlsx")
    assert files.file_name("a", "text/csv", "", moment).endswith(".csv")
    assert files.file_name("a/b:c*", "application/pdf", "", moment) == "a b c-20260102-030405.pdf"        # no character a Windows name cannot hold
    assert files.file_name("a", "application/pdf", 'attachment; filename="run.exe"', moment).endswith(".pdf")  # a program's extension is never taken
    assert files.file_name("a", "application/x-unknown", 'attachment; filename="run.exe"', moment).endswith(".bin")


def test_which_answers_are_files():
    assert files.is_file_answer("application/pdf") and files.is_file_answer("application/octet-stream; charset=x")
    assert files.is_file_answer("text/html", 'attachment; filename="a.html"') and files.is_file_answer("text/plain", "attachment")
    assert files.is_file_answer("application/vnd.ms-excel") and files.is_file_answer("image/png")
    assert not files.is_file_answer("text/html") and not files.is_file_answer("application/json") and not files.is_file_answer("text/x-gwt-rpc")
    assert not files.is_file_answer("application/vnd.api+json") and not files.is_file_answer("") and not files.is_file_answer("text/plain")


def test_the_same_second_never_overwrites_a_file(tmp_path):
    save, made = saver(tmp_path / "Rookie")
    first, second = save(b"one", "application/pdf", ""), save(b"two", "application/pdf", "")
    assert first["path"] != second["path"] and made[0].read_bytes() == b"one" and made[1].read_bytes() == b"two"


def test_a_page_instead_of_a_file_stops_the_run_and_saves_nothing(tmp_path):
    def send(node, url, headers, body):
        return {"ok": True, "status": 200, "ms": 3, "text": "<html><body>Phiên làm việc đã hết</body></html>"}

    result, shown, made = run_export(tmp_path, send)
    assert result["status"] == "needs_help" and made == [] and not (tmp_path / "Rookie").exists()
    assert "đăng nhập" in result["message"]                      # the usual refusal: the session ended


def test_an_error_page_with_status_200_is_not_taken_for_the_file(tmp_path):
    send = lambda node, url, headers, body: {"ok": True, "status": 200, "ms": 3, "text": "<html>Khong co du lieu</html>"}   # noqa: E731
    result, _, made = run_export(tmp_path, send)
    assert result["status"] == "needs_help" and "không phải file" in result["message"] and made == []


def test_a_file_over_50_mb_stops_the_run_and_says_so(tmp_path):
    big = lambda node, url, headers, body: {"ok": False, "status": 0, "error": "too_big"}   # noqa: E731  the bridge refused to fetch it
    result, _, made = run_export(tmp_path, big)
    assert result["status"] == "failed" and "50 MB" in result["message"] and made == []
    over = lambda node, url, headers, body: {"ok": True, "status": 200, "ms": 1, "file": {"data": b"0" * (files.MAX_BYTES + 1), "ctype": "application/pdf", "disposition": ""}}   # noqa: E731
    result, _, made = run_export(tmp_path, over)
    assert result["status"] == "failed" and "50 MB" in result["message"] and made == []


def test_the_twin_answers_a_file_node_with_a_placeholder_and_saves_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    nodes = export_group()
    send = twin.make_twin_send({"cif": "1"})
    answer = send(nodes[0], "/rpt/export", "", "")
    assert answer["file"]["data"].startswith(b"%PDF") and len(answer["file"]["data"]) < 1000
    shown = Shown()
    result = replay.run_api(flow(), nodes, {"cif": "1"}, send, shown, threading.Event(), twin=True)
    assert result["status"] == "finished", result
    sent = shown.details["g3"]["requests"][0]
    assert sent["file"]["twin"] is True and sent["file"]["saved"] is False and "path" not in sent["file"] and "BẢN SAO" in sent["file"]["name"]
    assert not (tmp_path / "profile").exists() and not any(tmp_path.rglob("*.pdf"))     # nothing in Downloads, nothing in a temp folder


def test_a_file_node_that_would_write_is_still_refused_like_any_other():
    nodes = export_group()
    nodes[-1]["risk"] = "write"
    sent = []
    result = replay.run_api(flow(), nodes, {"cif": "1"}, lambda n, u, h, b: sent.append(u) or {"ok": True, "status": 200, "ms": 1, "text": "{}"},
                            Shown(), threading.Event(), save_file=lambda *a: {"name": "x", "path": "x"})
    assert result["status"] == "refused" and "/rpt/export" not in sent


# ---- the bridge, with a fake process --------------------------------------------------------------------------------------

class FileBridge(IeBridge):
    def __init__(self, replies):
        super().__init__()
        self.replies, self.seen = replies, []

    def frame_op(self, op, selectors, value=""):
        self.seen.append(op)
        if op == "send":
            return [{"frame": "top", "id": "q1"}]
        return [{"id": "q1", "done": True, "status": 200, "ms": 4, "text": "", "error": "", "file": True, "ctype": "application/pdf",
                 "disp": 'attachment; filename="r.pdf"', "len": self.replies.get("len", 0)}]

    def request(self, message, timeout=15.0):
        self.seen.append(message["cmd"])
        return self.replies[message["cmd"]]


def test_the_bridge_hands_the_bytes_over_unchanged_from_base64():
    import base64

    bridge = FileBridge({"fetchfile": {"ok": True, "found": True, "b64": base64.b64encode(PDF_BYTES).decode("ascii")}})
    answer = bridge.send("top", "GET", "/r.pdf", "", "", sleep=lambda s: None)
    assert answer["ok"] and answer["file"] == {"data": PDF_BYTES, "ctype": "application/pdf", "disposition": 'attachment; filename="r.pdf"'}


def test_the_bridge_does_not_fetch_a_file_that_says_it_is_over_50_mb():
    bridge = FileBridge({"len": files.MAX_BYTES + 1, "dropfile": {"ok": True}})
    answer = bridge.send("top", "GET", "/r.pdf", "", "", sleep=lambda s: None)
    assert answer == {"ok": False, "error": "too_big", "size": files.MAX_BYTES + 1} and "fetchfile" not in bridge.seen


# ---- the web page: saving and opening ------------------------------------------------------------------------------------

class SendingBridge(FakeIeBridge):
    def __init__(self, answer):
        super().__init__()
        self.answer = answer

    def last_requests(self, frame, path, timeout=30.0):
        return []

    def bind(self, tab_id, peek=False):
        return {"ok": True}

    def unbind(self):
        return {"ok": True}

    def send(self, frame, method, url, headers, body):
        return self.answer


def export_core(tmp_path, monkeypatch, answer):
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    core, _ = make_core(tmp_path, ie_bridge=lambda: SendingBridge(answer))
    wf = {**flow(), "engine": "ie", "status": "approved"}
    core.store.put("flows", [{"title": "Xuất báo cáo giao dịch", "steps": [], "inputs": [], "learned_at": "x", "workflow": wf, "api": file_nodes()[2:]}])
    return core


def run_to_end(core):
    import time

    assert core.dispatch("POST", "/api/run/start", {"title": "Xuất báo cáo giao dịch", "mode": "simulate", "window": "ie-tab:1", "inputs": {"cif": "1"}})[0] == 200
    for _ in range(100):
        run = core.dispatch("GET", "/api/run/status", {})[1]
        if run.get("result"):
            break
        time.sleep(0.1)
    core._run["thread"].join(5)
    return run


def test_the_page_run_saves_the_pdf_in_downloads_rookie_audits_no_name_or_byte_and_does_not_cache_it(tmp_path, monkeypatch):
    core = export_core(tmp_path, monkeypatch, {"ok": True, "status": 200, "ms": 5, "text": "", "file": {"data": PDF_BYTES, "ctype": "application/pdf", "disposition": ""}})
    run = run_to_end(core)
    assert run["result"]["status"] == "finished", run
    saved = list((tmp_path / "profile" / "Downloads" / "Rookie").glob("Xuất báo cáo giao dịch-*.pdf"))
    assert len(saved) == 1 and saved[0].read_bytes() == PDF_BYTES
    request = next(r for d in run["details"].values() for r in d["requests"] if r.get("file"))
    assert request["file"]["path"] == str(saved[0])
    audit = (core.store.home / "audit.jsonl").read_text(encoding="utf-8")
    assert saved[0].name not in audit and "%PDF" not in audit
    assert core._cache == {}                                      # an export is made again every time


def test_the_configured_folder_is_used_when_there_is_one(tmp_path, monkeypatch):
    core = export_core(tmp_path, monkeypatch, {"ok": True, "status": 200, "ms": 5, "text": "", "file": {"data": PDF_BYTES, "ctype": "application/pdf", "disposition": ""}})
    core.store.put("download_folder", str(tmp_path / "mine"))
    run_to_end(core)
    assert len(list((tmp_path / "mine").glob("*.pdf"))) == 1


def test_the_address_of_a_dialog_is_learned_as_a_dialog_node_and_a_window_open_is_not():
    for target, expected in (("dialog", True), ("_blank", False)):
        raw, events, requests = export_requests()
        requests.append({"kind": "open", "frame": "main", "method": "GET", "url": "/touchpoint/utilities/dlgMessageBox.jsp?language=vi", "status": 200, "req": "", "res": "",
                         "hdr": "", "target": target, "file": {"guess": True, "ctype": "", "size": 0, "name": ""}, "after": {"t": 1_700_000_003_000}})
        nodes = replay.build_api(flow(), events, replay.templates(raw, events, requests))
        opened = next(n for n in nodes if n["url"].endswith("language=vi"))
        assert bool(opened.get("dialog")) is expected and opened["kind"] == "file"


@pytest.mark.parametrize("dialog, status", [(True, "finished"), (False, "needs_help")])
def test_a_dialog_of_the_page_that_shows_a_page_is_skipped_but_a_file_request_that_gets_a_page_still_needs_help(tmp_path, monkeypatch, dialog, status):
    """TouchPoint opens its own message box (Đồng ý, Hủy) with showModalDialog: a guess made from the address of a dialog is not a file the run must get."""
    core = export_core(tmp_path, monkeypatch, {"ok": True, "status": 200, "ms": 5, "text": "<xml><button>Đồng ý</button></xml>"})
    node = {**file_nodes()[2:][-1], "via": "open", "method": "GET", "body": "", "file": {"guess": True, "ctype": "", "size": 0, "name": ""}, **({"dialog": True} if dialog else {})}
    flows = core.store.get("flows")
    flows[0]["api"] = [node]
    core.store.put("flows", flows)
    run = run_to_end(core)
    assert run["result"]["status"] == status, run
    if dialog:
        assert not any(r.get("view") or r.get("error") for d in run["details"].values() for r in d["requests"])      # nothing of the dialog's page is shown


def test_the_open_routes_open_only_a_file_inside_the_rookie_folder(tmp_path, monkeypatch):
    core = export_core(tmp_path, monkeypatch, {"ok": True, "status": 200, "ms": 5, "text": "", "file": {"data": PDF_BYTES, "ctype": "application/pdf", "disposition": ""}})
    run_to_end(core)
    folder = tmp_path / "profile" / "Downloads" / "Rookie"
    mine = next(folder.glob("*.pdf"))
    opened = []
    core._open_path = lambda path: opened.append(Path(path))
    assert core.dispatch("POST", "/api/file/open", {"path": str(mine)})[0] == 200 and opened == [mine]
    assert core.dispatch("POST", "/api/file/open", {"path": str(mine), "folder": True})[0] == 200 and opened[-1] == folder
    printed = []
    core._print_path = lambda path: printed.append(Path(path)) or True
    reply = core.dispatch("POST", "/api/file/open", {"path": str(mine), "print": True})
    assert reply[0] == 200 and reply[1]["printed"] is True and printed == [mine]
    core._print_path = lambda path: False                            # no program of this PC prints that kind of file: it is opened for the teller to print
    reply = core.dispatch("POST", "/api/file/open", {"path": str(mine), "print": True})
    assert reply[0] == 200 and reply[1]["printed"] is False and opened[-1] == mine
    outside = tmp_path / "secret.pdf"
    outside.write_bytes(b"x")
    exe = folder / "run.exe"
    exe.write_bytes(b"MZ")
    sneaky = str(folder / ".." / ".." / "secret.pdf")
    before = len(opened)
    for path in (str(outside), sneaky, str(folder), str(tmp_path / "profile" / "Downloads" / "Rookie2" / "a.pdf"), "", str(exe), str(folder / "missing.pdf")):
        status, reply = core.dispatch("POST", "/api/file/open", {"path": path})
        assert status == 400 and "error" in reply, (path, reply)
    status, _ = core.dispatch("POST", "/api/file/open", {"path": str(outside), "folder": True})
    assert status == 400 and len(opened) == before                # nothing was opened for any of them
    assert files.inside(folder, mine) and not files.inside(folder, Path(str(folder) + "2") / "a.pdf") and not files.inside(folder, folder)


def test_a_page_that_starts_to_leave_just_before_its_form_line_arrives_still_counts_as_the_form_having_gone():
    class Bridge:
        def start_recording(self, *a, **k):
            return {}

        def poll(self):
            return []

        def stop_recording(self):
            return []

    session = IeSession(Bridge(), 1, "App")
    session._take([{"kind": "formgo", "uid": "g", "t": 1000, "frame": "top"},
                   {"kind": "click", "t": 1001, "uid": "c", "frame": "top", "tag": "button", "type": "submit", "id": "b", "label": "Xuat", "pos": 0, "ctl": True},
                   {"kind": "form", "uid": "f", "t": 1002, "frame": "top", "method": "POST", "url": "/export", "req": "a=1"}])
    session._flush_quiet(force=True)
    assert [(r["kind"], r["url"]) for r in session.requests] == [("form", "/export")]
