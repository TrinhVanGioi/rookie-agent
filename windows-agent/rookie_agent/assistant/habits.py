"""What the teller does often, counted from the audit log (design 2.2). Names and counts only: never a value, never a sentence."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

FILE = "assistant-habits.json"
NEXT_WITHIN_SECONDS = 600
MAX_BONUS = 0.05
LONG_DIGITS = re.compile(r"\d{6,}")


def _seconds(text: str) -> float:
    try:
        return time.mktime(time.strptime(text, "%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError):
        return 0.0


def build_habits(audit_path: Path, titles: set[str], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Continue the counts of `previous` with the audit lines it has not seen. Dry runs do not count; agents that are gone are dropped."""
    stats = previous or {"version": 1, "audit_lines": 0, "workflows": {}, "next": {}, "last_finished": None}
    try:
        lines = audit_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for text in lines[int(stats.get("audit_lines", 0)):]:
        try:
            line = json.loads(text)
        except ValueError:
            continue
        stats["audit_lines"] = int(stats.get("audit_lines", 0)) + 1
        title, status = str(line.get("title") or ""), str(line.get("status") or "")
        if line.get("mode") == "dry" or not title:
            continue
        item = stats["workflows"].setdefault(title, {"runs": 0, "finished": 0, "stopped": 0, "failed": 0, "via_assistant": 0, "last": "",
                                                     "hours": [0] * 24, "input_names": {}})
        item["runs"] += 1
        key = status if status in ("finished", "stopped") else "failed"
        item[key] += 1
        item["via_assistant"] += 1 if line.get("via") == "assistant" else 0
        item["last"] = str(line.get("time") or "")[:10]
        when = str(line.get("time") or "")
        if len(when) >= 13 and when[11:13].isdigit():
            item["hours"][int(when[11:13]) % 24] += 1
        for name in line.get("input_names") or []:
            item["input_names"][str(name)] = item["input_names"].get(str(name), 0) + 1
        if status == "finished":
            before = stats.get("last_finished")
            if before and before["title"] != title and 0 <= _seconds(when) - before["at"] <= NEXT_WITHIN_SECONDS:
                row = stats["next"].setdefault(before["title"], {})
                row[title] = row.get(title, 0) + 1
            stats["last_finished"] = {"title": title, "at": _seconds(when)}
    stats["workflows"] = {t: v for t, v in stats["workflows"].items() if t in titles}
    stats["next"] = {t: {n: c for n, c in row.items() if n in titles} for t, row in stats["next"].items() if t in titles}
    stats["built_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return stats


def load_habits(home: Path) -> dict[str, Any] | None:
    try:
        return json.loads((home / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_habits(home: Path, stats: dict[str, Any]) -> bool:
    """Refuses to write anything that looks like a long number: the file must hold names and counts only."""
    text = json.dumps(stats, ensure_ascii=False, indent=1)
    if LONG_DIGITS.search(re.sub(r'"(?:last_finished|built_at|last)": "[^"]*"|"at": [\d.]+', "", text)):
        return False
    try:
        (home / FILE).write_text(text, encoding="utf-8")
    except OSError:
        return False
    return True


def bonus(stats: dict[str, Any] | None, title: str) -> float:
    runs = int(((stats or {}).get("workflows", {}).get(title) or {}).get("runs", 0))
    return min(MAX_BONUS, runs / 1000)


def frequent(stats: dict[str, Any] | None, limit: int = 5) -> list[dict[str, Any]]:
    items = [{"title": t, "runs": v["runs"]} for t, v in (stats or {}).get("workflows", {}).items() if v["runs"]]
    return sorted(items, key=lambda i: -i["runs"])[:limit]


def next_after(stats: dict[str, Any] | None, title: str, limit: int = 3) -> list[dict[str, Any]]:
    row = ((stats or {}).get("next") or {}).get(title) or {}
    return [{"title": t, "count": c} for t, c in sorted(row.items(), key=lambda kv: -kv[1])[:limit]]
