"""Task 11.11: a screen the page fills from an answer, field by field, is learned (labels and where each value is in the answer; never a
value) and made again, as a printable page, from the answer of every run."""

from __future__ import annotations

import json
import threading

from rookie_agent.ie import files, replay, report
from test_files import export_core, file_nodes, run_to_end
from test_replay import Shown, flow

GWT = ('//OK[1,2,3,4,5,6,7,["com.fis.tp.client.dto.DebitAdvice/1234567890","Customer Title 1","116000002248","EUR","10944/",'
       '"28598 - CN KCN TIEN SON - HOI SO","Một nghìn euro"],0,7]')
NEW = GWT.replace("Customer Title 1", "Tran Thi B").replace("116000002248", "119900001111").replace("10944/", "2500/").replace("Một nghìn euro", "Hai nghìn euro")


def field(label, value):
    return {"label": label, "value": value}


def screen(moment, fields, changed=None, tables=None):
    changed = fields if changed is None else changed
    return {"t": moment, "provisional": False, "after": None,
            "changed": [{"frame": "dlg", "kind": "field", "name": f["label"]} for f in changed],
            "frames": [{"frame": "dlg", "fields": fields, "tables": tables or [], "messages": []}]}


DLG = [field("Tên khách hàng", "Customer Title 1"), field("Số tài khoản", "116000002248"), field("Loại tiền", "EUR"),
       field("Số tiền", "10,944.00"), field("Chi nhánh", "28598 - CN KCN TIEN SON - HOI SO"), field("Bằng chữ", "Một nghìn euro"),
       field("Ngày 17/11/2026", "x")]
REQUEST = {"res": GWT, "t": 1000, "status": 200, "after": {"label": "IN BÁO NỢ/CÓ"}}


def test_the_values_of_each_kind_of_answer_are_candidates_with_the_rule_that_finds_them_again():
    gwt = dict((v, r) for r, v in report.candidates(GWT))
    assert gwt["Customer Title 1"] == {"gwt": 1} and "com.fis.tp.client.dto.DebitAdvice/1234567890" not in gwt
    xml = dict((v, r) for r, v in report.candidates("<Rs><Cust><Name>Tran A</Name></Cust><Trn><Amt>10944</Amt></Trn><Trn><Amt>2714</Amt></Trn></Rs>"))
    assert xml["Tran A"] == {"xml": ["Rs", "Cust", "Name"]} and xml["2714"] == {"xml": ["Rs", "Trn[2]", "Amt"]}
    js = dict((v, r) for r, v in report.candidates('{"a": {"name": "Tran A", "rows": [{"n": 5}, {"n": 77}]}, "ok": true, "none": null}'))
    assert js["Tran A"] == {"json": ["a", "name"]} and js["77"] == {"json": ["a", "rows", 1, "n"]} and "True" not in js
    assert report.candidates("<html><body>x</body></html>") == [] and report.candidates("plain") == []


def test_the_screen_fields_the_answer_holds_are_learned_with_their_labels_in_screen_order_and_nothing_else():
    fields = report.learn([REQUEST], [screen(1200, DLG)])
    (one,) = fields
    assert one["request"] == 0 and one["title"] == "IN BÁO NỢ/CÓ"
    assert [f["label"] for f in one["fields"]] == ["Tên khách hàng", "Số tài khoản", "Loại tiền", "Số tiền", "Chi nhánh", "Bằng chữ"]    # «Ngày 17/11/2026» has digits: no label
    assert one["fields"][3]["rule"] == {"gwt": 4}                                  # «10,944.00» on the screen, «10944/» in the answer
    text = json.dumps(report.learn([REQUEST], [screen(1200, DLG)]), ensure_ascii=False)
    for value in ("Customer Title", "116000002248", "10944", "TIEN SON"):
        assert value not in text                                                   # labels and rules only


def test_a_screen_read_before_the_call_or_unchanged_or_with_too_few_matches_teaches_nothing():
    assert report.learn([REQUEST], [screen(500, DLG)]) == []                                   # before the call
    assert report.learn([REQUEST], [screen(1200, DLG, changed=[])]) == []                      # the action did not change it
    assert report.learn([REQUEST], [screen(1200, DLG[:2])]) == []                              # two fields are not a report
    assert report.learn([{**REQUEST, "res": "plain text answer"}], [screen(1200, DLG)]) == []
    assert report.learn([{**REQUEST, "status": 500}], [screen(1200, DLG)]) == []
    assert report.learn([{**REQUEST, "res": GWT}], [{**screen(1200, DLG), "provisional": True}]) == []


def test_the_best_screen_after_the_call_is_the_one_that_is_taught():
    later = screen(3000, DLG[:3])
    assert [f["label"] for f in report.learn([REQUEST], [later, screen(1500, DLG)])[0]["fields"]][:2] == ["Tên khách hàng", "Số tài khoản"]
    assert len(report.learn([REQUEST], [later, screen(1500, DLG)])[0]["fields"]) == 6


def test_a_single_row_table_gives_its_headers_as_labels():
    table = {"id": "adv", "headers": ["Khách hàng", "Số TK", "Loại tiền", "Số tiền"], "rows": [["Customer Title 1", "116000002248", "EUR", "10944"]]}
    entry = {"t": 1200, "provisional": False, "changed": [{"frame": "dlg", "kind": "table", "name": "adv"}], "frames": [{"frame": "dlg", "fields": [], "tables": [table]}]}
    assert [f["label"] for f in report.learn([REQUEST], [entry])[0]["fields"]] == ["Khách hàng", "Số TK", "Loại tiền", "Số tiền"]


SPEC = {"title": "IN BÁO NỢ/CÓ", "fields": report.learn([REQUEST], [screen(1200, DLG)])[0]["fields"]}


def test_a_new_answer_gives_the_new_values_under_the_same_labels_and_a_missing_one_is_left_out():
    assert report.fill(SPEC, NEW)[:3] == [("Tên khách hàng", "Tran Thi B"), ("Số tài khoản", "119900001111"), ("Loại tiền", "EUR")]
    short = '//OK[1,2,["com.x.Dto/1","Tran Thi B"],0,7]'
    assert report.fill(SPEC, short) == [("Tên khách hàng", "Tran Thi B")]


def test_the_report_spec_goes_onto_the_node_of_its_request():
    nodes = [{"id": "a0"}, {"id": "a3"}]
    report.attach(nodes, [{"request": 3, "title": "T", "fields": [{"label": "L", "rule": {"gwt": 1}}]}, {"request": 9, "title": "X", "fields": [{"label": "L", "rule": {"gwt": 1}}]}])
    assert "report" not in nodes[0] and nodes[1]["report"] == {"title": "T", "fields": [{"label": "L", "rule": {"gwt": 1}}]}


def test_the_printable_page_is_ours_escaped_and_says_it_is_not_the_systems_own_document():
    page = files.pairs_report_html("Báo nợ <b>", [("Tên", "A & <script>alert(1)</script>"), ("Số tiền", "10.944")], None)
    assert page.startswith(files.REPORT_MARK) and "<script" not in page.lower() and "A &amp; &lt;script&gt;" in page and "Báo nợ &lt;b&gt;" in page
    assert "không phải chứng từ chính thức" in page and "href=" not in page and "src=" not in page


def report_node():
    return {**[n for n in file_nodes() if n["kind"] == "file"][0], "report": SPEC}


def test_a_run_makes_the_page_from_the_answer_and_counts_it_as_the_document(tmp_path):
    made = []

    def save_report(title, html):
        path = tmp_path / f"{len(made)}.html"
        path.write_text(html, encoding="utf-8")
        made.append((title, html))
        return {"name": path.name, "path": str(path)}

    shown = Shown()
    send = lambda node, url, headers, body: {"ok": True, "status": 200, "ms": 4, "text": NEW}   # noqa: E731
    result = replay.run_api(flow(), [report_node()], {"cif": "1"}, send, shown, threading.Event(), save_report=save_report)
    assert result["status"] == "finished", result
    (title, html), = made
    assert title == "IN BÁO NỢ/CÓ" and "Tran Thi B" in html and "119900001111" in html and "Customer Title" not in html and "<td>Tên khách hàng</td>" in html
    request = shown.details["g3"]["requests"][0]
    assert request["file"]["saved"] and request["file"]["kind"] == "report" and request["file"]["warn"] == ""
    assert ["Số tài khoản", "119900001111"] in request["view"]["pairs"]


def test_when_the_answer_has_none_of_the_fields_the_run_says_no_document_came(tmp_path):
    send = lambda node, url, headers, body: {"ok": True, "status": 200, "ms": 4, "text": "//OK[1,[\"x\"],0,7]"}   # noqa: E731
    result = replay.run_api(flow(), [report_node()], {"cif": "1"}, send, Shown(), threading.Event(), save_report=lambda t, h: {"name": "x", "path": "x"})
    assert result["status"] == "needs_help" and "chưa nhận được file báo cáo" in result["message"]


def test_the_page_run_saves_the_printable_page_in_the_rookie_folder_and_prints_it(tmp_path, monkeypatch):
    core = export_core(tmp_path, monkeypatch, {"ok": True, "status": 200, "ms": 5, "text": NEW})
    flows = core.store.get("flows")
    flows[0]["api"] = [report_node()]
    core.store.put("flows", flows)
    run = run_to_end(core)
    assert run["result"]["status"] == "finished", run
    folder = tmp_path / "profile" / "Downloads" / "Rookie"
    (page,) = folder.glob("*(bản in).html")
    assert files.is_report(page) and "Tran Thi B" in page.read_text(encoding="utf-8")
    audit = (core.store.home / "audit.jsonl").read_text(encoding="utf-8")
    assert "Tran Thi B" not in audit and "119900001111" not in audit
    printed = []
    core._print_path = lambda path: printed.append(path) or True
    assert core.dispatch("POST", "/api/file/open", {"path": str(page), "print": True})[1]["printed"] is True and printed == [page]
