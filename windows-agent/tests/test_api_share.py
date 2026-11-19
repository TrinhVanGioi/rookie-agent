"""Task 10.3: the API nodes of a flow as the server may keep them. Only allowed fields; every piece of a template that looks like data is
masked on this PC (a customer name from an answer, a number, a date); the full templates stay on this PC."""

from __future__ import annotations

import json

from rookie_agent.ie import api_share


def node(**changes):
    base = {
        "id": "a3", "step_id": "s2", "group": "g2", "group_label": "Tra cứu", "label": "Tra cứu → POST /tp/rpc", "kind": "xhr", "via": "xhr",
        "frame": "0/1", "method": "POST", "url": "http://tp.local/tp/rpc?method=getToken&claims=cif", "ms": 120,
        "headers": "Authorization: Bearer ⟦l2⟧\r\nContent-Type: text/x-gwt-rpc; charset=utf-8", "body": "7|0|5|com.fis.tp.Service|find|⟦cif⟧|NGUYEN VAN AN|",
        "links": {"l2": {"from": "a2", "whole": True}}, "risk": "read", "complete": True, "unresolved": [],
        "answer": "//OK[1,'NGUYEN VAN AN','0123456789']", "shape": {"rows": 3},
    }
    base.update(changes)
    return base


def test_only_the_allowed_fields_go_and_never_the_recorded_answer():
    sent = api_share.for_server([node(extra="x")])[0]
    assert "answer" not in sent and "shape" not in sent and "extra" not in sent
    assert set(sent) <= set(api_share.FIELDS) | {"masked"}


def test_a_customer_name_a_number_and_a_date_in_a_template_are_masked_and_the_marks_and_names_of_services_stay():
    sent = api_share.for_server([node(body="7|0|6|com.fis.tp.Service|find|⟦cif⟧|NGUYEN VAN AN|0123456789|20/11/2026|", url="http://tp.local/khach/0012345678/xem?ten=Nguy%E1%BB%85n&page=2")])[0]
    assert "NGUYEN" not in sent["body"] and "0123456789" not in sent["body"] and "2026" not in sent["body"]
    assert "com.fis.tp.Service|find|⟦cif⟧|" in sent["body"]
    assert "0012345678" not in sent["url"] and "%E1" not in sent["url"] and "page=2" in sent["url"] and "/khach/" in sent["url"]
    assert sent["masked"] >= 5
    text = json.dumps(sent, ensure_ascii=False)
    for secret in ("NGUYEN", "0123456789", "0012345678"):
        assert secret not in text


def test_a_header_keeps_its_name_and_its_marks():
    sent = api_share.for_server([node()])[0]
    assert sent["headers"].startswith("Authorization: Bearer ⟦l2⟧")
    assert api_share.for_server([node(body="a|b|", url="http://tp.local/x")])[0]["masked"] == 0


def test_a_link_found_by_the_text_around_it_goes_without_that_text():
    sent = api_share.for_server([node(links={"l2": {"from": "a2", "before": "'NGUYEN VAN AN','", "after": "'"}, "l3": {"from": "a1", "json": ["data", 0, "token"]}})])[0]
    assert sent["links"]["l2"] == {"from": "a2", "text": True}
    assert sent["links"]["l3"] == {"from": "a1", "json": ["data", 0, "token"]}


def make_core(*a, **k):
    from test_webui import make_core as real    # sibling module (tests/ has no package: the server has one named `tests`)
    return real(*a, **k)


class Server:
    put: list = []
    fail = False

    def __init__(self, url):
        self.url = url

    def post_session(self, *a, **k):
        return {}

    def learn(self, workflow_id, session_ids, title=None, traces=None):
        return {"workflow": {"id": "tra-cuu", "version": 2, "title": title, "inputs": [], "steps": [
            {"id": "s2", "action": "click", "risk": "read", "mode": "auto", "target": {"label": "Tra cứu"}}]}, "warnings": []}

    def put_api(self, workflow_id, version, api):
        if Server.fail:
            from rookie_agent.server_client import ServerError
            raise ServerError("Không kết nối được máy chủ")
        Server.put.append((workflow_id, version, api))
        return {"count": len(api)}


def test_learning_sends_the_masked_nodes_and_keeps_the_full_ones_on_this_pc(tmp_path):
    from test_webui import record_one

    Server.put, Server.fail = [], False
    core, session = make_core(tmp_path, server_client=Server)
    record_one(core, session)
    core._api_for = lambda workflow, ids: [node()]
    ids = [r["id"] for r in core.store.listing()]
    status, reply = core.dispatch("POST", "/api/learn", {"ids": ids, "title": "Tra cứu"})
    assert status == 200, reply
    (flow_id, version, api), = Server.put
    assert (flow_id, version) == ("tra-cuu", 2) and "answer" not in api[0] and "NGUYEN" not in json.dumps(api, ensure_ascii=False)
    kept = core.store.get("flows")[0]["api"][0]
    assert "NGUYEN VAN AN" in kept["body"]                     # the full template stays here


def test_learning_still_works_when_the_nodes_cannot_be_sent(tmp_path):
    from test_webui import record_one

    Server.put, Server.fail = [], True
    core, session = make_core(tmp_path, server_client=Server)
    record_one(core, session)
    core._api_for = lambda workflow, ids: [node()]
    ids = [r["id"] for r in core.store.listing()]
    status, reply = core.dispatch("POST", "/api/learn", {"ids": ids, "title": "Tra cứu"})
    assert status == 200 and any("nút API" in w for w in reply["warnings"])


def test_the_same_samples_give_the_same_count_as_the_server_check():
    # the server checks with the same rule (server/app/api_nodes.py, test_api_nodes.py uses these samples)
    assert api_share.mask_text("a|NGUYEN VAN AN|b") == ("a|•••|b", 1)
    assert api_share.mask_text("x=⟦cif⟧&y=12345") == ("x=⟦cif⟧&y=•••", 1)
    assert api_share.mask_text("Bearer ⟦l2⟧") == ("Bearer ⟦l2⟧", 0)
    assert api_share.mask_text("q=Tr%E1%BA%A7n") == ("q=•••", 1)
