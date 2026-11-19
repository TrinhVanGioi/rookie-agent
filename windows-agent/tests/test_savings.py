"""Task 11.8: time saved, from the recordings and the finished runs; no number before there are enough of both."""

from __future__ import annotations

import json

from rookie_agent.assistant import savings


def ev(ts):
    return {"ts": ts}


def test_a_recording_lasts_from_its_first_action_to_its_last():
    assert savings.recording_seconds([ev("2026-11-20T09:00:00.000Z"), ev("2026-11-20T09:02:30.500Z")]) == 150.5
    assert savings.recording_seconds([ev("2026-11-20T09:00:00.000Z")]) is None


def test_runs_are_the_finished_ones_of_that_flow(tmp_path):
    audit = tmp_path / "audit.jsonl"
    lines = [{"title": "Sao kê", "status": "finished", "mode": "simulate", "seconds": 4.2}, {"title": "Sao kê", "status": "failed", "mode": "simulate", "seconds": 1},
             {"title": "Sao kê", "status": "finished", "mode": "twin", "seconds": 9}, {"title": "Khác", "status": "finished", "mode": "run", "seconds": 3}]
    audit.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    assert savings.run_seconds(audit, "Sao kê") == [4.2]


def test_no_number_before_three_of_each_and_then_medians():
    assert "Chưa đủ" in savings.summary([120, 130], [5, 6, 7])["text"]
    shown = savings.summary([120, 150, 180], [5, 6, 30])
    assert (shown["manual_s"], shown["agent_s"], shown["saved_s"]) == (150, 6, 144)
    assert shown["text"] == "Làm tay khoảng 2,5 phút, trợ lý khoảng 6 giây: tiết kiệm khoảng 2,4 phút mỗi lần."
