"""How much time a flow saves (task 11.8): by hand (the recordings, first action to last) against the assistant (finished runs).

Medians, never a guess: fewer than MIN_SAMPLES on either side and no number is shown. Only durations; no value of any kind.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

MIN_SAMPLES = 3
COUNTED = ("run", "simulate")


def recording_seconds(events: list[dict[str, Any]]) -> float | None:
    """First action to last action of one recording, in seconds."""
    stamps = []
    for event in events:
        try:
            stamps.append(datetime.fromisoformat(str(event.get("ts")).replace("Z", "+00:00")).timestamp())
        except ValueError:
            continue
    return round(max(stamps) - min(stamps), 1) if len(stamps) >= 2 else None


def run_seconds(audit_path: Path, title: str) -> list[float]:
    found: list[float] = []
    try:
        lines = audit_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return found
    for text in lines:
        try:
            line = json.loads(text)
        except ValueError:
            continue
        if line.get("title") == title and line.get("status") == "finished" and line.get("mode") in COUNTED:
            found.append(float(line.get("seconds") or 0))
    return found


def summary(manual: list[float], runs: list[float]) -> dict[str, Any]:
    """{"manual_s", "agent_s", "saved_s", "text"} when both sides have enough samples, else {"text": why not yet}."""
    if len(manual) < MIN_SAMPLES or len(runs) < MIN_SAMPLES:
        return {"text": f"Chưa đủ số đo để tính thời gian tiết kiệm (cần {MIN_SAMPLES} lần ghi và {MIN_SAMPLES} lần chạy)."}
    by_hand, agent = statistics.median(manual), statistics.median(runs)
    saved = max(0.0, by_hand - agent)

    def words(seconds: float) -> str:
        return f"{seconds / 60:.1f} phút".replace(".", ",") if seconds >= 90 else f"{round(seconds)} giây"

    return {"manual_s": round(by_hand, 1), "agent_s": round(agent, 1), "saved_s": round(saved, 1),
            "text": f"Làm tay khoảng {words(by_hand)}, trợ lý khoảng {words(agent)}: tiết kiệm khoảng {words(saved)} mỗi lần."}
