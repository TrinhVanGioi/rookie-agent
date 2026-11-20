"""Gate 9 (windows agent): the shape of an answer without a value, the fake made from it, the run on the twin (nothing leaves the PC,
write and money wait for a person's Duyệt), the process fields sent with a session, the proxies to the server's twin, the n8n file."""

import json
import re
import threading
import time

import pytest

from rookie_agent.ie import n8n, replay, shape, twin
from rookie_agent.server_client import ServerClient, ServerError
from test_replay import Shown, flow, nodes, recorded
from test_webui import FakeServer, ie_core, make_core

VALUES = ["0123456789", "NGUYỄN VĂN ĐỨC", "Trần Thị Bích", "XT9f8e7d6c5b4a3", "KH00042", "15000000", "0987654321"]


def leaked(skeleton):
    text = json.dumps(skeleton, ensure_ascii=False)
    return [v for v in VALUES if v in text]


# ---- the shape keeps no value --------------------------------------------------------------------------------------------------

def test_a_json_answer_keeps_keys_and_types_and_no_value():
    answer = json.dumps({"cif": "0123456789", "name": "NGUYỄN VĂN ĐỨC", "token": "XT9f8e7d6c5b4a3", "balance": 15000000, "ok": True,
                         "accounts": [{"no": "0987654321", "owner": "Trần Thị Bích"}]}, ensure_ascii=False)
    skeleton = shape.shape(answer)
    assert leaked(skeleton) == []
    fake = json.loads(shape.fake(skeleton, {"cif": "1"}))
    assert set(fake) == {"cif", "name", "token", "balance", "ok", "accounts"} and isinstance(fake["balance"], int) and fake["ok"] is True
    assert re.fullmatch(r"\d{10}", fake["cif"]) and len(fake["accounts"]) == 1
    assert leaked({"fake": fake}) == []


def test_a_gwt_answer_keeps_class_names_and_masks_the_other_strings_and_amounts():
    answer = '//OK[1,15000000,["NGUYỄN VĂN ĐỨC","KH00042","com.tp.Customer/123","java.lang.String/2004016611"],0,7]'
    skeleton = shape.shape(answer)
    assert leaked(skeleton) == []
    text = shape.fake(skeleton, {})
    assert text.startswith("//OK[1,") and "com.tp.Customer/123" in text and "java.lang.String/2004016611" in text
    assert leaked({"t": text}) == [] and text.endswith(",0,7]")


def test_an_html_answer_keeps_tags_and_attribute_names_not_text_or_other_values():
    answer = ('<html><body><form action="/pay?acct=0123456789" method="post"><input id="cif" name="cif" type="text" value="0123456789">'
              '<table id="t"><tr><td class="n">NGUYỄN VĂN ĐỨC</td><td>KH00042</td></tr></table></form></body></html>')
    skeleton = shape.shape(answer)
    assert leaked(skeleton) == []
    text = shape.fake(skeleton, {"cif": "x"})
    assert '<input id="cif" name="cif" type="text"' in text and '<td class="n">' in text and "<table id=\"t\">" in text
    assert leaked({"t": text}) == []


def test_a_text_answer_is_only_a_shape():
    skeleton = shape.shape("Khach hang: Trần Thị Bích\nSo CIF: 0123456789")
    assert leaked(skeleton) == []
    assert shape.fake(skeleton, {}).count("\n") == 1


def test_the_fake_is_the_same_for_the_same_inputs_and_another_for_another_cif():
    skeleton = shape.shape(json.dumps({"name": "NGUYEN VAN A", "cif": "0123456789"}))
    one, again, other = (shape.fake(skeleton, {"cif": c}) for c in ("1", "1", "2"))
    assert one == again and one != other
    assert shape.fake(skeleton, {"cif": "1"}, "seed-a") != shape.fake(skeleton, {"cif": "1"}, "seed-b")


def test_the_links_of_a_flow_still_find_a_value_in_the_fake_for_all_three_kinds_of_rule():
    html = '<html><table><tr><td>Ten</td><td>TRAN THI B</td></tr></table></html>'
    rule_html = replay.locate_value(html, "TRAN THI B")
    assert "before" in rule_html
    for answer, rule in [(json.dumps({"a": {"xsrf": "NEWTOKEN77"}}), {"json": ["a", "xsrf"]}),
                         ('//OK[1,["TRAN THI B","KH00099","com.tp.Customer/123"],0,7]', {"gwt": 1}), (html, rule_html)]:
        fake = shape.fake(shape.shape(answer, [rule]), {"cif": "1"})
        value = replay.take_value(fake, rule)
        assert value and value not in answer, (rule, fake)
        assert replay.take_value(shape.fake(shape.shape(answer, [rule]), {"cif": "1"}), rule) == value


def test_a_recording_stores_a_shape_with_each_template_and_no_value_in_it():
    found = replay.templates(*recorded())
    assert all(item["shape"] for item in found)
    assert "KH00042" not in json.dumps([item["shape"] for item in found]) and "XT9f8e7d6c5b4a3" not in json.dumps([i["shape"] for i in found])
    api = nodes()
    assert all("shape" in n for n in api)


# ---- run_api on the twin -------------------------------------------------------------------------------------------------------

class Approver:
    """A person: waits for a question on the controller and answers it from another thread."""

    def __init__(self, controller, answers):
        self.controller, self.answers, self.asked = controller, list(answers), []
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def loop(self):
        end = time.monotonic() + 5
        while self.answers and time.monotonic() < end:
            ask = self.controller.ask
            if ask is not None:
                self.asked.append(ask)
                self.controller.decide(ask["id"], self.answers.pop(0))
            time.sleep(0.01)


def twin_run(api, workflow=None, answers=(), role="maker"):
    from rookie_agent.webui.run import WebController

    stop, sent = threading.Event(), []
    controller = WebController(stop, {}, lambda: "")
    real_send = lambda *a: sent.append(a) or {"ok": True, "status": 200, "ms": 1, "text": "REAL"}   # noqa: E731
    person = Approver(controller, answers)
    result = replay.run_api(workflow or flow(), api, {"cif": "9988776655"}, twin.make_twin_send({"cif": "9988776655"}), controller, stop,
                            twin=True, role=role)
    person.thread.join(1)
    return result, controller, person, sent


def test_the_twin_goes_through_three_linked_nodes_and_the_real_send_is_never_used():
    result, controller, person, sent = twin_run(nodes()[:3])
    assert result["status"] == "finished" and result["twin"] is True and result["simulated_ms"] >= 0
    assert sent == [] and person.asked == []
    assert [s["status"] for s in controller.steps] == ["done"] * 3
    sent_third = controller.details["g3"]["requests"][0]
    assert sent_third["status"] == 200 and re.fullmatch(r"kh=[A-Z]{2}\d{5}&tab=1", sent_third["body"])   # the link took the fake's value
    assert controller.details["g3"]["twin"] == replay.TWIN_BANNER


def test_a_write_node_waits_for_a_person_and_goes_on_after_the_duyet_and_money_never_goes_by_itself():
    api = nodes()[:3]
    api[1]["risk"] = "write"
    result, controller, person, _ = twin_run(api, answers=[True])
    assert result["status"] == "finished" and [a["risk"] for a in person.asked] == ["write"] and person.asked[0]["kind"] == "approve"
    api[2]["risk"] = "money"
    result, controller, person, _ = twin_run(api, answers=[True, True])
    assert [a["risk"] for a in person.asked] == ["write", "money"] and result["status"] == "finished"


def test_a_no_stops_the_twin_run_and_a_stop_wins():
    api = nodes()[:3]
    api[1]["risk"] = "money"
    result, controller, person, _ = twin_run(api, answers=[False])
    assert result["status"] == "stopped" and [s["status"] for s in controller.steps][-1] == "rejected"


def test_a_checker_stage_without_a_write_node_still_waits_for_the_checker_at_its_last_node():
    result, controller, person, _ = twin_run(nodes()[:3], answers=[True], role="checker")
    assert result["status"] == "finished" and len(person.asked) == 1 and person.asked[0]["step_id"] == "g3"


# ---- the whole process through the page's routes -------------------------------------------------------------------------------

class NoIe:
    """If the twin ever touched IE this would fail."""

    def __getattr__(self, name):
        raise AssertionError(f"the twin must not touch IE: {name}")


def two_stage_core(tmp_path):
    api = nodes()[:3]
    api[1]["risk"] = "write"
    maker = {"title": "Lập lệnh", "inputs": ["cif"], "steps": [], "warnings": [], "learned_at": "x", "api": api,
             "workflow": {**flow(), "schema_version": 2, "engine": "ie", "id": "wf-maker", "version": 1, "status": "approved"}}
    java = {"title": "KSV duyệt", "inputs": [], "steps": [], "warnings": [], "learned_at": "x", "api": [],
            "workflow": {"engine": "java", "id": "wf-checker", "version": 1, "status": "approved", "inputs": [],
                         "steps": [{"id": "k1", "action": "click", "target": {"label": "Mở lệnh"}, "risk": "read", "mode": "auto"},
                                   {"id": "k2", "action": "click", "target": {"label": "Duyệt"}, "risk": "money", "mode": "approve"}]}}
    core, _ = make_core(tmp_path, ie_bridge=lambda: NoIe())
    core.store.put("flows", [maker, java])
    return core


def status_of(core, state=None, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        status = core.dispatch("GET", "/api/twin/status", {})[1]
        if state is None and status["state"] != "running" or status["state"] == state:
            return status
        time.sleep(0.02)
    raise AssertionError(status["state"])


def test_a_process_runs_maker_then_queue_then_checker_and_pauses_for_each_duyet(tmp_path):
    core = two_stage_core(tmp_path)
    body = {"stages": [{"flow_id": "wf-maker", "role": "maker", "label": "GDV lập lệnh"}, {"flow_id": "wf-checker", "role": "checker", "label": "KSV duyệt"}],
            "inputs": {"cif": "9988776655"}, "seed": "7"}
    status, reply = core.dispatch("POST", "/api/twin/run", body)
    assert status == 200 and "BẢN SAO" in reply["banner"]
    asks = []
    for _ in range(4):
        waiting = status_of(core)
        if waiting["state"] != "waiting_approval":
            break
        assert waiting["twin"] and waiting["banner"].startswith("BẢN SAO") and waiting["ask"]["risk"] in ("write", "money")
        asks.append((waiting["ask"]["role"], waiting["ask"]["risk"]))
        assert core.dispatch("POST", "/api/twin/decide", {"ask_id": waiting["ask"]["id"], "approve": True})[0] == 200
        time.sleep(0.1)
    done = status_of(core, "finished")
    assert asks == [("maker", "write"), ("checker", "money")]
    assert done["result"]["twin"] is True and len(done["stages"]) == 2
    ids = [s["id"] for s in done["steps"]]
    assert ids.index("q1") > ids.index("c1.g3") and ids.index("c2.k1") > ids.index("q1")        # maker, queue, checker
    assert done["details"]["c2.k2"]["screen"] is True and done["details"]["c1.g2"]["twin"].startswith("BẢN SAO")
    lines = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert lines[-1]["mode"] == "twin" and "9988776655" not in json.dumps(lines[-1])


def test_a_flow_learned_before_the_twin_existed_says_to_record_and_learn_again(tmp_path):
    core = two_stage_core(tmp_path)
    flows = core.store.get("flows")
    for node in flows[0]["api"]:
        node.pop("shape")
    core.store.put("flows", flows)
    status, reply = core.dispatch("POST", "/api/twin/run", {"stages": [{"flow_id": "wf-maker", "role": "maker"}], "inputs": {}})
    assert status == 400 and reply["error"] == "Luồng này học trước khi có bản sao, hãy Ghi và Học lại."


def test_a_dung_khan_ends_a_run_that_waits_for_a_duyet(tmp_path):
    core = two_stage_core(tmp_path)
    core.dispatch("POST", "/api/twin/run", {"stages": [{"flow_id": "wf-maker", "role": "maker"}], "inputs": {"cif": "9988776655"}})
    assert status_of(core)["state"] == "waiting_approval"
    core.dispatch("POST", "/api/twin/stop", {})
    assert status_of(core, "stopped")["result"]["status"] == "stopped"


def test_the_flows_list_says_which_flows_have_a_twin(tmp_path):
    core = two_stage_core(tmp_path)
    rows = {r["title"]: r for r in core.dispatch("GET", "/api/flows", {})[1]["flows"]}
    assert rows["Lập lệnh"]["twin_ready"] is True and rows["Lập lệnh"]["workflow_id"] == "wf-maker" and rows["KSV duyệt"]["twin_ready"] is False


# ---- what goes to the server with a session ------------------------------------------------------------------------------------

def test_a_session_goes_up_with_the_role_a_keyed_hash_of_the_case_and_the_calls_with_their_time_and_no_query(tmp_path):
    posted = []

    class Server(FakeServer):
        def post_session(self, session_id, engine, events, **extra):
            posted.append((engine, events, extra))

    core, _ = make_core(tmp_path, server_client=Server)
    assert core.dispatch("POST", "/api/twin/settings", {"role": "checker"})[1]["role"] == "checker"
    events = [{"seq": 0, "type": "click", "target": {"label": "Tìm"}}, {"seq": 1, "type": "click", "target": {"label": "Duyệt"}}]
    core.store.save("s1", events, "lần 1", engine="ie")
    key = core._case_key(["POST /api/transfers/LCT00042/approve", ""])
    base = {"body": "", "headers": "", "links": {}, "kind": "xhr", "frame": "top", "complete": True, "answer": "json"}
    core.store.update("s1", role="checker", case_key=key, requests=[
        {**base, "index": 0, "after_seq": 0, "method": "GET", "url": "http://host/tp/find?cif=0123456789&x=1", "status": 200, "ms": 140},
        {**base, "index": 1, "after_seq": 1, "method": "POST", "url": "/api/transfers/LCT00042/approve", "status": 200, "ms": 90},
        {**base, "index": 2, "after_seq": None, "method": "GET", "url": "/init", "status": 200, "ms": 5}])
    status, reply = core.dispatch("POST", "/api/learn", {"ids": ["s1"], "title": "Duyệt"})
    assert status == 200, reply
    engine, sent_events, extra = posted[0]
    assert extra["role"] == "checker" and extra["case_key"] == key and re.fullmatch(r"[0-9a-f]{32}", key)
    assert sent_events[0]["api_calls"] == [{"method": "GET", "path": "/tp/find", "status": 200, "ms": 140}]
    assert sent_events[1]["api_calls"] == [{"method": "POST", "path": "/api/transfers/{id}/approve", "status": 200, "ms": 90}]
    assert "LCT00042" not in json.dumps(posted, default=str) and "0123456789" not in json.dumps(posted, default=str)


def test_the_case_key_is_a_keyed_hash_that_depends_on_the_unit_key_and_is_the_same_everywhere_for_the_same_id(tmp_path):
    core, _ = make_core(tmp_path)
    settings = core.dispatch("GET", "/api/twin/settings", {})[1]
    assert len(settings["unit_key"]) >= 16 and settings["role"] == "maker"            # made once and shown
    assert core.dispatch("GET", "/api/twin/settings", {})[1]["unit_key"] == settings["unit_key"]
    first = core._case_key(["xx LCT00007 yy"])
    assert first == core._case_key(["LCT00007"]) and first != core._case_key(["LCT00008"]) and core._case_key(["nothing here"]) is None
    core.dispatch("POST", "/api/twin/settings", {"unit_key": "another-unit-key-1234"})
    assert core._case_key(["LCT00007"]) != first
    assert core.dispatch("POST", "/api/twin/settings", {"role": "boss"})[0] == 400


def test_an_ie_session_is_posted_as_schema_3_with_role_and_case_key_in_the_body():
    sent = {}

    class Client(ServerClient):
        def _call(self, method, path, body=None, timeout=0):
            sent.update(path=path, body=body)
            return {}

    Client("http://x").post_session("s", "ie", [], role="maker", case_key="ab" * 16)
    assert sent["body"]["schema_version"] == 3 and sent["body"]["role"] == "maker" and sent["body"]["case_key"] == "ab" * 16
    Client("http://x").post_session("s", "java", [])
    assert sent["body"]["schema_version"] == 1 and "role" not in sent["body"]


# ---- the proxies to the server's twin ---------------------------------------------------------------------------------------------

def test_the_twin_routes_are_passed_to_the_server_and_a_server_error_is_a_plain_message(tmp_path):
    calls = []

    class Server(FakeServer):
        def twin_processes(self):
            calls.append("list"); return {"processes": []}

        def twin_save(self, process):
            calls.append(("save", process)); return {"id": "p1"}

        def twin_discover(self, process_id=""):
            calls.append(("discover", process_id)); return {"nodes": [], "edges": [], "variants": [], "cases": 0}

        def twin_suggest(self):
            calls.append("suggest"); return {"name": "x", "stages": [], "handoffs": []}

        def twin_metrics(self, process_id):
            calls.append(("metrics", process_id)); return {"cases": 3, "hidden": True, "steps": [], "queues": [], "bottleneck": None}

        def twin_simulate(self, process_id, payload):
            calls.append(("simulate", process_id, payload)); raise ServerError("Máy chủ từ chối (500): lỗi")

    core, _ = make_core(tmp_path, server_client=Server)
    assert core.dispatch("GET", "/api/twin/processes", {})[1] == {"processes": []}
    assert core.dispatch("POST", "/api/twin/processes", {"name": "P", "stages": [{"id": "s1"}], "handoffs": []})[1] == {"id": "p1"}
    assert core.dispatch("GET", "/api/twin/discover", {"process_id": "p1"})[1]["cases"] == 0
    assert core.dispatch("GET", "/api/twin/suggest", {})[1]["name"] == "x"
    assert core.dispatch("GET", "/api/twin/metrics", {"process_id": "p1"})[1]["hidden"] is True
    status, reply = core.dispatch("POST", "/api/twin/simulate", {"process_id": "p1", "seed": 3, "staff": {"maker": 2}})
    assert status == 400 and "Máy chủ từ chối" in reply["error"]
    assert ("simulate", "p1", {"seed": 3, "staff": {"maker": 2}}) in calls and ("save", {"name": "P", "stages": [{"id": "s1"}], "handoffs": []}) in calls
    assert core.dispatch("POST", "/api/twin/processes", {"name": "", "stages": []})[0] == 400
    assert core.dispatch("GET", "/api/twin/metrics", {})[0] == 400


def test_a_get_query_reaches_the_route_as_its_body(tmp_path):
    import urllib.request
    from http.server import ThreadingHTTPServer

    from rookie_agent.webui.server import make_handler

    seen = []

    class Server(FakeServer):
        def twin_metrics(self, process_id):
            seen.append(process_id); return {"cases": 0, "hidden": True, "steps": [], "queues": []}

    core, _ = make_core(tmp_path, server_client=Server)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(core, 0, lambda: None))
    port = httpd.server_address[1]
    httpd.RequestHandlerClass = make_handler(core, port, lambda: None)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/twin/metrics?process_id=p9", headers={"X-Rookie": "1"})
        assert json.loads(urllib.request.urlopen(request).read())["hidden"] is True
    finally:
        httpd.shutdown()
    assert seen == ["p9"]


# ---- the n8n file ------------------------------------------------------------------------------------------------------------------

def test_the_n8n_export_has_every_node_and_connection_and_no_value_or_header(tmp_path):
    core = two_stage_core(tmp_path)
    flows = core.store.get("flows")
    flows[0]["api"][0]["headers"] = "Cookie: JSESSIONID=SECRETCOOKIE\n"
    flows[0]["api"][1]["body"] = '7|0|5|find|CIF|⟦cif⟧|xsrf_token="⟦l1⟧"|'
    core.store.put("flows", flows)
    status, doc = core.dispatch("POST", "/api/twin/export", {"name": "Chuyển tiền", "stages": [
        {"flow_id": "wf-maker", "role": "maker", "label": "GDV lập lệnh"}, {"flow_id": "wf-checker", "role": "checker", "label": "KSV"}]})
    assert status == 200
    text = json.dumps(doc, ensure_ascii=False)
    for secret in ("SECRETCOOKIE", "KH00042", "XT9f8e7d6c5b4a3", "0123456789", "Cookie"):
        assert secret not in text
    types = [n["type"] for n in doc["nodes"]]
    assert types.count("n8n-nodes-base.httpRequest") == 3 and "n8n-nodes-base.wait" in types and "n8n-nodes-base.noOp" in types
    assert any(n["name"] == "Bàn giao / Hàng chờ duyệt" for n in doc["nodes"]) and n8n.NOTE in text
    http_nodes = [n for n in doc["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"]
    assert "⟦cif⟧" in http_nodes[1]["parameters"]["body"] and all("headers" not in n["parameters"] for n in http_nodes)
    names = [n["name"] for n in doc["nodes"] if n["type"] != "n8n-nodes-base.stickyNote"]
    assert len(names) == len(set(names)) and all(len(n["position"]) == 2 for n in doc["nodes"])
    # one sticky note per step around its calls; the calls are named under their step
    notes = [n for n in doc["nodes"] if n["type"] == "n8n-nodes-base.stickyNote"]
    assert len(notes) == 3 and "Mở màn hình" in notes[0]["name"] and notes[0]["parameters"]["width"] > 0
    assert http_nodes[0]["name"].startswith("Mở màn hình · 1/1 GET /tp/init")
    # a chain: every node but the last connects to the next (a sticky note takes no part)
    assert set(doc["connections"]) == set(names[:-1])
    assert all(doc["connections"][a]["main"][0][0]["node"] == b for a, b in zip(names, names[1:]))


def test_every_event_of_an_ie_session_sent_to_the_server_says_schema_3_like_the_session():
    """The server refuses a session whose events keep schema 2 while the session says 3 (found on real IE, Gate 9)."""
    from types import SimpleNamespace
    from rookie_agent.webui.core import Core
    document = {"engine": "ie", "events": [{"seq": 0, "schema_version": 2}, {"seq": 1, "schema_version": 2}],
                "requests": [{"after_seq": 1, "method": "post", "url": "http://x/api/cif?id=1", "status": 200, "ms": 12}]}
    events = Core._events_for_server(SimpleNamespace(_path_template=Core._path_template), document)
    assert [e["schema_version"] for e in events] == [3, 3]
    assert "api_calls" not in events[0] and events[1]["api_calls"] == [{"method": "POST", "path": "/api/cif", "status": 200, "ms": 12}]


def _login_first(api):
    """The first call made by the sign-in (Enter on Password), its answer feeding the next call (a session id)."""
    api[0]["step_id"] = "s2_password"
    return api


def test_a_value_from_the_sign_in_answer_is_taken_from_the_twins_fake_and_nothing_is_sent(monkeypatch):
    monkeypatch.setattr(replay, "_sign_in_steps", lambda workflow: {"s2_password"})
    result, controller, person, sent = twin_run(_login_first(nodes()[:3]))
    assert result["status"] == "finished" and sent == []
    assert [s["status"] for s in controller.steps] == ["skipped", "done", "done"]
    assert "không gửi gì" in controller.steps[0]["detail"]


def test_a_real_run_that_needs_the_sign_in_answer_stops_and_says_to_record_after_signing_in(monkeypatch):
    from rookie_agent.webui.run import WebController
    monkeypatch.setattr(replay, "_sign_in_steps", lambda workflow: {"s2_password"})
    stop, sent = threading.Event(), []
    controller = WebController(stop, {}, lambda: "")
    send = lambda *a: sent.append(a) or {"ok": True, "status": 200, "ms": 1, "text": "{}"}   # noqa: E731
    result = replay.run_api(flow(), _login_first(nodes()[:3]), {"cif": "9988776655"}, send, controller, stop)
    assert result["status"] == "needs_help" and sent == []
    assert "phiên làm việc" in result["message"] and "bấm Ghi" in result["message"] and "bản sao" in result["message"]      # plain words, with the ways out


# ---- the sign-in value taken from the live page (Gate 8, 6.4) ----------------------------------------------------------------------

def _session_node(body, name="l1"):
    return {"id": "a1", "step_id": "s3_find", "kind": "xhr", "label": "Mở màn hình → POST /touchpoint/TPClassLoader", "frame": "top",
            "method": "POST", "url": "http://h/touchpoint/TPClassLoader", "headers": "", "body": body, "risk": "read", "complete": True,
            "unresolved": [], "links": {name: {"from": "a0", "json": ["sid"]}}}


def _real_run(body, live, monkeypatch, name="l1", values=None):
    from rookie_agent.webui.run import WebController
    monkeypatch.setattr(replay, "_sign_in_steps", lambda workflow: {"s2_password"})
    login = {"id": "a0", "step_id": "s2_password", "kind": "xhr", "label": "Nhấn Enter ở «Password» → POST /touchpoint/TPClassLoader",
             "frame": "top", "method": "POST", "url": "http://h/touchpoint/TPClassLoader", "headers": "", "body": "x", "risk": "read",
             "complete": True, "unresolved": [], "links": {}}
    stop, sent, asked = threading.Event(), [], []
    controller = WebController(stop, {}, lambda: "")
    send = lambda node, url, headers, text: sent.append((url, headers, text)) or {"ok": True, "status": 200, "ms": 1, "text": "{}"}   # noqa: E731

    def peek(node):
        asked.append(node["id"])
        return live

    result = replay.run_api(flow(), [login, _session_node(body, name)], values or {}, send, controller, stop, peek=peek)
    return result, controller, sent, asked


def test_a_gwt_body_takes_the_session_from_the_page_s_newest_matching_body(monkeypatch):
    template = "7|0|5|http://h/touchpoint/|ABC123|⟦l1⟧|com.tp.Svc|run|1|2|3|4|"
    live = ["7|0|5|http://h/touchpoint/|ABC123|OLDSESSION|com.tp.Svc|run|1|2|3|4|",
            "unrelated body", "7|0|5|http://h/touchpoint/|ABC123|NEWSESSION9|com.tp.Svc|run|1|2|3|4|"]
    result, controller, sent, asked = _real_run(template, live, monkeypatch)
    assert result["status"] == "finished" and "NEWSESSION9" in sent[0][2] and "OLDSESSION" not in sent[0][2]
    assert controller.details["g2"]["inputs"] == [{"name": "l1", "from": "phiên đang mở của trang IE"}]


def test_a_form_body_and_a_template_with_two_marks_take_the_right_group(monkeypatch):
    result, _, sent, _ = _real_run("sid=⟦l1⟧&cif=⟦cif⟧&tab=1", ["sid=S%2B1x&cif=0123456789&tab=1"], monkeypatch, values={"cif": "99887766"})
    assert result["status"] == "finished" and sent[0][2] == "sid=S%2B1x&cif=99887766&tab=1"


def test_a_body_that_does_not_fit_the_template_stops_with_the_way_out_and_sends_nothing(monkeypatch):
    result, controller, sent, _ = _real_run("sid=⟦l1⟧&tab=1", ["other=1"], monkeypatch)
    assert result["status"] == "needs_help" and sent == []
    assert "Ghi rồi Dừng ngay một lần" in result["message"] and "phiên làm việc" in result["message"]
    result, _, sent, _ = _real_run("sid=⟦l1⟧&tab=1", [], monkeypatch)
    assert result["status"] == "needs_help" and sent == []


def test_the_value_taken_from_the_live_page_is_not_kept_in_the_audit_or_the_flow(monkeypatch):
    template = "sid=⟦l1⟧&tab=1"
    api = [_session_node(template)]
    result, controller, sent, _ = _real_run(template, ["sid=SECRETSESSION42&tab=1"], monkeypatch)
    assert "SECRETSESSION42" not in json.dumps(api) and "SECRETSESSION42" not in json.dumps(result)
    assert "SECRETSESSION42" not in json.dumps(controller.steps)   # the canvas detail (memory only) shows the sent body as it always did


# ---- one step is one node that fires its batch of calls ---------------------------------------------------------------------------

def test_one_duyet_asks_for_a_whole_step_not_for_each_of_its_calls():
    from test_replay import batch_nodes

    api = batch_nodes()
    for node in api:
        if node["group"] == "g3":
            node["risk"] = "write"
    result, controller, person, sent = twin_run(api, answers=[True])
    assert result["status"] == "finished" and len(person.asked) == 1 and person.asked[0]["step_id"] == "g3" and sent == []
    assert [r["status"] for r in controller.details["g3"]["requests"]] == [200, 200]
    assert [s["id"] for s in result["steps"]] == ["g1", "g2", "g3"]


def test_a_no_to_the_one_duyet_leaves_every_call_of_the_step_unsent():
    from test_replay import batch_nodes

    api = batch_nodes()
    for node in api:
        if node["group"] == "g3":
            node["risk"] = "money"
    result, controller, person, _ = twin_run(api, answers=[False])
    assert result["status"] == "stopped" and len(person.asked) == 1
    assert [r["state"] for r in controller.details["g3"]["requests"]] == ["chưa gửi", "chưa gửi"]


def test_a_checker_stage_asks_once_at_its_last_step_even_when_that_step_has_several_calls():
    from test_replay import batch_nodes

    result, controller, person, _ = twin_run(batch_nodes(), answers=[True], role="checker")
    assert result["status"] == "finished" and len(person.asked) == 1 and person.asked[0]["step_id"] == "g3"


def test_a_stage_of_a_flow_saved_before_groups_gets_its_groups_prefixed_and_the_steps_stay_one_node_each():
    from test_replay import batch_nodes

    old = batch_nodes()
    for node in old:
        node.pop("group"), node.pop("group_label")
    prefixed = twin.prefixed(old, "c1.", "Lập lệnh")
    assert [g["id"] for g in replay.groups_of(prefixed)] == ["c1.g1", "c1.g2", "c1.g3"]
    assert replay.groups_of(prefixed)[2]["label"] == "[Lập lệnh] s4_open" and len(replay.groups_of(prefixed)[2]["calls"]) == 2
