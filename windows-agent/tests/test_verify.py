"""Task 12.2 (SADPT, Monitor and Analyze): after a step the screen is laid against its postcondition, and a change is sorted into
technical or business before anything is decided."""

from __future__ import annotations

import json

from rookie_agent.adaptive import classify, verify


def frame(name, tables=(), fields=(), messages=()):
    return {"frame": name, "tables": [{"id": t, "headers": ["A"], "rows": [["1"]]} for t in tables],
            "fields": [{"label": label, "value": value} for label, value in fields],
            "messages": [{"text": text, "level": "info"} for text in messages]}


EXPECT = [{"frame": "work", "kind": "table", "name": "tblInfo"}]
BEFORE = [frame("top", fields=[("Giờ", "10:00:00")]), frame("work")]


def test_the_expected_table_on_screen_is_ok_and_a_clock_that_ticked_is_not_a_change():
    after = [frame("top", fields=[("Giờ", "10:00:02")]), frame("work", tables=["tblInfo"])]
    assert verify.check(EXPECT, BEFORE, after, known_frames={"top", "work"})["state"] == "ok"


def test_what_is_expected_and_not_there_yet_is_missing_by_name_only():
    verdict = verify.check(EXPECT, BEFORE, [frame("top"), frame("work", tables=["tblOther"])], known_frames={"top", "work"})
    assert verdict["state"] == "missing" and verdict["missing"] == EXPECT


def test_a_dialog_or_a_message_never_seen_while_recording_is_unexpected_and_says_no_text():
    dialog = [frame("top"), frame("work", tables=["tblInfo"]), frame("work/dlg", fields=[("Xác nhận", "Khách hàng Nguyen Van A")])]
    verdict = verify.check(EXPECT, BEFORE, dialog, known_frames={"top", "work"})
    assert verdict["state"] == "unexpected" and verdict["unexpected"] == [{"frame": "work/dlg", "kind": "frame"}]
    message = [frame("top"), frame("work", tables=["tblInfo"], messages=["Tài khoản 0123456789 bị phong toả"])]
    verdict = verify.check(EXPECT, BEFORE, message, known_frames={"top", "work"})
    assert verdict["state"] == "unexpected" and verdict["unexpected"] == [{"frame": "work", "kind": "message"}]
    assert "0123456789" not in json.dumps(verdict) and "Nguyen" not in json.dumps(verdict)


def test_a_message_the_recordings_showed_after_this_step_is_expected_and_one_that_keeps_changing_is_not_news():
    saved = EXPECT + [{"frame": "work", "kind": "message", "name": ""}]
    after = [frame("top"), frame("work", tables=["tblInfo"], messages=["Đã lưu"])]
    assert verify.check(saved, BEFORE, after, known_frames={"top", "work"})["state"] == "ok"
    ticking = verify.check(EXPECT, BEFORE, after, known_frames={"top", "work"}, volatile={("work", "message", "*")})
    assert ticking["state"] == "ok"


def test_a_box_the_next_step_answers_is_the_way_on_not_news():
    box = [frame("top"), frame("work", tables=["tblInfo"]), frame("work/dlg", messages=["Xác nhận giấy tờ tuỳ thân"])]
    known = {"top", "work", "work/dlg"}
    assert verify.check(EXPECT, BEFORE, box, known_frames=known)["state"] == "unexpected"                   # a message nobody answers
    assert verify.check(EXPECT, BEFORE, box, known_frames=known, answered_in={"work/dlg"})["state"] == "ok"  # the next step presses in it


def test_a_step_without_postcondition_only_watches_for_the_unexpected():
    assert verify.check([], BEFORE, [frame("top"), frame("work")], known_frames={"top", "work"})["state"] == "ok"
    assert verify.check([], BEFORE, [frame("top"), frame("work"), frame("work/dlg")], known_frames={"top", "work"})["state"] == "unexpected"


def test_changes_are_sorted_technical_or_business_and_each_decision_is_a_row_without_values():
    assert classify.classify("not_found")["change"] == "technical" and classify.classify("low_confidence")["change"] == "technical"
    assert classify.classify("unexpected")["change"] == "business" and classify.classify("unexpected")["action"] == "ask"
    assert classify.classify("missing")["change"] == "unknown"
    row = classify.decision("s2_tra_cuu", "unexpected", "ask", "stopped", detail={"frame": "work/dlg", "kind": "frame"})
    assert row == {"step_id": "s2_tra_cuu", "saw": "unexpected", "change": "business", "action": "ask", "outcome": "stopped",
                   "where": {"frame": "work/dlg", "kind": "frame"}}
