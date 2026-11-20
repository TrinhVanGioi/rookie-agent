"""Task 12.2: the runner checks every step of a version 4 flow against its postcondition, and stops at a safe point on a change it
has never seen (a business change), without pressing anything in it."""

from __future__ import annotations

import json

from rookie_agent import runner


def frame(name, tables=(), messages=()):
    return {"frame": name, "tables": [{"id": t, "headers": ["A"], "rows": [["1"]]} for t in tables], "fields": [],
            "messages": [{"text": m, "level": "info"} for m in messages]}


class ScreenDriver:
    """A page whose screen after each click is scripted: `screens[step id]` is what a look shows once that step was done."""

    def __init__(self, screens):
        self.screens, self.done, self.looks = screens, [], 0

    def window_title(self):
        return "Mock TouchPoint"

    def exists(self, selectors):
        return True

    def click(self, selectors):
        self.done.append(("click", selectors[0]))

    def fill(self, selectors, value):
        self.done.append(("fill", selectors[0]))

    def look(self):
        self.looks += 1
        last = next((sid for sid in reversed(list(self.screens)) if any(sel.endswith(sid) for _, sel in self.done)), None)
        return self.screens.get(last, [frame("top"), frame("work")])


def flow(expect_find=True):
    find = {"id": "s2", "action": "click", "target": {"selectors": ["frame=work|id=s2"], "label": "TRA CỨU"}, "risk": "read", "mode": "auto",
            "intent": "TRA CỨU", "adapt": {"reresolve": True}}
    if expect_find:
        find["expect"] = {"appears": [{"frame": "work", "kind": "table", "name": "tblInfo"}]}
    return {"schema_version": 4, "engine": "ie", "id": "f", "version": 1, "status": "approved", "inputs": [{"name": "acct", "type": "string"}],
            "steps": [{"id": "s1", "action": "fill", "value": "{acct}", "target": {"selectors": ["frame=work|id=s1"]}, "risk": "read", "mode": "auto",
                       "adapt": {"reresolve": True}},
                      find,
                      {"id": "s3", "action": "click", "target": {"selectors": ["frame=work|id=s3"], "label": "IN"}, "risk": "read", "mode": "auto",
                       "intent": "IN", "adapt": {"reresolve": True}}]}


def go(driver, workflow=None):
    return runner.run_workflow(workflow or flow(), {"acct": "0123456789"}, driver, runner.AutoController(), engine="ie", versions=(2, 3, 4),
                               post_timeout=0.6, sleep=lambda s: None)


def test_a_step_whose_postcondition_shows_goes_on_and_the_run_finishes():
    d = ScreenDriver({"s2": [frame("top"), frame("work", tables=["tblInfo"])]})
    result = go(d)
    assert result["status"] == "finished" and [s for _, s in d.done] == ["frame=work|id=s1", "frame=work|id=s2", "frame=work|id=s3"]
    assert d.looks >= 2 and "decisions" not in result


def test_a_dialog_never_seen_while_recording_stops_the_run_there_without_pressing_anything_else():
    d = ScreenDriver({"s2": [frame("top"), frame("work", tables=["tblInfo"]), frame("work/dlg", messages=["Khách hàng Nguyen Van A cần xác nhận"])]})
    result = go(d)
    assert result["status"] == "needs_help" and [s for _, s in d.done] == ["frame=work|id=s1", "frame=work|id=s2"]
    assert "chưa từng thấy" in result["message"] and "TRA CỨU" in result["message"] and result["teach_after"] == "s2"
    assert result["decisions"] == [{"step_id": "s2", "saw": "unexpected", "change": "business", "action": "ask", "outcome": "stopped",
                                    "risk": "read", "where": {"frame": "work/dlg", "kind": "frame"}}]
    assert "Nguyen" not in json.dumps(result) and "0123456789" not in json.dumps(result)


def test_the_expected_result_that_never_comes_stops_and_says_what_was_awaited():
    d = ScreenDriver({"s2": [frame("top"), frame("work", tables=["tblEmpty"])]})
    result = go(d)
    assert result["status"] == "needs_help" and "tblInfo" in result["message"] and len(d.done) == 2
    assert result["decisions"][0]["saw"] == "missing" and result["decisions"][0]["change"] == "unknown"


def test_a_flow_before_version_4_and_a_driver_that_cannot_look_run_as_before():
    old = flow()
    old["schema_version"] = 3
    for step in old["steps"]:
        for key in ("intent", "expect", "adapt"):
            step.pop(key, None)
    d = ScreenDriver({"s2": [frame("top"), frame("work/dlg")]})
    assert go(d, old)["status"] == "finished" and d.looks == 0

    class Blind(ScreenDriver):
        look = None

    assert go(Blind({}))["status"] == "finished"
