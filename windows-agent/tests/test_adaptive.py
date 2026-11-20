"""Gate 12 (SADPT): what the screen showed after each action rides with the recording (names only), and becomes the flow's
postconditions on the server."""

from __future__ import annotations

import json

from rookie_agent.adaptive import expect
from rookie_agent.ie.recorder import _iso


def event(seq, moment, kind="click", label="TRA CỨU"):
    return {"schema_version": 2, "engine": "ie", "session_id": "s", "seq": seq, "ts": _iso(moment), "type": kind, "url": "IE",
            "target": {"selectors": [f"frame=work|id=b{seq}"], "label": label, "tag": "button"}, "value": None, "value_class": None, "api_calls": []}


def look(moment, *changed, provisional=False):
    return {"t": moment + 900, "t0": moment + 50, "after": {"kind": "click", "id": "b", "label": "x", "t": moment}, "provisional": provisional,
            "changed": [{"frame": f, "kind": k, "name": n} for f, k, n in changed], "frames": [], "frames0": []}


def test_each_event_gets_what_the_screen_showed_after_it_masked_and_without_messages_text():
    events = [event(0, 1_000), event(1, 5_000)]
    seen = [look(1_000, ("work", "table", "tblInfo"), ("work", "field", "Số dư 12.345.678"), ("work", "message", "Khách hàng Nguyen Van A")),
            look(1_000, ("work", "table", "junk"), provisional=True),          # a first reading replaced by the checked one: not kept
            look(5_000, ("work/dlg", "field", "Tên khách hàng"))]
    out = expect.attach_shows(events, seen)
    assert out[0]["shows"] == [{"frame": "work", "kind": "table", "name": "tblInfo"}, {"frame": "work", "kind": "field", "name": "Số dư #"},
                               {"frame": "work", "kind": "message", "name": ""}]
    assert out[1]["shows"] == [{"frame": "work/dlg", "kind": "field", "name": "Tên khách hàng"}]
    text = json.dumps(out, ensure_ascii=False)
    assert "Nguyen Van A" not in text and "12.345.678" not in text


def test_an_action_the_screen_was_not_read_after_says_nothing_and_an_empty_change_is_said():
    events = [event(0, 1_000), event(1, 2_000)]
    out = expect.attach_shows(events, [look(2_000)])
    assert "shows" not in out[0] and out[1]["shows"] == []


def test_the_server_gets_schema_4_when_the_recording_says_what_the_screen_showed(tmp_path):
    from test_webui import make_core

    core, _ = make_core(tmp_path)
    document = {"engine": "ie", "events": expect.attach_shows([event(0, 1_000), event(1, 2_000)], [look(1_000, ("work", "table", "tblInfo"))]),
                "requests": []}
    sent = core._events_for_server(document)
    assert {e["schema_version"] for e in sent} == {4} and sent[0]["shows"] and "shows" not in sent[1]
    old = core._events_for_server({"engine": "ie", "events": [event(0, 1_000)], "requests": []})
    assert old[0]["schema_version"] == 3 and "shows" not in old[0]
