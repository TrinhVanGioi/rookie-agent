"""Gates 7 and 8: a recording's API calls become templates (typed values as marks, values from earlier answers as links), the learned
flow is a chain of API nodes, and a run sends them again with this run's values (fakes here; the page part runs on a real IE in
test_ie_real.py)."""

import json
import threading

from rookie_agent.ie import replay, response_view
from rookie_agent.ie.recorder import _iso

T_FILL, T_KIND, T_FIND, T_OPEN = 1_700_000_000_000, 1_700_000_001_000, 1_700_000_002_000, 1_700_000_003_000
SEL_CIF, SEL_KIND, SEL_FIND, SEL_OPEN = "frame=main|id=txtCustAcctNumber", "frame=main|id=cboKind", "frame=main|id=btnFind", "frame=main|id=lnkOpen"
TOKEN = "XT9f8e7d6c5b4a3"


def recorded():
    raw = [{"kind": "input", "t": T_FILL, "value": "0123456789"}, {"kind": "select", "t": T_KIND, "value": "CIF"},
           {"kind": "click", "t": T_FIND}, {"kind": "click", "t": T_OPEN}]
    events = [{"seq": 0, "ts": _iso(T_FILL), "type": "input", "target": {"selectors": [SEL_CIF]}},
              {"seq": 1, "ts": _iso(T_KIND), "type": "select", "target": {"selectors": [SEL_KIND]}},
              {"seq": 2, "ts": _iso(T_FIND), "type": "click", "target": {"selectors": [SEL_FIND]}},
              {"seq": 3, "ts": _iso(T_OPEN), "type": "click", "target": {"selectors": [SEL_OPEN]}}]
    requests = [
        # 0: the screen opening gives an anti-forgery token (before any action)
        {"kind": "xhr", "frame": "main", "method": "GET", "url": "/tp/init", "status": 200, "req": "", "res": json.dumps({"xsrf": TOKEN}), "after": None},
        # 1: the search: the typed customer id and the token from 0
        {"kind": "xhr", "frame": "main", "method": "POST", "url": "/tp/find", "status": 200, "hdr": "X-GWT-Permutation:ABC\n",
         "req": f'7|0|5|find|CIF|0123456789|xsrf_token="{TOKEN}"|', "res": '//OK[1,["NGUYEN VAN A","KH00042","com.tp.Customer/123"],0,7]',
         "after": {"t": T_FIND}},
        # 2: the detail: the customer number that the search answered
        {"kind": "form", "frame": "main", "method": "POST", "url": "/tp/detail", "status": 200, "req": "kh=KH00042&tab=1", "res": "", "after": {"t": T_OPEN}},
        # 3: a password typed in a form: never sent again
        {"kind": "form", "frame": "main", "method": "POST", "url": "/tp/login", "status": 200, "req": "pw=***", "res": "", "after": {"t": T_OPEN}},
    ]
    return raw, events, requests


def flow():
    return {"inputs": [{"name": "cif", "label": "Số CIF"}],
            "steps": [{"id": "s1_cif", "action": "fill", "value": "{cif}", "target": {"selectors": [SEL_CIF]}, "risk": "read"},
                      {"id": "s2_kind", "action": "select", "value": "CIF", "target": {"selectors": [SEL_KIND]}, "risk": "read"},
                      {"id": "s3_find", "action": "click", "target": {"selectors": [SEL_FIND]}, "risk": "read"},
                      {"id": "s4_open", "action": "click", "target": {"selectors": [SEL_OPEN]}, "risk": "read"}]}


def nodes():
    raw, events, requests = recorded()
    return replay.build_api(flow(), events, replay.templates(raw, events, requests))


def test_typed_values_are_marks_values_from_earlier_answers_are_links_and_none_is_kept():
    found = replay.templates(*recorded())
    text = json.dumps(found)
    assert "0123456789" not in text and TOKEN not in text and "KH00042" not in text
    assert found[1]["body"] == '7|0|5|find|⟦e1⟧|⟦e0⟧|xsrf_token="⟦l1⟧"|' and found[1]["complete"]
    assert found[1]["links"]["l1"] == {"from": 0, "json": ["xsrf"]}
    assert found[2]["links"]["l1"] == {"from": 1, "gwt": 1} and found[2]["body"] == "kh=⟦l1⟧&tab=1"
    assert found[3]["complete"] is False


def test_a_token_no_answer_explains_is_hidden_and_the_request_cannot_be_sent_again():
    raw, events, requests = recorded()
    requests[0]["res"] = "{}"
    found = replay.templates(raw, events, requests)
    assert TOKEN not in json.dumps(found) and found[1]["complete"] is False


def test_the_flow_is_the_api_calls_in_order_named_after_the_action_that_made_them():
    api = nodes()
    assert [n["id"] for n in api] == ["a0", "a1", "a2", "a3"]
    assert api[0]["label"].startswith("Mở màn hình → GET /tp/init") and api[1]["step_id"] == "s3_find"
    assert api[1]["body"] == '7|0|5|find|CIF|⟦cif⟧|xsrf_token="⟦l1⟧"|' and api[1]["links"]["l1"]["from"] == "a0"
    assert api[2]["links"]["l1"] == {"from": "a1", "gwt": 1} and api[2]["kind"] == "form" and api[2]["unresolved"] == []


class Shown:
    def __init__(self):
        self.steps, self.details = [], {}

    def progress(self, step_id, status, detail):
        self.steps.append((step_id, status))

    def show(self, step_id, shown):
        self.details[step_id] = shown


ANSWERS = {"/tp/init": json.dumps({"xsrf": "NEWTOKEN77"}), "/tp/find": '//OK[1,["TRAN THI B","KH00099","com.tp.Customer/123"],0,7]',
           "/tp/detail": "<html><table><tr><td>Ten</td><td>TRAN THI B</td></tr></table></html>"}


def test_a_run_sends_the_new_value_and_carries_what_each_answer_gives_to_the_next_call():
    sent, shown = [], Shown()

    def send(node, url, headers, body):
        sent.append((url, body))
        return {"ok": True, "status": 200, "ms": 9, "text": ANSWERS.get(url, "")}

    result = replay.run_api(flow(), nodes()[:3], {"cif": "9988776655"}, send, shown, threading.Event())
    assert result["status"] == "finished", result
    assert sent == [("/tp/init", ""), ("/tp/find", '7|0|5|find|CIF|9988776655|xsrf_token="NEWTOKEN77"|'), ("/tp/detail", "kh=KH00099&tab=1")]
    assert shown.details["a2"]["inputs"] == [{"name": "l1", "from": nodes()[1]["label"]}]
    assert shown.details["a2"]["requests"][0]["view"]["rows"] == [["Ten", "TRAN THI B"]]


def test_a_value_missing_from_the_new_answer_stops_and_asks_never_guesses():
    answers = {**ANSWERS, "/tp/init": "{}"}
    result = replay.run_api(flow(), nodes()[:3], {"cif": "1"}, lambda n, u, h, b: {"ok": True, "status": 200, "ms": 1, "text": answers.get(u, "")},
                            Shown(), threading.Event())
    assert result["status"] == "needs_help" and "không lấy được" in result["message"]


def test_a_password_request_a_write_node_and_a_refused_answer_stop_the_run():
    def answer(n, u, h, b):
        return {"ok": True, "status": 200, "ms": 1, "text": ANSWERS.get(u, "")}

    assert replay.run_api(flow(), nodes(), {"cif": "1"}, answer, Shown(), threading.Event())["status"] == "needs_help"   # a3: the password
    writing = nodes()[:2]
    writing[1]["risk"] = "write"
    sent = []
    result = replay.run_api(flow(), writing, {"cif": "1"}, lambda *a: sent.append(a) or answer(*a), Shown(), threading.Event())
    assert result["status"] == "refused" and len(sent) == 1                  # only the screen opening went
    result = replay.run_api(flow(), nodes()[:2], {"cif": "1"}, lambda n, u, h, b: {"ok": True, "status": 200, "ms": 1, "text": "//EX[2,0]"
                            if u == "/tp/find" else ANSWERS[u]}, Shown(), threading.Event())
    assert result["status"] == "needs_help" and "//EX" in result["message"]


def test_the_sign_in_is_never_replayed():
    steps = [{"id": "s0_user", "action": "fill", "value": "{user}", "target": {"selectors": ["frame=top|id=txtUser"]}, "risk": "read"},
             {"id": "s0_pw", "action": "submit", "target": {"selectors": ["frame=top|id=txtPassword"]}, "risk": "read"}] + flow()["steps"]
    login = {"id": "a9", "step_id": "s0_pw", "label": "login", "risk": "read", "method": "POST", "url": "/login", "body": "pw=***", "headers": "",
             "links": {}, "complete": False, "unresolved": [], "frame": "top", "kind": "form"}
    sent = []
    result = replay.run_api({"steps": steps}, [login] + nodes()[:1], {}, lambda n, u, h, b: sent.append(u) or {"ok": True, "status": 200, "ms": 1, "text": "{}"},
                            Shown(), threading.Event())
    assert result["status"] == "finished" and sent == ["/tp/init"]


def test_answers_are_made_short_to_read():
    j = response_view.summarize('{"customer": {"name": "A", "cif": "1"}, "accounts": [{"no": "11", "bal": 5}, {"no": "12", "bal": 6}]}')
    assert ["customer.name", "A"] in j["pairs"] and j["rows"][0] == ["no", "bal"] and len(j["rows"]) == 3
    h = response_view.summarize("<html><body><p>Ket qua</p><table><tr><td>CIF</td><td>123</td></tr></table><script>x()</script></body></html>")
    assert h["rows"] == [["CIF", "123"]] and h["lines"] == ["Ket qua"]
    assert response_view.summarize("//EX[1]")["lines"][0].startswith("Máy chủ báo lỗi")


def test_the_flow_tab_draws_the_api_nodes_and_runs_them(tmp_path):
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
            if frame != "top":
                return {"ok": False, "error": "no_frame"}           # the recorded frame is named differently now: the top page sends
            Bridge.sent.append(body)
            return {"ok": True, "status": 200, "ms": 5, "text": ANSWERS.get(url, "")}

    core, _ = make_core(tmp_path, ie_bridge=lambda: Bridge())
    core.store.put("flows", [{"title": "Tra CIF", "steps": [], "inputs": ["Số CIF"], "learned_at": "x",
                              "workflow": {**flow(), "engine": "ie", "status": "draft"}, "api": nodes()[:3]}])
    listed = core.dispatch("GET", "/api/flows", {})[1]["flows"][0]
    assert [a["id"] for a in listed["api_nodes"]] == ["a0", "a1", "a2"] and listed["api_nodes"][2]["links"] == {"l1": "a1"}
    assert "xsrf_token" not in json.dumps(listed)                         # the page gets what is called, never a template's body
    status, reply = core.dispatch("POST", "/api/run/start", {"title": "Tra CIF", "mode": "simulate", "window": "ie-tab:1", "inputs": {"cif": "9988776655"}})
    assert status == 200, reply
    done = wait_for(core, "finished")
    assert Bridge.sent[1] == '7|0|5|find|CIF|9988776655|xsrf_token="NEWTOKEN77"|'
    assert done["details"]["a2"]["requests"][0]["status"] == 200
    core._run["thread"].join(5)
    audit = (core.store.home / "audit.jsonl").read_text(encoding="utf-8")
    assert "9988776655" not in audit and "TRAN THI B" not in audit and "NEWTOKEN77" not in audit


class CountingBridge:
    """A signed-in IE tab that answers like the fake TouchPoint above and counts what it was asked."""

    def __init__(self, answers=None):
        self.sent, self.open_tabs, self.answers = [], [{"id": 1, "title": "TouchPoint", "host": "tp.example"}], answers or ANSWERS

    def tabs(self):
        return list(self.open_tabs)

    def bind(self, tab_id):
        return {"ok": True}

    def unbind(self):
        return {"ok": True}

    def send(self, frame, method, url, headers, body):
        self.sent.append(url)
        return {"ok": True, "status": 200, "ms": 5, "text": self.answers.get(url, "")}


def cache_core(tmp_path, bridge, api=None):
    from test_webui import make_core

    core, _ = make_core(tmp_path, ie_bridge=lambda: bridge)
    core.store.put("flows", [{"title": "Tra CIF", "steps": [], "inputs": ["Số CIF"], "learned_at": "x",
                              "workflow": {**flow(), "engine": "ie", "status": "approved"}, "api": api or nodes()[:3]}])
    return core


def look_up(core, cif, **extra):
    from test_webui import wait_for

    status, reply = core.dispatch("POST", "/api/run/start", {"title": "Tra CIF", "mode": "simulate", "window": "ie-tab:1", "inputs": {"cif": cif}, **extra})
    assert status == 200, reply
    done = wait_for(core, "finished") if not reply.get("cached") else core.dispatch("GET", "/api/run/status", {})[1]
    core._run["thread"].join(5)
    return reply, done


def test_the_same_customer_again_in_the_session_comes_from_memory_and_another_one_calls_the_server(tmp_path):
    bridge = CountingBridge()
    core = cache_core(tmp_path, bridge)
    look_up(core, "9988776655")
    assert len(bridge.sent) == 3
    reply, done = look_up(core, "9988776655")
    assert reply["cached"] and len(bridge.sent) == 3                          # nothing was asked of the server
    assert "bộ nhớ phiên" in done["result"]["message"] and done["details"]["a2"]["requests"][0]["view"]["rows"] == [["Ten", "TRAN THI B"]]
    look_up(core, "9988776655", refresh=True)                                 # «Làm mới»: the server is asked again
    assert len(bridge.sent) == 6
    look_up(core, "1122334455")                                                # another customer
    assert len(bridge.sent) == 9
    assert core.dispatch("GET", "/api/cache", {})[1] == {"kept": 2, "seconds": 300}
    audit = (core.store.home / "audit.jsonl").read_text(encoding="utf-8")
    assert "9988776655" not in audit and "TRAN THI B" not in audit


def test_the_session_memory_ends_with_the_tab_a_sign_in_page_the_button_or_its_time(tmp_path):
    bridge = CountingBridge()
    core = cache_core(tmp_path, bridge)
    look_up(core, "9988776655")
    assert core.dispatch("POST", "/api/cache/clear", {})[1] == {"cleared": 1}
    look_up(core, "9988776655")
    assert len(bridge.sent) == 6                                               # asked again after «Xoá bộ nhớ phiên»
    bridge.open_tabs = [{"id": 2, "title": "TouchPoint", "host": "tp.example"}]   # the tab of that sign-in was closed
    core._cache_prune(bridge)
    assert core.dispatch("GET", "/api/cache", {})[1]["kept"] == 0
    bridge.open_tabs = [{"id": 1, "title": "TouchPoint", "host": "tp.example"}]
    look_up(core, "9988776655")
    core.store.put("cache_seconds", 0)                                         # its time is up
    look_up(core, "9988776655")
    assert len(bridge.sent) == 12
    core.store.put("cache_seconds", 300)
    bridge.answers = {**ANSWERS, "/tp/find": "<html><input type=password name=pw></html>"}   # the session has ended: a sign-in page
    status, _ = core.dispatch("POST", "/api/run/start", {"title": "Tra CIF", "mode": "simulate", "window": "ie-tab:1", "inputs": {"cif": "9988776655"}, "refresh": True})
    from test_webui import wait_for
    wait_for(core, "needs_help")
    core._run["thread"].join(5)
    assert core.dispatch("GET", "/api/cache", {})[1]["kept"] == 0              # nothing of that session is kept


def test_a_run_that_stops_at_a_write_call_is_never_kept(tmp_path):
    api = nodes()[:3]
    api[2]["risk"] = "write"
    bridge = CountingBridge()
    core = cache_core(tmp_path, bridge, api)
    status, _ = core.dispatch("POST", "/api/run/start", {"title": "Tra CIF", "mode": "simulate", "window": "ie-tab:1", "inputs": {"cif": "1"}})
    from test_webui import wait_for
    wait_for(core, "refused")
    core._run["thread"].join(5)
    assert core.dispatch("GET", "/api/cache", {})[1]["kept"] == 0 and len(bridge.sent) == 2


def test_the_assistant_runs_a_read_only_look_up_by_its_api_calls_and_anything_else_on_the_screen(tmp_path):
    bridge = CountingBridge()
    core = cache_core(tmp_path, bridge)
    started = []
    core.run_start = lambda body, via=None: started.append((body["mode"], via)) or {"started": True}

    class Plans:
        def take(self, plan_id):
            return ("Tra CIF", {"cif": "1"})

    core._assistant = lambda: Plans()
    core.assistant_run({"plan_id": "p1", "window": "ie-tab:1"})
    flows = core.store.get("flows")
    flows[0]["api"][1]["risk"] = "write"
    core.store.put("flows", flows)
    core.assistant_run({"plan_id": "p2", "window": "ie-tab:1"})
    assert started == [("simulate", "assistant"), ("run", "assistant")]
