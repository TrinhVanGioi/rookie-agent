"""Build the process event log from stored sessions.

A row is one visit to one workflow step in one session. Times come from the event `ts`. A step starts when the previous action ended
(the GDV's work and thinking before the action count as the step's time) and ends at its last action.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.storage import Storage

ROLES = ("maker", "checker")
_ACTIONS = {"input": {"fill"}, "select": {"select"}, "click": {"click"}, "submit": {"submit", "click"}, "navigate": {"goto"}}


def parse_ts(text: str) -> float:
    return datetime.strptime(text.replace("Z", ""), "%Y-%m-%dT%H:%M:%S.%f" if "." in text else "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


def to_ts(seconds: float) -> str:
    seconds = round(seconds, 3)
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(round(seconds % 1 * 1000)) % 1000:03d}Z"


def match_step(event: dict[str, Any], steps: list[dict[str, Any]]) -> int | None:
    """Index of the workflow step an event belongs to: same kind of action on an element sharing a selector (or the same page for navigate)."""
    wanted = _ACTIONS.get(event["type"], set())
    target = event.get("target")
    for index, step in enumerate(steps):
        if step.get("action") not in wanted:
            continue
        if event["type"] == "navigate":
            if step.get("url") == event.get("url"):
                return index
        elif target and step.get("target") and set(target["selectors"]) & set(step["target"]["selectors"]):
            return index
    return None


def _visits(events: list[dict[str, Any]], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group the events of a session into visits of steps, in time order."""
    ordered = sorted(events, key=lambda e: e["seq"])
    visits: list[dict[str, Any]] = []
    previous_end: float | None = None
    for event in ordered:
        now = parse_ts(event["ts"])
        index = match_step(event, steps)
        if index is None:
            previous_end = now
            continue
        if visits and visits[-1]["index"] == index:
            visit = visits[-1]
        else:
            visit = {"index": index, "start": previous_end if previous_end is not None else now, "events": []}
            visits.append(visit)
        visit["events"].append(event)
        visit["end"] = now
        previous_end = now
    return visits


def _outcome(visit: dict[str, Any], seen_max: int, visited: set[int]) -> str:
    calls = [c for e in visit["events"] for c in e.get("api_calls") or []]
    if any(c["status"] >= 400 for c in calls):
        return "error"
    edits: dict[str, int] = {}
    for event in visit["events"]:
        if event["type"] in ("input", "select") and event.get("target"):
            key = event["target"]["selectors"][0]
            edits[key] = edits.get(key, 0) + 1
    if any(n > 1 for n in edits.values()) or visit["index"] in visited or visit["index"] < seen_max:
        return "rework"
    return "done"


def session_rows(session: dict[str, Any], workflow: dict[str, Any]) -> list[dict[str, Any]]:
    steps = workflow["steps"]
    rows: list[dict[str, Any]] = []
    seen_max, visited = -1, set()
    for visit in _visits(session["events"], steps):
        step = steps[visit["index"]]
        timings = [c["ms"] for e in visit["events"] for c in e.get("api_calls") or [] if "ms" in c]
        rows.append(
            {
                "case": session.get("case_key") or session["session_id"],
                "session_id": session["session_id"],
                "workflow_id": workflow["id"],
                "step_id": step["id"],
                "label": (step.get("target") or {}).get("label") or step["id"],
                "role": session.get("role") or "maker",
                "start": to_ts(visit["start"]),
                "end": to_ts(visit["end"]),
                "outcome": _outcome(visit, seen_max, visited),
                "api_ms": sum(timings) if timings else None,
            }
        )
        seen_max = max(seen_max, visit["index"])
        visited.add(visit["index"])
    return rows


MIN_MATCH = 0.6   # a session that was not learned from belongs to the workflow most of its actions match, if at least this part does


def _best_workflow(session: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    events = session["events"]
    best, best_score = None, MIN_MATCH
    for workflow in candidates:
        if workflow.get("engine") != session["engine"]:
            continue
        score = sum(match_step(e, workflow["steps"]) is not None for e in events) / max(1, len(events))
        if score >= best_score and (best is None or score > best_score):
            best, best_score = workflow, score
    return best


def build_log(storage: Storage, workflow_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Rows of every session. A session a workflow was learned from belongs to it (the newest one when there are several); any other
    session belongs to the workflow its actions match best."""
    owner: dict[str, tuple[str, int]] = {}
    for workflow_id, version, session_ids in storage.learn_sources():
        for session_id in session_ids:
            owner[session_id] = (workflow_id, version)
    latest: dict[str, dict[str, Any]] = {}
    for entry in storage.list_workflows():
        found = storage.get_workflow(entry["id"])
        if found:
            latest[entry["id"]] = found[0]
    candidates = [w for w in latest.values() if not workflow_ids or w["id"] in workflow_ids]
    documents: dict[tuple[str, int], dict[str, Any] | None] = {}
    rows: list[dict[str, Any]] = []
    for session in storage.all_sessions():
        link = owner.get(session["session_id"])
        if link is not None:
            if workflow_ids and link[0] not in workflow_ids:
                continue
            if link not in documents:
                found = storage.get_workflow(link[0], link[1])
                documents[link] = found[0] if found else None
            workflow = documents[link]
        else:
            workflow = _best_workflow(session, candidates)
        if workflow is not None:
            rows.extend(session_rows(session, workflow))
    rows.sort(key=lambda r: (r["start"], r["session_id"]))
    return rows


def by_case(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    cases: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        cases.setdefault(row["case"], []).append(row)
    for items in cases.values():
        items.sort(key=lambda r: (parse_ts(r["start"]), parse_ts(r["end"])))
    return cases
