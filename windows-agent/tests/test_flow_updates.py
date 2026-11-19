"""Task 10.7: a version edited on the admin page reaches the PC. Shown with what changed; a draft is tried on the twin and the server is
told; only a version approved on the server is taken; this PC's full templates stay; without the server the PC runs its own copy."""

from __future__ import annotations

import copy
import hashlib
import json
import time

from rookie_agent.ie import api_share, replay
from rookie_agent.server_client import ServerError
from test_replay import flow as base_flow, nodes


def make_core(*a, **k):
    from test_webui import make_core as real    # sibling module (tests/ has no package: the server has one named `tests`)
    return real(*a, **k)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def local_flow():
    api = copy.deepcopy(nodes()[:3])
    return {"title": "Tra cứu", "inputs": ["cif"], "steps": [], "warnings": [], "learned_at": "x", "api": api,
            "workflow": {**base_flow(), "schema_version": 2, "engine": "ie", "id": "tra-cuu", "version": 1, "status": "approved"}}


def server_version(flow, version, status, change=None):
    workflow = {**flow["workflow"], "version": version, "status": status}
    api = api_share.for_server(flow["api"])
    if change:
        change(api)
    return {"workflow": workflow, "digest": digest(workflow), "api": api, "api_digest": digest(api), "warnings": []}


class Server:
    replies: dict = {}
    edits: dict = {}
    told: list = []
    down = False

    def __init__(self, url):
        self.url = url

    def flow_version(self, workflow_id, version=None):
        if Server.down:
            raise ServerError("Không kết nối được máy chủ")
        if version is None:
            version = max(Server.replies)
        reply = Server.replies[version]
        if digest(reply["api"]) != reply["api_digest"]:
            raise ServerError("Nút API nhận về không khớp mã kiểm tra (digest); không dùng.")
        return copy.deepcopy(reply)

    def edit_record(self, workflow_id, version):
        return Server.edits.get(version)

    def post_test_run(self, workflow_id, version, result):
        Server.told.append(("test-run", version, result["status"]))

    def set_status(self, workflow_id, version, status):
        Server.told.append(("status", version, status))

    def post_runs(self, runs):
        return {}


def core_with(tmp_path, *versions):
    Server.replies = {v["workflow"]["version"]: v for v in versions}
    Server.edits, Server.told, Server.down = {2: {"edited_by": "quantri", "base_version": 1}}, [], False
    core, _ = make_core(tmp_path, server_client=Server)
    core.store.put("flows", [local_flow()])
    return core


def relabel_and_add(api):
    first = api[0]["group"] if "group" in api[0] else None
    for node in api:
        if node.get("group") == first:
            node["group_label"] = "Mở màn hình tra cứu"
            node["mode"] = "approve"
    api.append({"id": "n1", "step_id": None, "group": "g99", "group_label": "Tải sao kê", "label": "Tải sao kê → GET /tp/statement",
                "kind": "http", "via": "", "method": "GET", "url": "http://tp.local/tp/statement?cif=⟦cif⟧", "headers": "", "body": "",
                "links": {}, "risk": "read", "complete": True, "unresolved": [], "ms": 0, "masked": 0, "added": True})


# ---- merging ------------------------------------------------------------------------------------------------------------------

def test_merge_keeps_the_full_templates_of_this_pc_and_takes_order_labels_risk_and_duyet_from_the_server():
    local = copy.deepcopy(nodes()[:3])
    local[1]["body"] = local[1]["body"] + "|NGUYEN VAN AN|"
    server = api_share.for_server(local)
    assert "NGUYEN" not in json.dumps(server, ensure_ascii=False)
    server = [server[2], server[1]]                          # the first node dropped, the other two swapped
    server[1].update(group_label="Tìm khách", risk="write", mode="approve")
    server.append({"id": "n1", "group": "g9", "group_label": "Mới", "label": "Mới → GET /x", "kind": "http", "method": "GET", "url": "http://tp.local/x",
                   "headers": "", "body": "", "links": {}, "risk": "read", "complete": True, "unresolved": [], "masked": 0, "added": True})
    merged = api_share.merge(local, server)
    assert [n["id"] for n in merged] == [local[2]["id"], local[1]["id"], "n1"]
    assert "NGUYEN VAN AN" in merged[1]["body"] and merged[1]["shape"] == local[1]["shape"]   # the full template and the twin stay
    assert (merged[1]["group_label"], merged[1]["risk"], merged[1]["mode"]) == ("Tìm khách", "write", "approve")
    assert merged[2]["shape"] is None and merged[2]["added"] is True


def test_merge_never_lowers_a_risk_and_marks_a_node_recorded_elsewhere_as_not_sendable():
    local = copy.deepcopy(nodes()[:2])
    local[0]["risk"] = "write"
    server = api_share.for_server(local)
    server[0]["risk"] = "read"
    server.append({**server[1], "id": "a77", "masked": 2})
    merged = api_share.merge(local, server)
    assert merged[0]["risk"] == "write" and merged[2]["complete"] is False


# ---- what the PC shows and does --------------------------------------------------------------------------------------------

def test_a_newer_version_is_listed_with_what_changed_and_who_edited_it(tmp_path):
    flow = local_flow()
    core = core_with(tmp_path, server_version(flow, 1, "approved"), server_version(flow, 2, "draft", relabel_and_add))
    (update,) = core.dispatch("GET", "/api/flows/updates", {})[1]["updates"]
    assert (update["title"], update["local_version"], update["version"], update["edited_by"]) == ("Tra cứu", 1, 2, "quantri")
    assert update["can_try"] is True and update["can_take"] is False
    assert any("Thêm nút «Tải sao kê»" in line for line in update["changes"])
    assert any("thêm bước Duyệt" in line for line in update["changes"])


def test_a_draft_cannot_be_taken_and_an_approved_one_replaces_this_pcs_copy_with_its_full_templates(tmp_path):
    flow = local_flow()
    flow["api"][1]["body"] += "|NGUYEN VAN AN|"
    core = core_with(tmp_path, server_version(flow, 2, "draft", relabel_and_add))
    core.store.put("flows", [flow])
    status, reply = core.dispatch("POST", "/api/flows/update/take", {"title": "Tra cứu", "version": 2})
    assert status == 400 and "chưa được Duyệt" in reply["error"]

    Server.replies[3] = server_version(flow, 3, "approved", relabel_and_add)
    Server.edits[3] = {"edited_by": "quantri"}
    status, reply = core.dispatch("POST", "/api/flows/update/take", {"title": "Tra cứu", "version": 3})
    assert status == 200 and reply == {"taken": True, "version": 3}
    taken = core.store.get("flows")[0]
    assert taken["workflow"]["version"] == 3 and taken["api"][-1]["id"] == "n1"
    assert "NGUYEN VAN AN" in taken["api"][1]["body"]
    line = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert (line["mode"], line["from_version"], line["version"], line["edited_by"]) == ("update", 1, 3, "quantri")
    assert core.dispatch("GET", "/api/flows/updates", {})[1]["updates"] == []


def test_a_copy_whose_nodes_do_not_match_their_digest_is_not_taken(tmp_path):
    flow = local_flow()
    bad = server_version(flow, 2, "approved")
    bad["api"][0]["url"] = "http://evil.local/x"
    core = core_with(tmp_path, bad)
    status, reply = core.dispatch("POST", "/api/flows/update/take", {"title": "Tra cứu", "version": 2})
    assert status == 400 and "digest" in reply["error"]
    assert core.store.get("flows")[0]["workflow"]["version"] == 1


def test_without_the_server_the_pc_keeps_its_own_copy_and_says_so(tmp_path):
    core = core_with(tmp_path, server_version(local_flow(), 1, "approved"))
    Server.down = True
    reply = core.dispatch("GET", "/api/flows/updates", {})[1]
    assert reply["updates"] == [] and "vẫn chạy như cũ" in reply["error"]
    assert core.store.get("flows")[0]["workflow"]["version"] == 1


def test_trying_a_draft_runs_it_on_the_twin_and_tells_the_server_without_taking_it(tmp_path):
    flow = local_flow()
    core = core_with(tmp_path, server_version(flow, 2, "draft", relabel_and_add))
    status, reply = core.dispatch("POST", "/api/flows/update/try", {"title": "Tra cứu", "version": 2, "inputs": {"cif": "9988776655"}})
    assert status == 200, reply
    end = time.monotonic() + 5
    while time.monotonic() < end:
        state = core.dispatch("GET", "/api/twin/status", {})[1]
        if state["state"] == "waiting_approval":           # the Duyệt added on the admin page asks the person, on the twin too
            core.dispatch("POST", "/api/twin/decide", {"ask_id": state["ask"]["id"], "approve": True})
        if state["state"] in ("finished", "failed", "stopped", "needs_help", "refused") and Server.told:
            break
        time.sleep(0.02)
    assert state["state"] == "finished", state
    assert Server.told == [("test-run", 2, "finished"), ("status", 2, "tested")]
    assert core.store.get("flows")[0]["workflow"]["version"] == 1           # tried, not taken
    line = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert (line["mode"], line["workflow_id"], line["version"]) == ("twin", "tra-cuu", 2) and "9988776655" not in json.dumps(line)


def test_a_read_step_put_under_duyet_on_the_admin_page_asks_before_it_is_sent():
    api = copy.deepcopy(nodes()[:2])
    for node in api:
        node["risk"] = "read"
    api[1]["mode"] = "approve"
    groups = replay.groups_of(api)
    assert groups[-1].get("approve") is True and not groups[0].get("approve")

    class Person:
        asked = []

        def progress(self, *a):
            pass

        def show(self, *a):
            pass

        def approve(self, step, index, total):
            Person.asked.append(step["id"])
            return False

    import threading

    sent = []
    result = replay.run_api({"steps": []}, api, {"cif": "1"}, lambda node, url, headers, body: sent.append(node["id"]) or {"ok": True, "status": 200, "text": "{}"},
                            Person(), threading.Event())
    assert result["status"] == "stopped" and Person.asked == [groups[-1]["id"]]
    assert sent == [c for c in groups[0]["calls"]]           # the first step went; the one under Duyệt sent nothing
