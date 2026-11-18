"""Discover the real process from the log: which step follows which, the variants, and a suggested stage order."""

from __future__ import annotations

import re
from collections import Counter
from statistics import median
from typing import Any

from app.storage import Storage
from app.twin.log import by_case, parse_ts


def queue_name(to_stage: str, to_role: str) -> str:
    return "cho_duyet" if to_role == "checker" else "cho_" + re.sub(r"[^a-z0-9]+", "_", to_stage.lower()).strip("_")


def stage_map(process: dict[str, Any] | None, rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """workflow id -> {id, role}. Without a process every workflow is its own stage."""
    if process:
        return {s["workflow_id"]: {"id": s["id"], "role": s["role"]} for s in reversed(process["stages"])}
    return {r["workflow_id"]: {"id": r["workflow_id"], "role": r["role"]} for r in rows}


def discover(rows: list[dict[str, Any]], process: dict[str, Any] | None = None) -> dict[str, Any]:
    stages = stage_map(process, rows)
    queues = {(h["from_stage"], h["to_stage"]): h["queue"] for h in (process or {}).get("handoffs", [])}
    nodes: dict[str, dict[str, Any]] = {}
    edges: Counter[tuple[str, str]] = Counter()
    handoff_of: dict[tuple[str, str], str] = {}
    variants: Counter[tuple[str, ...]] = Counter()
    cases = by_case([r for r in rows if r["workflow_id"] in stages])
    for items in cases.values():
        path: list[str] = []
        last_row: dict[str, Any] | None = None
        for row in items:
            stage = stages[row["workflow_id"]]
            node = f"{stage['id']}:{row['step_id']}"
            entry = nodes.setdefault(node, {"id": node, "label": row["label"], "role": stage["role"], "stage": stage["id"], "step_id": row["step_id"], "count": 0})
            entry["count"] += 1
            if path:
                key = (path[-1], node)
                edges[key] += 1
                before = stages[last_row["workflow_id"]]  # type: ignore[index]
                if before["id"] != stage["id"]:
                    handoff_of[key] = queues.get((before["id"], stage["id"])) or queue_name(stage["id"], stage["role"])
            path.append(node)
            last_row = row
        variants[tuple(path)] += 1
    total = len(cases)
    return {
        "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
        "edges": [
            {"from": a, "to": b, "count": n, "handoff": handoff_of.get((a, b))}
            for (a, b), n in sorted(edges.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "variants": [
            {"steps": list(steps), "count": n, "share": round(n / total, 4)}
            for steps, n in sorted(variants.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "cases": total,
    }


def suggest(rows: list[dict[str, Any]], storage: Storage | None = None) -> dict[str, Any]:
    """A draft process from cases that appear in more than one workflow (joined by the hashed case key)."""
    ranks: dict[str, list[int]] = {}
    roles: dict[str, Counter[str]] = {}
    joined = 0
    for items in by_case(rows).values():
        first: dict[str, float] = {}
        for row in items:
            first.setdefault(row["workflow_id"], parse_ts(row["start"]))
            roles.setdefault(row["workflow_id"], Counter())[row["role"]] += 1
        if len(first) < 2:
            continue
        joined += 1
        for rank, workflow_id in enumerate(sorted(first, key=first.get)):  # type: ignore[arg-type]
            ranks.setdefault(workflow_id, []).append(rank)
    if not joined:
        return {
            "name": "", "stages": [], "handoffs": [], "cases_joined": 0,
            "reason": "Chưa có ca nào đi qua nhiều việc (ví dụ người lập lệnh rồi người kiểm soát duyệt). Hãy ghi cả hai vai trò cho cùng một ca rồi thử lại.",
        }
    order = sorted(ranks, key=lambda w: (median(ranks[w]), w))
    stages = []
    for workflow_id in order:
        title = None
        if storage is not None:
            found = storage.get_workflow(workflow_id)
            title = found[0].get("title") if found else None
        stages.append({"id": workflow_id, "workflow_id": workflow_id, "label": title or workflow_id, "role": roles[workflow_id].most_common(1)[0][0]})
    handoffs: list[dict[str, str]] = []
    for a, b in zip(stages, stages[1:]):
        name, used = queue_name(b["id"], b["role"]), {h["queue"] for h in handoffs}
        while name in used:
            name += "_2"
        handoffs.append({"from_stage": a["id"], "to_stage": b["id"], "queue": name})
    return {"name": "Quy trình đầu cuối", "stages": stages, "handoffs": handoffs, "cases_joined": joined, "reason": None}
