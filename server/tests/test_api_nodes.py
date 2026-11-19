"""Task 10.3: the API nodes of a flow on the server: allowed fields only, no template piece that looks like data, digest of their own."""

from __future__ import annotations

import hashlib
import json

from app import api_nodes
from tests.helpers import java_transfer_session, payload


def learn(client):
    ids = []
    for i in range(3):
        client.post("/sessions", json=payload(f"s-{i}", java_transfer_session(f"s-{i}")))
        ids.append(f"s-{i}")
    return client.post("/workflows/learn", json={"title": "Tra cứu", "session_ids": ids}).json()["workflow"]["id"]


NODES = [
    {"id": "a1", "step_id": None, "group": "g1", "group_label": "Mở màn hình", "label": "Mở màn hình → GET /tp/token", "kind": "xhr", "via": "xhr",
     "method": "GET", "url": "http://tp.local/tp/token?method=getToken", "headers": "", "body": "", "links": {}, "risk": "read",
     "complete": True, "unresolved": [], "ms": 40, "masked": 0},
    {"id": "a2", "step_id": "s2", "group": "g2", "group_label": "Tra cứu", "label": "Tra cứu → POST /tp/rpc", "kind": "xhr", "via": "xhr",
     "method": "POST", "url": "http://tp.local/tp/rpc", "headers": "Authorization: Bearer ⟦l1⟧", "body": "7|0|4|com.fis.tp.Service|find|⟦cif⟧|•••|",
     "links": {"l1": {"from": "a1", "whole": True}}, "risk": "read", "complete": True, "unresolved": [], "ms": 90, "masked": 1},
]


def test_the_owner_sends_the_nodes_and_every_version_serves_them_with_a_digest_of_their_own(client):
    flow = learn(client)
    reply = client.put(f"/workflows/{flow}/versions/1/api", json={"api": NODES})
    assert reply.status_code == 200, reply.text
    got = client.get(f"/workflows/{flow}/versions/1").json()
    canonical = json.dumps(NODES, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert got["api"] == NODES and got["api_digest"] == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert "api" not in client.get(f"/workflows/{flow}/versions/1").json()["workflow"]       # the workflow itself is unchanged


def test_a_field_that_is_not_allowed_is_refused(client):
    flow = learn(client)
    for change in ({"answer": "//OK[1,'NGUYEN VAN AN']"}, {"shape": {}}, {"cookie": "x"}):
        reply = client.put(f"/workflows/{flow}/versions/1/api", json={"api": [{**NODES[0], **change}]})
        assert reply.status_code == 422


def test_a_template_piece_that_looks_like_data_is_refused(client):
    flow = learn(client)
    for change in ({"body": "a|NGUYEN VAN AN|"}, {"url": "http://tp.local/khach/0012345678"}, {"headers": "X-Ten: Trần"},
                   {"body": "q=Tr%E1%BA%A7n"}):
        reply = client.put(f"/workflows/{flow}/versions/1/api", json={"api": [{**NODES[0], **change}]})
        assert reply.status_code == 422 and "giống dữ liệu" in reply.json()["detail"], change


def test_the_same_samples_give_the_same_count_as_the_pc():
    # same samples as windows-agent/tests/test_api_share.py: both sides use one rule
    assert api_nodes.data_pieces("a|NGUYEN VAN AN|b") == 1
    assert api_nodes.data_pieces("x=⟦cif⟧&y=12345") == 1
    assert api_nodes.data_pieces("Bearer ⟦l2⟧") == 0
    assert api_nodes.data_pieces("q=Tr%E1%BA%A7n") == 1
    assert api_nodes.data_pieces("a|•••|b") == 0


def test_the_approved_version_serves_its_nodes(client):
    flow = learn(client)
    client.put(f"/workflows/{flow}/versions/1/api", json={"api": NODES})
    client.post(f"/workflows/{flow}/versions/1/test-runs", json={"status": "finished"})
    client.post(f"/workflows/{flow}/versions/1/status", json={"status": "tested"})
    client.post(f"/workflows/{flow}/versions/1/status", json={"status": "approved"})
    assert client.get(f"/workflows/{flow}/approved").json()["api"] == NODES


def test_a_flow_without_nodes_says_so(client):
    flow = learn(client)
    got = client.get(f"/workflows/{flow}").json()
    assert got["api"] is None and got["api_digest"] is None
