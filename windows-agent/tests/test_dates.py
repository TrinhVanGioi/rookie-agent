"""Task 12.6: a calendar icon and a day number are one date fill. Running fills the field and checks it; a read-only field stops the run."""

from __future__ import annotations

from rookie_agent import runner
from rookie_agent.ie import clean


def click(seq, element, name, label):
    return {"schema_version": 2, "engine": "ie", "session_id": "s", "seq": seq, "ts": "2026-11-20T09:00:00.000Z", "type": "click",
            "url": "TouchPoint/Main", "value": None, "value_class": None, "api_calls": [],
            "target": {"selectors": [f"frame=work|id={element}", f"frame=work|name={name}", f"frame=work|label={label}"],
                       "label": label, "tag": "button"}}


def typed(seq, element, label, value):
    return {"schema_version": 2, "engine": "ie", "session_id": "s", "seq": seq, "ts": "2026-11-20T09:00:01.000Z", "type": "input",
            "url": "TouchPoint/Main", "value": value, "value_class": None, "api_calls": [],
            "target": {"selectors": [f"frame=work|id={element}", f"frame=work|label={label}"], "label": label, "tag": "input"}}


def test_the_icon_and_the_day_become_the_date_the_field_already_recorded():
    document = {"events": [click(0, "btnCalFrom", "cal-txtFrom", "Lịch"), click(1, "calD3", "03/11/2026", "3"),
                           typed(2, "txtFrom", "Từ ngày", "03/11/2026"), click(3, "btnHistory", "btnHistory", "XEM LỊCH SỬ")],
                "requests": []}
    events = clean.fold_calendar(document)["events"]
    assert [e["type"] for e in events] == ["input", "click"]
    assert events[0]["target"]["label"] == "Từ ngày" and events[0]["value"] == "03/11/2026"


def test_the_icon_and_the_day_become_a_date_when_the_field_change_was_not_recorded():
    document = {"events": [click(0, "btnCalFrom", "cal-txtFrom", "Lịch"), click(1, "calD3", "03/11/2026", "3")], "requests": []}
    (event,) = clean.fold_calendar(document)["events"]
    assert event["type"] == "input" and event["value"] == "03/11/2026"
    assert event["target"]["selectors"][0] == "frame=work|id=txtFrom"


def test_a_read_only_date_field_stops_the_run_and_asks():
    class Page:
        def window_title(self):
            return "Mock TouchPoint"

        def fill(self, selectors, value):
            raise runner.NeedsHelp("readonly", "Ô chỉ cho đọc, không nhập được.")

    step = {"id": "s1", "action": "fill", "value": "{tu_ngay}", "risk": "read", "mode": "auto",
            "target": {"selectors": ["frame=work|id=txtFrom"], "label": "Từ ngày"}}
    workflow = {"schema_version": 2, "engine": "ie", "id": "f", "version": 1, "status": "approved",
                "inputs": [{"name": "tu_ngay", "type": "date", "label": "Từ ngày"}], "steps": [step,
                {"id": "s2", "action": "click", "target": {"selectors": ["frame=work|id=btnHistory"], "label": "XEM"}, "risk": "read", "mode": "auto"}]}
    result = runner.run_workflow(workflow, {"tu_ngay": "03/11/2026"}, Page(), runner.AutoController(), engine="ie", versions=(2,))
    assert result["status"] == "needs_help" and "chỉ cho đọc" in result["message"]
    assert [s["id"] for s in result["steps"]] == ["s1"]
