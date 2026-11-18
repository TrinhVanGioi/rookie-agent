"""Gate 7: a recording's requests become templates, the learned flow carries them, and a simulated run sends them again (fakes here;
the page part runs on a real IE in test_ie_real.py)."""

import threading

from rookie_agent.ie import replay, response_view
from rookie_agent.ie.recorder import _iso

T_FILL, T_KIND, T_FIND = 1_700_000_000_000, 1_700_000_001_000, 1_700_000_002_000
SEL_CIF, SEL_KIND, SEL_FIND = "frame=main|id=txtCustAcctNumber", "frame=main|id=cboKind", "frame=main|id=btnFind"


def recorded():
    raw = [{"kind": "input", "t": T_FILL, "value": "0123456789"}, {"kind": "select", "t": T_KIND, "value": "CIF"},
           {"kind": "click", "t": T_FIND}]
    events = [{"seq": 0, "ts": _iso(T_FILL), "type": "input", "target": {"selectors": [SEL_CIF]}},
              {"seq": 1, "ts": _iso(T_KIND), "type": "select", "target": {"selectors": [SEL_KIND]}},
              {"seq": 2, "ts": _iso(T_FIND), "type": "click", "target": {"selectors": [SEL_FIND]}}]
    requests = [
        {"frame": "main", "method": "POST", "url": "/tp/find", "status": 200, "hdr": "X-GWT-Permutation:ABC\n",
         "req": "7|0|5|find|CIF|0123456789|", "res": '//OK[1,["NGUYEN VAN A","com.tp.Customer/123"],0,7]', "after": {"t": T_FIND}},
        {"frame": "main", "method": "GET", "url": "/tp/menu", "status": 200, "req": "", "res": "{}", "after": {}},   # page load: not a step
        {"frame": "main", "method": "POST", "url": "/tp/login", "status": 200, "req": 'pass="***"', "res": "", "after": {"t": T_FIND}},
    ]
    return raw, events, requests


def flow():
    return {"inputs": [{"name": "txtcustacctnumber", "label": "Số CIF"}],
            "steps": [{"id": "s1_cif", "action": "fill", "value": "{txtcustacctnumber}", "target": {"selectors": [SEL_CIF]}, "risk": "read"},
                      {"id": "s2_kind", "action": "select", "value": "CIF", "target": {"selectors": [SEL_KIND]}, "risk": "read"},
                      {"id": "s3_find", "action": "click", "target": {"selectors": [SEL_FIND]}, "risk": "read"}]}


def test_what_was_typed_is_a_mark_and_a_request_that_hid_a_secret_cannot_be_sent_again():
    found = replay.templates(*recorded())
    assert "0123456789" not in str(found)                                      # the typed value is never kept
    assert found[0]["body"] == "7|0|5|find|⟦e1⟧|⟦e0⟧|" and found[0]["after_seq"] == 2 and found[0]["complete"]
    assert found[0]["headers"] == "X-GWT-Permutation:ABC\n" and found[0]["kind"] == "gwt"
    assert found[1]["after_seq"] is None and found[2]["complete"] is False


def test_learning_puts_each_request_under_its_step_with_the_step_value():
    raw, events, requests = recorded()
    by_step = replay.attach(flow(), events, replay.templates(raw, events, requests))
    assert list(by_step) == ["s3_find"] and len(by_step["s3_find"]) == 2        # the page-load request is not part of the flow
    assert by_step["s3_find"][0]["body"] == "7|0|5|find|CIF|⟦txtcustacctnumber⟧|" and by_step["s3_find"][0]["unresolved"] == []


class Shown:
    def __init__(self):
        self.steps, self.details = [], {}

    def progress(self, step_id, status, detail):
        self.steps.append((step_id, status))

    def show(self, step_id, shown):
        self.details[step_id] = shown


def by_step_ok():
    raw, events, requests = recorded()
    found = replay.attach(flow(), events, replay.templates(raw, events, requests))
    found["s3_find"] = found["s3_find"][:1]
    return found


def test_a_simulated_run_sends_the_new_value_from_the_page_and_shows_what_came_back():
    sent, shown = [], Shown()

    def send(item, url, body):
        sent.append((item["frame"], url, body))
        return {"ok": True, "status": 200, "ms": 12, "text": '//OK[1,["TRAN THI B","com.tp.Customer/123"],0,7]'}

    result = replay.simulate(flow(), by_step_ok(), {"txtcustacctnumber": "9988776655"}, send, shown, threading.Event())
    assert result["status"] == "finished"
    assert sent == [("main", "/tp/find", "7|0|5|find|CIF|9988776655|")]
    assert [s for s, st in shown.steps if st == "skipped"] == ["s1_cif", "s2_kind"]   # screen-only steps are passed over
    view = shown.details["s3_find"]["requests"][0]["view"]
    assert view["kind"] == "gwt" and view["lines"] == ["TRAN THI B"]          # class names are left out


def test_a_refused_answer_stops_and_a_write_step_with_requests_never_sends():
    shown = Shown()
    result = replay.simulate(flow(), by_step_ok(), {"txtcustacctnumber": "1"}, lambda *a: {"ok": True, "status": 200, "ms": 1, "text": "//EX[2,0]"},
                             shown, threading.Event())
    assert result["status"] == "needs_help" and "//EX" in result["message"]
    writing = flow()
    writing["steps"][2]["risk"] = "write"
    sent = []
    result = replay.simulate(writing, by_step_ok(), {"txtcustacctnumber": "1"}, lambda *a: sent.append(a) or {}, Shown(), threading.Event())
    assert result["status"] == "refused" and sent == []


def test_a_missing_value_is_asked_never_guessed():
    result = replay.simulate(flow(), by_step_ok(), {}, lambda *a: {}, Shown(), threading.Event())
    assert result["status"] == "needs_help" and "txtcustacctnumber" in result["message"]


def test_answers_are_made_short_to_read():
    j = response_view.summarize('{"customer": {"name": "A", "cif": "1"}, "accounts": [{"no": "11", "bal": 5}, {"no": "12", "bal": 6}]}')
    assert ["customer.name", "A"] in j["pairs"] and j["rows"][0] == ["no", "bal"] and len(j["rows"]) == 3
    h = response_view.summarize("<html><body><p>Ket qua</p><table><tr><td>CIF</td><td>123</td></tr></table><script>x()</script></body></html>")
    assert h["rows"] == [["CIF", "123"]] and h["lines"] == ["Ket qua"]
    assert response_view.summarize("//EX[1]")["lines"][0].startswith("Máy chủ báo lỗi")


def test_the_flow_tab_runs_the_simulation_and_shows_each_step(tmp_path):
    import json

    from test_webui import make_core, wait_for

    class Bridge:
        sent = []

        def tabs(self):
            return [{"id": 1, "title": "TouchPoint"}]

        def bind(self, tab_id):
            return {"ok": True}

        def unbind(self):
            return {"ok": True}

        def send(self, frame, method, url, headers, body):
            Bridge.sent.append(body)
            return {"ok": True, "status": 200, "ms": 5, "text": '{"name": "TRAN THI B"}'}

    core, _ = make_core(tmp_path, ie_bridge=lambda: Bridge())
    workflow = {**flow(), "engine": "ie", "status": "draft"}
    core.store.put("flows", [{"title": "Tra CIF", "steps": [], "learned_at": "x", "workflow": workflow, "requests": by_step_ok()}])
    listed = core.dispatch("GET", "/api/flows", {})[1]["flows"][0]
    assert listed["request_steps"] == ["s3_find"] and "requests" not in json.dumps(listed).replace("request_steps", "")
    status, reply = core.dispatch("POST", "/api/run/start", {"title": "Tra CIF", "mode": "simulate", "window": "ie-tab:1",
                                                             "inputs": {"txtcustacctnumber": "9988776655"}})
    assert status == 200, reply
    done = wait_for(core, "finished")
    assert Bridge.sent == ["7|0|5|find|CIF|9988776655|"]
    assert done["details"]["s3_find"]["requests"][0]["view"]["pairs"] == [["name", "TRAN THI B"]]
    core._run["thread"].join(5)
    audit = (core.store.home / "audit.jsonl").read_text(encoding="utf-8")
    assert "9988776655" not in audit and "TRAN THI B" not in audit and '"simulate"' in audit
