"""A SOAP (XML) service: values written as text, a fault said in words even with HTTP 200, a value found again by the elements that hold it,
the operation told apart by the first element of the Body, a report sent inside the XML as base64 saved as the document it is."""

from __future__ import annotations

import base64
import json
import threading
from datetime import datetime

import pytest

from rookie_agent.ie import clean, files, replay, response_view, shape
from test_files import PDF_BYTES, run_export

ENVELOPE = ('<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Header/><soap:Body>'
            '<ns2:LoginRs xmlns:ns2="http://svc.example/"><SessionId>SID-0001-XYZ</SessionId><User>gdv01</User></ns2:LoginRs></soap:Body></soap:Envelope>')


def test_a_value_is_written_into_an_xml_body_as_text_and_into_other_bodies_as_it_is():
    body = "<soap:Body><GetStatement><Account>⟦acct⟧</Account><Note>⟦note⟧</Note></GetStatement></soap:Body>"
    filled, missing = replay.fill_in(body, {"acct": "0123456789", "note": 'a & b <script> "q" \'r\''}, xml=True)
    assert missing == [] and "<Account>0123456789</Account>" in filled
    assert "a &amp; b &lt;script&gt; &quot;q&quot; &apos;r&apos;" in filled and "<script>" not in filled      # no element can be added by a value
    assert replay.fill_in("a=⟦x⟧&b=2", {"x": "1&2"})[0] == "a=1&2&b=2"                                     # other bodies: as before
    assert replay.is_xml_body("<a/>") and replay.is_xml_body("x", "Content-Type: text/xml; charset=utf-8\nSOAPAction: x")
    assert not replay.is_xml_body("7|0|5|x|", "Content-Type: text/x-gwt-rpc") and not replay.is_xml_body("{}", "Content-Type: application/json")


@pytest.mark.parametrize("text, expected", [
    ('<soap:Envelope xmlns:soap="x"><soap:Body><soap:Fault><faultcode>soap:Server</faultcode><faultstring>Tai khoan khong ton tai</faultstring></soap:Fault></soap:Body></soap:Envelope>',
     "dịch vụ (SOAP) báo lỗi: Tai khoan khong ton tai"),
    ('<env:Envelope xmlns:env="x"><env:Body><env:Fault><env:Reason><env:Text xml:lang="en">Het phien</env:Text></env:Reason></env:Fault></env:Body></env:Envelope>',
     "dịch vụ (SOAP) báo lỗi: Het phien"),
    ("<IFX><Status><StatusCode>5</StatusCode><Severity>Error</Severity><StatusDesc>Sai   dinh dang</StatusDesc></Status></IFX>",
     "dịch vụ báo lỗi (Severity=Error): Sai dinh dang"),
    ("<a><Fault/></a>", "dịch vụ (SOAP) báo lỗi"),
    (ENVELOPE, ""), ('{"Fault": 1}', ""), ("", ""), ("<IFX><Status><Severity>Info</Severity></Status></IFX>", ""),
])
def test_a_fault_is_a_refusal_even_with_http_200(text, expected):
    assert replay.soap_fault(text) == expected
    assert replay.refused(200, text) == expected


def test_a_value_of_an_xml_answer_is_found_again_by_the_elements_that_hold_it():
    rule = replay.locate_value(ENVELOPE, "SID-0001-XYZ")
    assert rule == {"xml": ["Envelope", "Body", "LoginRs", "SessionId"]}                 # names only: no prefix, no value
    assert replay.take_value(ENVELOPE.replace("SID-0001-XYZ", "SID-9999-NEW"), rule) == "SID-9999-NEW"
    assert replay.take_value("<Envelope><Body><LoginRs/></Body></Envelope>", rule) is None                # not there: the run stops and asks
    assert replay.take_value("not xml", rule) is None
    repeated = "<R><Row><Id>a1</Id></Row><Row><Id>b2</Id></Row></R>"
    second = replay.locate_value(repeated, "b2")
    assert second == {"xml": ["R", "Row[2]", "Id"]} and replay.take_value(repeated.replace("b2", "c3"), second) == "c3"


def test_the_twin_answers_an_xml_link_with_a_value_of_the_same_shape():
    rule = replay.locate_value(ENVELOPE, "SID-0001-XYZ")
    skeleton = shape.shape(ENVELOPE, [rule])
    fake = shape.fake(skeleton, {"cif": "1"})
    value = replay.take_value(fake, rule)
    assert value and value != "SID-0001-XYZ" and "SID-0001-XYZ" not in json.dumps(skeleton)


def test_the_operation_of_a_soap_call_is_the_first_element_of_its_body():
    a = {"method": "POST", "url": "http://x/ws/svc", "body": '<s:Envelope xmlns:s="x"><s:Body><ns:GetAccount xmlns:ns="y"><Id>⟦e0⟧</Id></ns:GetAccount></s:Body></s:Envelope>'}
    b = {**a, "body": a["body"].replace("GetAccount", "GetHistory")}
    assert clean._op(a) == "POST /ws/svc GetAccount" and clean._op(b) == "POST /ws/svc GetHistory"
    assert clean._op({"method": "POST", "url": "http://x/ws/svc", "body": "<a/>"}) == "POST /ws/svc"


def test_the_view_of_an_xml_answer_has_the_names_of_the_elements_and_says_a_fault_first():
    view = response_view.summarize(ENVELOPE)
    assert ["SessionId", "SID-0001-XYZ"] in view["pairs"] and ["User", "gdv01"] in view["pairs"] and view["lines"] == []
    fault = response_view.summarize("<E><Body><Fault><faultstring>Loi</faultstring></Fault></Body></E>")
    assert fault["lines"] == ["dịch vụ (SOAP) báo lỗi: Loi"]


def wrapped(data: bytes, width: int = 76) -> str:
    text = base64.b64encode(data).decode("ascii")
    return "\r\n".join(text[i:i + width] for i in range(0, len(text), width))


def test_a_document_sent_inside_the_xml_as_base64_is_found_and_only_a_document():
    xml = f'<Envelope><Body><ReportRs><Status>0</Status><ReportData>{wrapped(PDF_BYTES * 2)}</ReportData></ReportRs></Body></Envelope>'
    assert files.embedded_document(xml) == PDF_BYTES * 2 and files.embedded_document(xml.encode("utf-8")) == PDF_BYTES * 2
    noise = f"<A><Token>{base64.b64encode(bytes(range(200))).decode()}</Token><Note>{'x' * 400}</Note></A>"
    assert files.embedded_document(noise) is None                                          # long base64 that is no document: left alone
    assert files.embedded_document("<A>JVBERi0=</A>") is None and files.embedded_document("JVBERi0" + "A" * 400) is None   # short, or not XML


def soap_send(answer_text, seen=None):
    def send(node, url, headers, body):
        if seen is not None:
            seen.append(body)
        return {"ok": True, "status": 200, "ms": 5, "text": answer_text}
    return send


def test_a_report_inside_a_soap_answer_is_saved_as_the_pdf_it_is(tmp_path):
    xml = f"<Envelope><Body><ReportRs><ReportData>{wrapped(PDF_BYTES)}</ReportData></ReportRs></Body></Envelope>"
    result, shown, made = run_export(tmp_path, soap_send(xml))
    assert result["status"] == "finished" and len(made) == 1 and made[0].read_bytes() == PDF_BYTES and made[0].suffix == ".pdf"
    sent = shown.details["g3"]["requests"][0]["file"]
    assert (sent["kind"], sent["warn"]) == ("pdf", "")


def test_a_soap_fault_with_http_200_stops_the_run_and_says_what_the_service_said(tmp_path):
    fault = "<Envelope><Body><Fault><faultstring>Het han muc in</faultstring></Fault></Body></Envelope>"
    node = {**[n for n in run_export.__globals__["file_nodes"]() if n["kind"] == "file"][0], "kind": "xhr"}      # a call of the flow, not a file
    result, shown, made = run_export(tmp_path, soap_send(fault), nodes=[node])
    assert result["status"] == "needs_help" and "Het han muc in" in result["message"] and made == []


GWT_KEY = '//OK[1234567,12345678,0,0,["com.fis.tp.client.report.ReportKey/1234567890","1ABC2dEfGHIjk3lMno4pqr5"],0,0]'


def test_a_gwt_answer_that_arrives_as_a_file_is_an_answer_not_a_document_and_a_run_without_a_document_says_so(tmp_path):
    send = lambda node, url, headers, body: ({"ok": True, "status": 200, "ms": 7, "text": "", "file": {"data": GWT_KEY.encode("utf-8"), "ctype": "application/octet-stream", "disposition": ""}}  # noqa: E731
                                              if node["kind"] == "file" else {"ok": True, "status": 200, "ms": 1, "text": "{}"})
    result, shown, made = run_export(tmp_path, send)
    assert made == []                                                                   # nothing saved: the key is no file
    assert result["status"] == "needs_help" and "chưa nhận được file báo cáo" in result["message"]
    request = shown.details["g3"]["requests"][0]
    assert "file" not in request and request.get("view") and "error" not in request    # shown as the answer it is
    assert files.sniff(GWT_KEY.encode("utf-8")) == "gwt" and files.warning_for("gwt") == ""


def test_a_run_that_did_get_its_document_is_finished(tmp_path):
    result = run_export(tmp_path, lambda node, url, headers, body: {"ok": True, "status": 200, "ms": 7, "text": "", "file": {"data": PDF_BYTES, "ctype": "application/pdf", "disposition": ""}})[0]
    assert result["status"] == "finished"


def test_a_value_typed_into_a_soap_call_goes_out_as_text(tmp_path):
    node = {**[n for n in run_export.__globals__["file_nodes"]() if n["kind"] == "file"][0], "kind": "xhr", "headers": "Content-Type: text/xml; charset=utf-8",
            "body": "<Body><Find><Name>⟦cif⟧</Name></Find></Body>"}
    seen: list[str] = []
    save_nothing = lambda *a: None      # noqa: E731
    from test_replay import Shown, flow

    result = replay.run_api(flow(), [node], {"cif": "A & B <x>"}, soap_send("<R><A>1</A></R>", seen), Shown(), threading.Event(), save_file=save_nothing)
    assert result["status"] == "finished" and seen == ["<Body><Find><Name>A &amp; B &lt;x&gt;</Name></Find></Body>"]
