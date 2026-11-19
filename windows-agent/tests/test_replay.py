"""Gates 7 and 8: a recording's API calls become templates (typed values as marks, values from earlier answers as links), the learned
flow is a chain of API nodes, and a run sends them again with this run's values (fakes here; the page part runs on a real IE in
test_ie_real.py)."""

import json

import pytest
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


def test_a_typed_value_inside_a_longer_constant_is_left_alone():
    # task 11.2 (found on the TouchPoint look-alike): the account typed was part of the GWT strong name
    raw, events, requests = recorded()
    requests[1] = {**requests[1], "req": "7|0|6|http://tp/|B4D2C1A0F00D5EED0123456789ABCDEF|com.tp.Find|find|0123456789|CIF|"}
    body = replay.templates(raw, events, requests)[1]["body"]
    assert body == "7|0|6|http://tp/|B4D2C1A0F00D5EED0123456789ABCDEF|com.tp.Find|find|⟦e0⟧|⟦e1⟧|", body


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


def batch_nodes():
    """The same recording, but the last click fires two calls in a row (the second takes a value from the search answer, as TouchPoint calls do)."""
    raw, events, requests = recorded()
    requests = requests[:3] + [{"kind": "form", "frame": "main", "method": "POST", "url": "/tp/detail2", "status": 200, "req": "kh=KH00042&tab=2",
                                "res": "", "ms": 7, "after": {"t": T_OPEN}}]
    return replay.build_api(flow(), events, replay.templates(raw, events, requests))


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
    assert shown.details["g3"]["inputs"] == [{"name": "l1", "from": nodes()[1]["label"]}]
    assert shown.details["g3"]["requests"][0]["view"]["rows"] == [["Ten", "TRAN THI B"]]


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

        def last_requests(self, frame, path, timeout=30.0):
            return []

        def bind(self, tab_id, peek=False):
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
    assert [a["id"] for a in listed["api_nodes"]] == ["g1", "g2", "g3"] and listed["api_nodes"][2]["links"] == {"l1": "g2"}
    assert "xsrf_token" not in json.dumps(listed)                         # the page gets what is called, never a template's body
    status, reply = core.dispatch("POST", "/api/run/start", {"title": "Tra CIF", "mode": "simulate", "window": "ie-tab:1", "inputs": {"cif": "9988776655"}})
    assert status == 200, reply
    done = wait_for(core, "finished")
    assert Bridge.sent[1] == '7|0|5|find|CIF|9988776655|xsrf_token="NEWTOKEN77"|'
    assert done["details"]["g3"]["requests"][0]["status"] == 200
    core._run["thread"].join(5)
    audit = (core.store.home / "audit.jsonl").read_text(encoding="utf-8")
    assert "9988776655" not in audit and "TRAN THI B" not in audit and "NEWTOKEN77" not in audit


class CountingBridge:
    """A signed-in IE tab that answers like the fake TouchPoint above and counts what it was asked."""

    def __init__(self, answers=None):
        self.sent, self.open_tabs, self.answers = [], [{"id": 1, "title": "TouchPoint", "host": "tp.example"}], answers or ANSWERS

    def tabs(self):
        return list(self.open_tabs)

    def last_requests(self, frame, path, timeout=30.0):
        return []

    def bind(self, tab_id, peek=False):
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
    assert "bộ nhớ phiên" in done["result"]["message"] and done["details"]["g3"]["requests"][0]["view"]["rows"] == [["Ten", "TRAN THI B"]]
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


# ---- TouchPoint: a token service answers a bearer token, the service call carries it in its Authorization header ----------------

JWT1 = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1MSIsImV4cCI6MTc5OTk5OTk5OX0.c2lnbmF0dXJlMQ"
JWT2 = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1MSIsImV4cCI6MTc5OTk5OTk5OX0.c2lnbmF0dXJlMg"


def _two_step(answer1, header_value=None):
    token_call = {"t": 1, "frame": "top", "method": "POST", "url": "http://h/touchpoint/postAuthentication.fisglobal?method=getToken&claims=QWJj", "status": 200, "ms": 5,
                  "req": "", "res": answer1, "hdr": "", "kind": "xhr", "after": None}
    service = {"t": 2, "frame": "top", "method": "POST", "url": "http://h/touchpoint/TPClassLoader", "status": 200, "ms": 5,
               "req": "methodName=a&className=b", "res": "<r/>", "kind": "xhr", "after": None,
               "hdr": "Authorization:Bearer " + (header_value or JWT1) + "\nContent-Type:application/x-www-form-urlencoded;text/xml;charset=utf-8\nMACHINE_NAME:PC7\n"}
    return [token_call, service]


@pytest.mark.parametrize("answer", ["\n  " + JWT1 + "  \n", json.dumps({"token": JWT1})])
def test_a_bearer_token_in_a_header_is_linked_to_the_token_answer_and_never_kept(answer):
    found = replay.templates([], [], _two_step(answer))
    assert "Authorization:Bearer ⟦l1⟧" in found[1]["headers"] and JWT1 not in json.dumps(found) and found[1]["complete"]
    assert "MACHINE_NAME:PC7" in found[1]["headers"] and "Cookie" not in found[1]["headers"]
    value = replay.take_value(answer, found[1]["links"]["l1"])
    assert value == JWT1
    # the next run: a fresh token goes into the header
    fresh = "  " + JWT2 + "\n" if not answer.startswith("{") else json.dumps({"token": JWT2})
    headers, missing = replay.fill_in(found[1]["headers"], {"l1": replay.take_value(fresh, found[1]["links"]["l1"])})
    assert "Bearer " + JWT2 in headers and not missing


def test_a_bearer_token_no_answer_explains_is_hidden_and_the_call_is_not_complete():
    found = replay.templates([], [], _two_step("something else entirely 12345"))
    assert JWT1 not in json.dumps(found) and "Authorization:***" in found[1]["headers"] and found[1]["complete"] is False


def test_identical_token_calls_repeated_are_kept_when_a_later_call_links_to_them():
    request = _two_step(JWT1)
    calls = [dict(request[0], t=i, res=JWT1 if i == 3 else "x" + str(i) * 20) for i in range(1, 4)]    # the same URL three times: the page polling
    service = dict(request[1], t=4)
    found = replay.templates([], [], calls + [service])
    api = replay.build_api({"steps": [], "inputs": []}, [], found)
    assert [n["id"] for n in api] == ["a2", "a3"] and api[1]["links"]["l1"]["from"] == "a2"


# ---- one step is one node that fires its batch of calls (docs/design.md 6.4) -------------------------------------------------------

def test_consecutive_calls_of_one_step_form_one_group_and_the_screen_opening_is_its_own():
    api = batch_nodes()
    assert [(n["id"], n["group"]) for n in api] == [("a0", "g1"), ("a1", "g2"), ("a2", "g3"), ("a3", "g3")]
    groups = replay.groups_of(api)
    assert [g["id"] for g in groups] == ["g1", "g2", "g3"]
    assert [g["label"] for g in groups] == ["Mở màn hình", "s3_find", "s4_open"]       # the name of the step: no "-> POST path"
    assert groups[2]["calls"] == ["a2", "a3"] and groups[2]["step_id"] == "s4_open" and groups[2]["risk"] == "read"
    assert groups[2]["ms"] == sum(n["ms"] for n in api[2:]) and "→" not in json.dumps(groups, ensure_ascii=False)


def test_a_flow_saved_before_groups_existed_is_grouped_the_same_way_when_it_is_loaded():
    api = batch_nodes()
    expected = replay.groups_of(api)
    for node in api:
        node.pop("group"), node.pop("group_label")
    assert replay.groups_of(api) == expected


def test_a_run_fires_the_batch_of_a_step_in_order_and_links_still_reach_across_steps():
    sent, shown = [], Shown()

    def send(node, url, headers, body):
        sent.append(url)
        return {"ok": True, "status": 200, "ms": 4, "text": ANSWERS.get(url, "")}

    result = replay.run_api(flow(), batch_nodes(), {"cif": "9988776655"}, send, shown, threading.Event())
    assert result["status"] == "finished" and sent == ["/tp/init", "/tp/find", "/tp/detail", "/tp/detail2"]
    assert [s["id"] for s in result["steps"]] == ["g1", "g2", "g3"]
    assert [s for s in shown.steps if s[1] == "done"] == [("g1", "done"), ("g2", "done"), ("g3", "done")]
    calls = shown.details["g3"]["requests"]
    assert [(c["url"], c["status"], c["ms"]) for c in calls] == [("/tp/detail", 200, 4), ("/tp/detail2", 200, 4)]
    assert calls[1]["body"] == "kh=KH00099&tab=2"                       # from the search answer, a step before
    assert shown.details["g3"]["action"] == "s4_open" and result["steps"][2]["detail"] == "2 lời gọi · 8 ms"


def test_a_step_that_writes_is_refused_once_with_its_planned_calls_listed():
    api = batch_nodes()
    for node in api:
        if node["group"] == "g3":
            node["risk"] = "write"
    sent, shown = [], Shown()
    result = replay.run_api(flow(), api, {"cif": "1"}, lambda n, u, h, b: sent.append(u) or {"ok": True, "status": 200, "ms": 1, "text": ANSWERS.get(u, "")},
                            shown, threading.Event())
    assert result["status"] == "refused" and sent == ["/tp/init", "/tp/find"] and "«s4_open»" in result["message"]
    assert [s for s in result["steps"] if s["status"] == "refused"] == [{"id": "g3", "status": "refused", "detail": "ghi dữ liệu hoặc tiền: không gửi bằng request"}]
    assert [(c["method"], c["url"], c["state"]) for c in shown.details["g3"]["requests"]] == [("POST", "/tp/detail", "chưa gửi"), ("POST", "/tp/detail2", "chưa gửi")]


def test_a_failure_inside_a_step_names_the_step_and_the_call_and_the_rest_stays_unsent():
    def send(node, url, headers, body):
        if url == "/tp/detail":
            return {"ok": True, "status": 200, "ms": 1, "text": "<html><input type=password></html>"}   # the sign-in page: the session ended
        return {"ok": True, "status": 200, "ms": 1, "text": ANSWERS.get(url, "")}

    shown = Shown()
    result = replay.run_api(flow(), batch_nodes(), {"cif": "1"}, send, shown, threading.Event())
    assert result["status"] == "needs_help" and "«s4_open»" in result["message"] and "POST /tp/detail:" in result["message"]
    calls = shown.details["g3"]["requests"]
    assert calls[0]["error"] and calls[1] == {"method": "POST", "url": "/tp/detail2", "state": "chưa gửi"}

    def broken(node, url, headers, body):
        return {"ok": False, "error": "timeout"} if url == "/tp/detail2" else {"ok": True, "status": 200, "ms": 1, "text": ANSWERS.get(url, "")}

    result = replay.run_api(flow(), batch_nodes(), {"cif": "1"}, broken, Shown(), threading.Event())
    assert result["status"] == "failed" and "«s4_open»" in result["message"] and "POST /tp/detail2" in result["message"]


def test_the_flows_list_draws_one_node_per_step_with_its_calls(tmp_path):
    from test_webui import make_core

    core, _ = make_core(tmp_path)
    core.store.put("flows", [{"title": "Tra CIF", "steps": [], "inputs": ["Số CIF"], "learned_at": "x",
                              "workflow": {**flow(), "engine": "ie", "status": "draft"}, "api": batch_nodes()}])
    nodes_ = core.dispatch("GET", "/api/flows", {})[1]["flows"][0]["api_nodes"]
    assert [(n["id"], n["call_count"]) for n in nodes_] == [("g1", 1), ("g2", 1), ("g3", 2)]
    assert [c["name"] for c in nodes_[2]["calls"]] == ["POST /tp/detail", "POST /tp/detail2"] and nodes_[2]["links"] == {"l1": "g2"}


# ---- a step that is write only by default: the teller is asked once «chỉ xem?» (docs/design.md 6.4 point 4) -----------------------------

from rookie_agent.ie import read_rules  # noqa: E402

RULES = read_rules.load()


class Asking(Shown):
    def __init__(self, answer):
        super().__init__()
        self.answer, self.asked = answer, []

    def confirm_read(self, step, index, total, calls):
        self.asked.append((step["id"], [c["name"] for c in calls]))
        return self.answer


def unknown_click(label="Khách hàng X", risk="write"):
    """The flow whose last click is a button no rule names, so the server gave it write; its two calls are the group g3."""
    wf = flow()
    wf["steps"][3] = {**wf["steps"][3], "risk": risk, "target": {**wf["steps"][3]["target"], "label": label, "tag": "button"}}
    api = batch_nodes()
    for node in api:
        if node["group"] == "g3":
            node["risk"] = risk
    return wf, api


def run_it(wf, api, ctl, **kw):
    sent = []
    result = replay.run_api(wf, api, {"cif": "1"}, lambda n, u, h, b: sent.append(u) or {"ok": True, "status": 200, "ms": 1, "text": ANSWERS.get(u, "")},
                            ctl, threading.Event(), **kw)
    return result, sent


def test_the_rules_are_readable_from_the_package_layout():
    assert RULES is not None and RULES["default_click"] == "write"
    assert read_rules.load(read_rules.RULES_PATH.parent / "nope.json") is None


def test_an_unknown_button_asks_once_then_remembers_and_the_next_run_sends_without_asking():
    wf, api = unknown_click()
    kept, ctl = {}, Asking(True)
    result, sent = run_it(wf, api, ctl, read_rules=RULES, confirmed=kept, remember=lambda sid: kept.update({sid: {"at": "t"}}))
    assert result["status"] == "finished" and sent[-2:] == ["/tp/detail", "/tp/detail2"]
    assert ctl.asked == [("s4_open", ["POST /tp/detail", "POST /tp/detail2"])] and kept == {"s4_open": {"at": "t"}}
    again = Asking(False)
    result, sent = run_it(wf, api, again, read_rules=RULES, confirmed=kept)
    assert result["status"] == "finished" and again.asked == [] and len(sent) == 4


def test_has_changes_refuses_with_nothing_sent_and_nothing_remembered():
    wf, api = unknown_click()
    kept, ctl = {}, Asking(False)
    result, sent = run_it(wf, api, ctl, read_rules=RULES, confirmed=kept, remember=lambda sid: kept.update({sid: {}}))
    assert result["status"] == "refused" and sent == ["/tp/init", "/tp/find"] and kept == {} and len(ctl.asked) == 1


def test_an_explicit_write_label_money_and_a_missing_rule_table_are_never_asked():
    for label, risk, rules in (("Lưu", "write", RULES), ("Khách hàng X", "money", RULES), ("Khách hàng X", "write", None)):
        wf, api = unknown_click(label, risk)
        ctl = Asking(True)
        result, sent = run_it(wf, api, ctl, read_rules=rules, confirmed={})
        assert result["status"] == "refused" and ctl.asked == [] and sent == ["/tp/init", "/tp/find"], (label, risk)
    wf, api = unknown_click()
    assert replay.run_api(wf, api, {"cif": "1"}, lambda n, u, h, b: {"ok": True, "status": 200, "ms": 1, "text": ANSWERS.get(u, "")}, Shown(),
                          threading.Event(), read_rules=RULES)["status"] == "refused"          # a controller that cannot ask


def test_twin_is_unchanged_it_still_waits_for_duyet_and_never_asks_read_only():
    wf, api = unknown_click()

    class Twin(Asking):
        def approve(self, step, index, total):
            self.asked.append("approve")
            return True

    ctl = Twin(True)
    replay.run_api(wf, api, {"cif": "1"}, lambda n, u, h, b: {"ok": True, "status": 200, "ms": 1, "text": ANSWERS.get(u, "")}, ctl, threading.Event(),
                   twin=True, read_rules=RULES)
    assert ctl.asked == ["approve"]


def test_the_flows_page_shows_the_confirmation_and_withdrawing_brings_the_question_back(tmp_path):
    from test_webui import make_core, wait_for

    wf, api = unknown_click()
    bridge = CountingBridge()
    core, _ = make_core(tmp_path, ie_bridge=lambda: bridge)
    core.store.put("flows", [{"title": "Tra CIF", "steps": [], "inputs": ["Số CIF"], "learned_at": "x",
                              "workflow": {**wf, "engine": "ie", "status": "approved"}, "api": api}])
    node = core.dispatch("GET", "/api/flows", {})[1]["flows"][0]["api_nodes"][2]
    assert node["asks_read"] is True and node["read_confirmed"] is None
    start = {"title": "Tra CIF", "mode": "simulate", "window": "ie-tab:1", "inputs": {"cif": "1"}}
    assert core.dispatch("POST", "/api/run/start", start)[0] == 200
    asked = wait_for(core, "waiting_review")["ask"]
    assert asked["kind"] == "confirm_read" and "chỉ xem dữ liệu" in asked["question"] and [c["name"] for c in asked["calls"]] == ["POST /tp/detail", "POST /tp/detail2"]
    assert core.dispatch("POST", "/api/run/decide", {"ask_id": asked["id"], "approve": True})[0] == 200
    wait_for(core, "finished")
    core._run["thread"].join(5)
    listed = core.dispatch("GET", "/api/flows", {})[1]["flows"][0]
    assert listed["api_nodes"][2]["read_confirmed"] and "read_confirmed" not in listed and len(bridge.sent) == 4
    assert core.dispatch("POST", "/api/run/start", {**start, "refresh": True})[0] == 200
    wait_for(core, "finished")                                               # remembered: no question
    core._run["thread"].join(5)
    assert core.dispatch("POST", "/api/flow/read-withdraw", {"title": "Tra CIF", "step_id": "s4_open"})[0] == 200
    assert core.dispatch("GET", "/api/flows", {})[1]["flows"][0]["api_nodes"][2]["read_confirmed"] is None
    assert core.dispatch("POST", "/api/run/start", {**start, "refresh": True})[0] == 200
    assert wait_for(core, "waiting_review")["ask"]["kind"] == "confirm_read"
    core.dispatch("POST", "/api/run/stop", {})
    core._run["thread"].join(5)
    assert "s4_open" not in json.dumps(core.store.get("flows")[0].get("read_confirmed") or {})
    assert "TRAN THI B" not in (core.store.home / "audit.jsonl").read_text(encoding="utf-8")
