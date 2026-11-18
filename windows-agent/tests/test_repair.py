"""Tasks 6.2 and 6.3: the page changed, the teller points at the element, the agent keeps it as a corrected version to approve."""

import json

from test_webui import RunBridge, run_core, wait_for

CANDIDATE = {"src": "frame=top|src=5", "tag": "input", "label": "So tai khoan", "selectors": ["frame=top|id=acctNew", "frame=top|label=So tai khoan", "frame=top|input[0]"]}


class RepairBridge(RunBridge):
    """The learned id is gone; label and place point at different fields: the agent is not sure."""

    def __init__(self):
        super().__init__()
        self.ops = []

    def locate(self, selectors):
        if selectors == ["frame=top|id=a"]:
            return [{"frame": "top", "probes": [{"kind": "label", "m": [5]}, {"kind": "pos", "m": [9]}], "fields": {"5": 1, "9": 1}}]
        return [{"frame": "top", "probes": [{"kind": "id", "m": [1]}], "fields": {"1": 1}}]

    def frame_op(self, op, selectors, value=""):
        self.ops.append(op)
        return [{"frame": "top", "candidates": [CANDIDATE]}] if op == "suggest" else []


def repair_core(tmp_path, risk="read"):
    core, _ = run_core(tmp_path)
    bridge = RepairBridge()
    core._ie = lambda: bridge
    flows = core.store.get("flows")
    flows[0]["workflow"]["steps"][0]["risk"] = risk
    if risk != "read":
        flows[0]["workflow"]["steps"][0]["mode"] = "approve"
    core.store.put("flows", flows)
    return core, bridge


def start(core):
    return core.dispatch("POST", "/api/run/start", {"title": "Chuyen tien", "inputs": {"acct": "0123456789"}, "window": "ie-tab:1", "mode": "run"})


def test_the_look_alikes_are_marked_and_the_teller_picks_one_then_the_read_step_goes_on(tmp_path):
    core, bridge = repair_core(tmp_path)
    assert start(core)[0] == 200
    ask = wait_for(core, "waiting_pick")["ask"]
    assert ask["candidates"] == [{"label": "So tai khoan", "tag": "input", "color": "vàng"}]
    assert bridge.ops == ["fingerprint", "suggest", "mark"] and bridge.done == []                 # marked, nothing done to the page yet
    assert core.dispatch("POST", "/api/run/decide", {"approve": True, "choice": 0, "ask_id": ask["id"]})[0] == 200
    wait_for(core, "waiting_approval")                                             # the money step after it still waits for a person
    assert bridge.done[0] == ("fill", "frame=top|src=5", "0123456789") and "unmark" in bridge.ops


def test_none_of_them_stops_the_run_and_keeps_nothing(tmp_path):
    core, bridge = repair_core(tmp_path)
    start(core)
    ask = wait_for(core, "waiting_pick")["ask"]
    core.dispatch("POST", "/api/run/decide", {"approve": False, "choice": None, "ask_id": ask["id"]})
    end = wait_for(core, "needs_help")
    assert bridge.done == [] and "repair" not in core.store.get("flows")[0] and "unmark" in bridge.ops


def test_the_pick_makes_a_new_version_that_changes_only_the_selectors_and_waits_for_approval(tmp_path):
    core, bridge = repair_core(tmp_path)
    start(core)
    ask = wait_for(core, "waiting_pick")["ask"]
    core.dispatch("POST", "/api/run/decide", {"approve": True, "choice": 0, "ask_id": ask["id"]})
    money = wait_for(core, "waiting_approval")["ask"]
    core.dispatch("POST", "/api/run/decide", {"approve": False, "ask_id": money["id"]})
    wait_for(core, "rejected")
    flow = core.store.get("flows")[0]
    old, new = flow["workflow"], flow["repair"]["workflow"]
    assert new["version"] == old["version"] + 1 and new["status"] == "draft" and old["status"] == "approved"
    assert new["steps"][0]["target"]["selectors"] == CANDIDATE["selectors"]
    assert [(s["risk"], s["mode"]) for s in new["steps"]] == [(s["risk"], s["mode"]) for s in old["steps"]]
    audit = [json.loads(line) for line in (core.store.home / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    repair = next(line for line in audit if line["mode"] == "repair")
    assert repair["status"] == "waiting_approval" and "0123456789" not in json.dumps(audit)
    listed = core.dispatch("GET", "/api/flows", {})[1]["flows"][0]
    assert listed["repair_pending"] is True and listed["repair"] is None


def test_before_the_approval_only_the_read_part_runs_and_the_approval_takes_the_corrected_version(tmp_path):
    core, bridge = repair_core(tmp_path)
    start(core)
    ask = wait_for(core, "waiting_pick")["ask"]
    core.dispatch("POST", "/api/run/decide", {"approve": True, "choice": 0, "ask_id": ask["id"]})
    wait_for(core, "waiting_approval")
    core.dispatch("POST", "/api/run/stop", {})
    wait_for(core, "stopped")
    core._run["thread"].join(5)
    bridge.done.clear()
    assert start(core)[0] == 200
    end = wait_for(core, "finished")
    assert not any(op == "click" for op, _, _ in bridge.done)                      # the money step was not part of it
    assert core.dispatch("POST", "/api/flow/approve", {"title": "Chuyen tien"})[0] == 200
    flow = core.store.get("flows")[0]
    assert "repair" not in flow and flow["workflow"]["version"] == 2 and flow["workflow"]["status"] == "approved"


class PrintBridge(RunBridge):
    def __init__(self):
        super().__init__()
        self.items = ["input:text|So tai khoan", "button|Gui", "input:text|Ghi chu"]

    def frame_op(self, op, selectors, value=""):
        return [{"frame": "top", "items": list(self.items)}] if op == "fingerprint" else []


def test_a_changed_start_screen_is_said_before_a_real_run_and_a_second_click_goes_ahead(tmp_path):
    core, _ = run_core(tmp_path)
    bridge = PrintBridge()
    core._ie = lambda: bridge
    body = {"title": "Chuyen tien", "inputs": {"acct": "0123456789"}, "window": "ie-tab:1", "mode": "run"}
    core.dispatch("POST", "/api/run/start", body)
    ask = wait_for(core, "waiting_approval")["ask"]
    core.dispatch("POST", "/api/run/decide", {"approve": True, "ask_id": ask["id"]})
    wait_for(core, "finished")
    core._run["thread"].join(5)
    kept = core.store.get("flows")[0]["fingerprint"]
    assert "top|input:text|So tai khoan" in kept and "0123456789" not in json.dumps(kept)
    bridge.items = ["input:text|So CIF", "input:text|Ho ten", "button|Tim"]          # another screen
    status, reply = core.dispatch("POST", "/api/run/start", body)
    assert status == 400 and "Màn hình đã đổi" in reply["error"]
    assert core.dispatch("POST", "/api/run/start", {**body, "confirm_changed": True})[0] == 200


def test_a_write_step_is_not_done_after_the_pick_until_the_corrected_agent_is_approved(tmp_path):
    core, bridge = repair_core(tmp_path, risk="write")
    start(core)
    first = wait_for(core, "waiting_approval")["ask"]                              # the write step asks before it runs
    core.dispatch("POST", "/api/run/decide", {"approve": True, "ask_id": first["id"]})
    ask = wait_for(core, "waiting_pick")["ask"]
    core.dispatch("POST", "/api/run/decide", {"approve": True, "choice": 0, "ask_id": ask["id"]})
    end = wait_for(core, "needs_help")
    assert bridge.done == [] and "Duyệt lại" in end["result"]["message"] and core.store.get("flows")[0]["repair"]
