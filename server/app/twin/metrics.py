"""Measure the process from the log: step times, waits, rework, errors, API latency and the bottleneck.

Only aggregates, and only when there are at least MIN_CASES cases. Never per person.
"""

from __future__ import annotations

from statistics import median
from typing import Any

from app.storage import Storage
from app.twin.log import by_case, parse_ts

MIN_CASES = 5


def percentile(values: list[float], q: float) -> float:
    """Linear interpolation between closest ranks (q from 0 to 1)."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def stage_rows(process: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {s["id"]: [r for r in rows if r["workflow_id"] == s["workflow_id"]] for s in process["stages"]}


def queue_waits(process: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """For each handoff: per case, from the end of the last row of the first stage to the start of the first row of the next stage."""
    grouped = stage_rows(process, rows)
    waits: dict[str, dict[str, float]] = {}
    for handoff in process["handoffs"]:
        ends: dict[str, float] = {}
        for row in grouped[handoff["from_stage"]]:
            ends[row["case"]] = max(ends.get(row["case"], 0.0), parse_ts(row["end"]))
        starts: dict[str, float] = {}
        for row in grouped[handoff["to_stage"]]:
            starts[row["case"]] = min(starts.get(row["case"], float("inf")), parse_ts(row["start"]))
        waits[handoff["queue"]] = {case: max(0.0, starts[case] - ends[case]) for case in ends if case in starts}
    return waits


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def compute(process: dict[str, Any], rows: list[dict[str, Any]], storage: Storage | None = None) -> dict[str, Any]:
    cases = {r["case"] for s in process["stages"] for r in rows if r["workflow_id"] == s["workflow_id"]}
    if len(cases) < MIN_CASES:
        return {"cases": len(cases), "hidden": True, "steps": [], "queues": [], "bottleneck": None}
    inbound = {h["to_stage"]: h["queue"] for h in process["handoffs"]}
    waits = queue_waits(process, rows)
    steps: list[dict[str, Any]] = []
    for stage in process["stages"]:
        order: list[str] = []
        workflow = storage.get_workflow(stage["workflow_id"]) if storage else None
        if workflow:
            order = [s["id"] for s in workflow[0]["steps"]]
        mine = [r for r in rows if r["workflow_id"] == stage["workflow_id"]]
        for step_id in order + sorted({r["step_id"] for r in mine} - set(order)):
            items = [r for r in mine if r["step_id"] == step_id]
            if not items:
                continue
            seconds = [parse_ts(r["end"]) - parse_ts(r["start"]) for r in items]
            api = [r["api_ms"] for r in items if r["api_ms"] is not None]
            first = order[0] if order else items[0]["step_id"]
            queue = waits.get(inbound.get(stage["id"], ""), {})
            steps.append(
                {
                    "stage": stage["id"],
                    "step_id": step_id,
                    "label": items[0]["label"],
                    "n": len(items),
                    "median_s": _round(median(seconds)),
                    "p90_s": _round(percentile(seconds, 0.9)),
                    "wait_median_s": _round(median(queue.values())) if step_id == first and len(queue) >= MIN_CASES else 0.0,
                    "rework_rate": round(sum(r["outcome"] == "rework" for r in items) / len(items), 4),
                    "error_rate": round(sum(r["outcome"] == "error" for r in items) / len(items), 4),
                    "api_ms_median": _round(median(api)) if api else None,
                }
            )
    queues = [
        {"name": name, "wait_median_s": _round(median(w.values())), "wait_p90_s": _round(percentile(list(w.values()), 0.9))}
        for name, w in waits.items()
        if len(w) >= MIN_CASES
    ]
    candidates = [("step", f"{s['stage']}:{s['step_id']}", s["median_s"] or 0.0) for s in steps] + [("queue", q["name"], q["wait_median_s"] or 0.0) for q in queues]
    total = sum(v for _, _, v in candidates)
    bottleneck = None
    if total > 0:
        kind, name, value = max(candidates, key=lambda c: c[2])
        bottleneck = {"kind": kind, "id": name, "share": round(value / total, 4)}
    return {"cases": len(cases), "hidden": False, "steps": steps, "queues": queues, "bottleneck": bottleneck}
