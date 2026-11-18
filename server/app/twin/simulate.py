"""What-if simulation of the end-to-end process: a discrete-event model with a heap and a seeded random generator.

Durations are sampled from the measured step times (empirical, a resampling of the log), with the API part and the human part kept apart:
  - `api_factor` scales only the API part (the measured api_ms of the visit);
  - a step marked "remove" takes no time (a stage with no time left is skipped, so it does not queue);
  - a step marked "agent" takes the measured agent run time when a passed sandbox run recorded one for that step; otherwise
    AGENT_FACTOR (0.3) of the human part, plus the API part (scaled by api_factor).
The draws of one case do not depend on how the staff or the other steps are set, so a baseline and a scenario with the same seed
see the same cases and the same step times: the difference between them is the change, not luck. Same seed, same output.
Baseline = default staff (1 maker, 1 checker, or `baseline_staff`), api_factor 1, every step kept.

Calibration (so the baseline reproduces what was measured): a handoff queue waits not only for a free checker but also for
one to look at the queue (they have other work). Each free person of that role picks up a waiting case after an exponential
delay of mean `pickup`, so k free people pick up after pickup/k on average: more checkers, shorter wait. `pickup` per role is
found by bisection so that the baseline median wait of the queue matches the measured median wait (metrics.queue_waits).
"""

from __future__ import annotations

import heapq
import random
from collections import deque
from statistics import median
from typing import Any

from app.llm.base import rule_simulation_text
from app.storage import Storage
from app.twin.log import parse_ts
from app.twin.metrics import percentile, queue_waits

AGENT_FACTOR = 0.3
DEFAULT_STAFF = {"maker": 1, "checker": 1}
MAX_CASES = 20000
MODES = ("keep", "remove", "agent")
FIRST_QUEUE = "Chờ GDV nhận ca"


class SimError(ValueError):
    """The simulation cannot run. The message says why, in Vietnamese."""


class _Clock:
    """Working hours (start hour, end hour of each day), or around the clock when None."""

    def __init__(self, work_hours: dict[str, int] | None) -> None:
        self.on = work_hours is not None
        self.start = (work_hours or {}).get("start", 0) * 3600
        self.end = (work_hours or {}).get("end", 24) * 3600

    def snap(self, t: float) -> float:
        if not self.on:
            return t
        day = t // 86400
        tod = t - day * 86400
        if tod < self.start:
            return day * 86400 + self.start
        if tod >= self.end:
            return (day + 1) * 86400 + self.start
        return t

    def finish(self, start: float, duration: float) -> float:
        if not self.on:
            return start + duration
        t, left = start, duration
        while True:
            t = self.snap(t)
            room = (t // 86400) * 86400 + self.end - t
            if left <= room:
                return t + left
            left -= room
            t = (t // 86400 + 1) * 86400 + self.start

    def working(self, a: float, b: float) -> float:
        if not self.on:
            return max(0.0, b - a)
        total, day = 0.0, int(a // 86400)
        while day * 86400 < b:
            lo, hi = max(a, day * 86400 + self.start), min(b, day * 86400 + self.end)
            total += max(0.0, hi - lo)
            day += 1
        return total

    def wall(self, work: float) -> float:
        if not self.on:
            return work
        window = self.end - self.start
        return (work // window) * 86400 + self.start + work % window


def build_model(process: dict[str, Any], rows: list[dict[str, Any]], storage: Storage | None = None) -> dict[str, Any]:
    """The measured pools per step, in stage order."""
    inbound = {h["to_stage"]: h["queue"] for h in process["handoffs"]}
    stages = []
    for index, stage in enumerate(process["stages"]):
        mine = [r for r in rows if r["workflow_id"] == stage["workflow_id"]]
        order: list[str] = []
        workflow = storage.get_workflow(stage["workflow_id"]) if storage else None
        if workflow:
            order = [s["id"] for s in workflow[0]["steps"]]
        order += sorted({r["step_id"] for r in mine} - set(order))
        agent = storage.agent_run_ms(stage["workflow_id"]) if storage else {}
        steps = []
        for step_id in order:
            pool = []
            for row in (r for r in mine if r["step_id"] == step_id):
                total = max(0.0, parse_ts(row["end"]) - parse_ts(row["start"]))
                api = min(total, (row["api_ms"] or 0.0) / 1000)
                pool.append((total - api, api))
            if pool:
                measured = median(agent[step_id]) / 1000 if agent.get(step_id) else None
                steps.append({"key": f"{stage['id']}:{step_id}", "step_id": step_id, "pool": pool, "agent_s": measured})
        if steps:
            queue = inbound.get(stage["id"]) or (FIRST_QUEUE if index == 0 else stage["id"])
            stages.append({"id": stage["id"], "role": stage["role"], "queue": queue, "steps": steps})
    if not stages:
        raise SimError("Chưa có số đo nào của quy trình này để mô phỏng. Hãy ghi và gom thêm ca trước.")
    return {"stages": stages}


def _service(step: dict[str, Any], draw: tuple[float, float], mode: str, api_factor: float) -> float:
    human, api = draw
    if mode == "remove":
        return 0.0
    if mode == "agent":
        if step["agent_s"] is not None:
            return step["agent_s"]
        return AGENT_FACTOR * human + api * api_factor
    return human + api * api_factor


def _mode_of(modes: dict[str, str], step: dict[str, Any]) -> str:
    return modes.get(step["key"]) or modes.get(step["step_id"]) or "keep"


def default_rate(model: dict[str, Any], staff: dict[str, int]) -> float:
    """About 80% of what the slowest role can do: busy, but not overloaded."""
    load: dict[str, float] = {}
    for stage in model["stages"]:
        mean = sum(sum(h + a for h, a in s["pool"]) / len(s["pool"]) for s in stage["steps"])
        load[stage["role"]] = load.get(stage["role"], 0.0) + mean
    rates = [staff.get(role, 1) * 3600 / seconds for role, seconds in load.items() if seconds > 0]
    return round(0.8 * min(rates), 3) if rates else 1.0


def run_once(
    model: dict[str, Any],
    *,
    seed: int,
    hours: float,
    arrivals_per_hour: float,
    staff: dict[str, int],
    api_factor: float,
    modes: dict[str, str],
    work_hours: dict[str, int] | None,
    pickup: dict[str, float] | None = None,
) -> dict[str, Any]:
    clock = _Clock(work_hours)
    horizon = hours * 3600
    arrivals_rng, service_rng = random.Random(f"{seed}:arrivals"), random.Random(f"{seed}:service")
    pickup_rng, pickup = random.Random(f"{seed}:pickup"), pickup or {}
    stages = model["stages"]
    # The cases, with every draw made up front so that nothing the scenario changes can shift them.
    cases: list[dict[str, Any]] = []
    work_t, limit = 0.0, clock.working(0, horizon)
    while True:
        work_t += arrivals_rng.expovariate(arrivals_per_hour / 3600)
        if work_t > limit or len(cases) >= MAX_CASES:
            break
        draws = [[service_rng.choice(s["pool"]) for s in stage["steps"]] for stage in stages]
        cases.append({"arrive": clock.wall(work_t), "draws": draws})
    heap: list[tuple[float, int, str, int, int]] = []
    counter = 0

    def push(time: float, kind: str, case: int, stage: int) -> None:
        nonlocal counter
        heapq.heappush(heap, (time, counter, kind, case, stage))
        counter += 1

    for number, case in enumerate(cases):
        push(case["arrive"], "request", number, 0)
    roles = {s["role"] for s in stages}
    busy = {role: 0 for role in roles}
    waiting: dict[str, deque] = {role: deque() for role in roles}
    busy_time = {role: 0.0 for role in roles}
    waits: dict[str, list[float]] = {}
    done: list[tuple[float, float, int]] = []   # (cycle, finish time, case)

    def capacity(role: str) -> int:
        return max(1, staff.get(role, 1))

    def service_of(number: int, stage_index: int) -> float:
        stage = stages[stage_index]
        draws = cases[number]["draws"][stage_index]
        return sum(_service(s, d, _mode_of(modes, s), api_factor) for s, d in zip(stage["steps"], draws))

    def begin(now: float, number: int, stage_index: int, asked: float) -> None:
        stage = stages[stage_index]
        mean = pickup.get(stage["role"], 0.0)
        free = capacity(stage["role"]) - busy[stage["role"]]
        delay = pickup_rng.expovariate(free / mean) if mean > 0 else 0.0
        start = clock.snap(now + delay)
        end = clock.finish(start, service_of(number, stage_index))
        waits.setdefault(stage["queue"], []).append(start - asked)
        busy[stage["role"]] += 1
        if start < horizon:
            busy_time[stage["role"]] += clock.working(start, min(end, horizon))
        push(end, "finish", number, stage_index)

    def request(now: float, number: int, stage_index: int) -> None:
        while stage_index < len(stages) and service_of(number, stage_index) <= 0:
            stage_index += 1   # nothing left to do in this stage: it is skipped
        if stage_index >= len(stages):
            done.append((now - cases[number]["arrive"], now, number))
            return
        role = stages[stage_index]["role"]
        if busy[role] < capacity(role):
            begin(now, number, stage_index, now)
        else:
            waiting[role].append((now, number, stage_index))

    while heap and heap[0][0] <= horizon:
        now, _, kind, number, stage_index = heapq.heappop(heap)
        if kind == "request":
            request(now, number, stage_index)
        else:
            role = stages[stage_index]["role"]
            busy[role] -= 1
            request(now, number, stage_index + 1)
            if waiting[role] and busy[role] < capacity(role):
                asked, next_case, next_stage = waiting[role].popleft()
                begin(now, next_case, next_stage, asked)

    cycles = [d[0] for d in done]
    shares: list[tuple[str, str, float]] = []
    if done:
        totals: dict[str, float] = {}
        for _, _, number in done:
            for s_index, stage in enumerate(stages):
                for step, draw in zip(stage["steps"], cases[number]["draws"][s_index]):
                    totals[step["key"]] = totals.get(step["key"], 0.0) + _service(step, draw, _mode_of(modes, step), api_factor)
        shares = [("step", key, value / len(done)) for key, value in totals.items()]
        shares += [("queue", name, median(values)) for name, values in waits.items()]
    total = sum(v for _, _, v in shares)
    bottleneck = None
    if total > 0:
        kind, name, value = max(shares, key=lambda c: c[2])
        bottleneck = {"kind": kind, "id": name, "share": round(value / total, 4)}
    available = {role: capacity(role) * clock.working(0, horizon) for role in roles}
    return {
        "completed": len(done),
        "cycle_mean_s": round(sum(cycles) / len(cycles), 2) if cycles else None,
        "cycle_p90_s": round(percentile(cycles, 0.9), 2) if cycles else None,
        "waits": {name: round(median(values), 2) for name, values in waits.items()},
        "utilization": {role: round(min(1.0, busy_time[role] / available[role]), 4) if available[role] else 0.0 for role in sorted(roles)},
        "bottleneck": bottleneck,
    }


def simulate(
    process: dict[str, Any], rows: list[dict[str, Any]], params: dict[str, Any], storage: Storage | None = None, client: Any = None
) -> dict[str, Any]:
    model = build_model(process, rows, storage)
    base_staff = {**DEFAULT_STAFF, **(params.get("baseline_staff") or {})}
    staff = {**base_staff, **(params.get("staff") or {})}
    rate = params.get("arrivals_per_hour") or default_rate(model, base_staff)
    hours = params.get("hours") or 8
    if rate * hours > MAX_CASES:
        raise SimError(f"Quá nhiều ca ({round(rate * hours)}); giảm số giờ hoặc số ca mỗi giờ (tối đa {MAX_CASES} ca).")
    modes = params.get("steps") or {}
    pickup = calibrate(model, process, rows, seed=params.get("seed", 1), hours=hours, rate=rate, staff=base_staff,
                       work_hours=params.get("work_hours"))
    known = {s["key"] for st in model["stages"] for s in st["steps"]} | {s["step_id"] for st in model["stages"] for s in st["steps"]}
    unknown = [k for k in modes if k not in known]
    if unknown:
        raise SimError(f"Không có bước {unknown[0]} trong quy trình này.")
    api_factor = params.get("api_factor", 1.0)
    common = {"seed": params.get("seed", 1), "hours": hours, "arrivals_per_hour": rate, "work_hours": params.get("work_hours")}
    baseline = run_once(model, staff=base_staff, api_factor=1.0, modes={}, pickup=pickup, **common)
    scenario = run_once(model, staff=staff, api_factor=api_factor, modes=modes, pickup=pickup, **common)
    changes = {
        "staff": staff,
        "baseline_staff": base_staff,
        "api_factor": api_factor,
        "steps": {k: v for k, v in modes.items() if v != "keep"},
        "arrivals_per_hour": rate,
        "hours": hours,
    }
    try:
        text = client.explain_simulation(baseline, scenario, changes) if client is not None else rule_simulation_text(baseline, scenario, changes)
    except Exception:   # a model that fails must not fail the simulation: the rules write the sentence
        text = rule_simulation_text(baseline, scenario, changes)
    return {"baseline": baseline, "scenario": scenario, "explanation": text,
            "inputs": {**common, **changes, "pickup_s": {k: round(v, 1) for k, v in pickup.items()}}}


def calibrate(model: dict[str, Any], process: dict[str, Any], rows: list[dict[str, Any]], *, seed: int, hours: float,
              rate: float, staff: dict[str, int], work_hours: dict[str, int] | None) -> dict[str, float]:
    """The pickup delay per role that makes the baseline wait of each handoff queue match the measured one."""
    measured = {name: median(v.values()) for name, v in queue_waits(process, rows).items() if v}
    pickup: dict[str, float] = {}
    for stage in model["stages"]:
        target = measured.get(stage["queue"])
        if not target or stage["role"] in pickup:
            continue
        lo, hi = 0.0, 4 * target
        for _ in range(25):
            mid = (lo + hi) / 2
            got = run_once(model, seed=seed, hours=hours, arrivals_per_hour=rate, staff=staff, api_factor=1.0, modes={},
                           work_hours=work_hours, pickup={**pickup, stage["role"]: mid})["waits"].get(stage["queue"], 0.0)
            lo, hi = (mid, hi) if got < target else (lo, mid)
        pickup[stage["role"]] = (lo + hi) / 2
    return pickup
