"""Make SYNTHETIC end-to-end cases for the process twin, and send them to the server.

Every case is a transfer on a mock-site style system: a maker looks up a CIF and creates a transfer order, then (after a long wait in the
approval queue) a checker opens it and approves. Durations are random but seeded, so the same seed gives the same data. Nothing here is
real: the case key is a hash of an invented order number, the values are never stored (sensitive fields carry only their class).

    python scripts/twin_seed.py http://localhost:8000 --cases 30 --seed 7

Other code (tests, e2e) can call `seed_cases(call, ...)` with any function `call(path, body=None) -> dict` that talks to the server.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import random
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

UNIT_KEY = b"rookie-demo-unit-key"   # on a real PC this is the unit's shared key; here it only has to be the same for maker and checker
MAKER_ID, CHECKER_ID = "lap-lenh-chuyen-tien", "duyet-lenh"
MAKER_TITLE, CHECKER_TITLE = "Tra cứu CIF và lập lệnh chuyển tiền", "Duyệt lệnh chuyển tiền"

# (type, selector, label, tag, value class or None, value, mean seconds, spread, api (method, path, mean ms) or None)
_MAKER = [
    ("click", "#tab-cif", "Tra cứu CIF", "button", None, None, 0.0, 0.0, None),
    ("input", "#f-cif", "Số CIF", "input", "cif_number", None, 8.0, 2.0, None),
    ("click", "#btn-cif-search", "Tìm CIF", "button", None, None, 4.0, 1.0, ("GET", "/api/cif", 300)),
    ("click", "#tab-transfer", "Lập lệnh chuyển tiền", "button", None, None, 3.0, 1.0, None),
    ("input", "#f-from", "Tài khoản chuyển", "input", "account_number", None, 10.0, 3.0, None),
    ("input", "#f-to", "Tài khoản nhận", "input", "account_number", None, 10.0, 3.0, None),
    ("input", "#f-amount", "Số tiền", "input", "amount", None, 8.0, 2.0, None),
    ("click", "#btn-submit-transfer", "Gửi duyệt", "button", None, None, 12.0, 3.0, ("POST", "/api/transfer", 450)),
]
_CHECKER = [
    ("click", "#tab-approvals", "Chờ duyệt", "button", None, None, 0.0, 0.0, None),
    ("click", "#row-open", "Mở lệnh", "button", None, None, 15.0, 5.0, ("GET", "/api/approvals", 200)),
    ("click", "#btn-approve", "Duyệt", "button", None, None, 20.0, 6.0, ("POST", "/api/approve", 380)),
]
QUEUE_MEAN_S, QUEUE_SPREAD_S = 1500.0, 600.0   # the approval queue is deliberately the long part: about 25 minutes


def case_key(order_number: str) -> str:
    return hmac.new(UNIT_KEY, order_number.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _events(session_id: str, rows: list[tuple], start: datetime, rng: random.Random, rework: bool, error: bool) -> list[dict[str, Any]]:
    rows = list(rows)
    if rework:   # the maker types the amount again: the same field edited twice
        at = next(i for i, row in enumerate(rows) if row[1] == "#f-amount")
        rows.insert(at + 1, rows[at])
    events, now = [], start
    for seq, (kind, selector, label, tag, value_class, value, mean, spread, api) in enumerate(rows):
        now += timedelta(seconds=max(0.5, rng.gauss(mean, spread)) if mean else 0)
        calls: list[dict[str, Any]] = []
        if api:
            failed = error and api[1] == "/api/transfer"
            calls = [{"method": api[0], "path": api[1], "status": 409 if failed else 200, "ms": round(max(20.0, rng.gauss(api[2], api[2] * 0.2)), 1)}]
        events.append(
            {
                "schema_version": 3,
                "engine": "web",
                "session_id": session_id,
                "seq": seq,
                "ts": _iso(now),
                "type": kind,
                "url": "/mock-site/chuyen-tien",
                "target": {"selectors": [selector], "label": label, "tag": tag},
                "value": value,
                "value_class": value_class,
                "api_calls": calls,
                "screenshot": None,
            }
        )
    return events


def make_cases(n: int = 30, seed: int = 7, start: str = "2026-11-02T08:00:00Z") -> list[dict[str, Any]]:
    """The sessions of n cases: [{case_key, maker: {session_id, events}, checker: {...}}]."""
    rng = random.Random(seed)
    arrival = datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    cases = []
    for i in range(n):
        arrival += timedelta(seconds=rng.uniform(240, 600))
        key = case_key(f"SEED{seed}-ORDER-{i:04d}")
        maker_id, checker_id = f"seed{seed}-m-{i:04d}", f"seed{seed}-c-{i:04d}"
        maker = _events(maker_id, _MAKER, arrival, rng, rework=rng.random() < 0.1, error=rng.random() < 0.05)
        maker_end = datetime.strptime(maker[-1]["ts"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        picked = maker_end + timedelta(seconds=max(60.0, rng.gauss(QUEUE_MEAN_S, QUEUE_SPREAD_S)))
        checker = _events(checker_id, _CHECKER, picked, rng, rework=False, error=False)
        cases.append({"case_key": key, "maker": {"session_id": maker_id, "events": maker}, "checker": {"session_id": checker_id, "events": checker}})
    return cases


def seed_cases(call: Callable[..., dict[str, Any]], n: int = 30, seed: int = 7, create_process: bool = True) -> dict[str, Any]:
    """Send n synthetic cases, learn the two workflows from them, and (optionally) save the suggested process. `call(path, body=None)` returns the reply (a GET when body is None)."""
    cases = make_cases(n, seed)
    for case in cases:
        for role in ("maker", "checker"):
            session = case[role]
            call("/sessions", {"schema_version": 3, "engine": "web", "session_id": session["session_id"], "events": session["events"],
                               "role": role, "case_key": case["case_key"], "synthetic": True})
    for workflow_id, title, role in ((MAKER_ID, MAKER_TITLE, "maker"), (CHECKER_ID, CHECKER_TITLE, "checker")):
        call("/workflows/learn", {"workflow_id": workflow_id, "title": title, "session_ids": [c[role]["session_id"] for c in cases]})
    result: dict[str, Any] = {"cases": n, "workflows": [MAKER_ID, CHECKER_ID], "synthetic": True}
    if create_process:
        draft = call("/twin/suggest")
        if draft["stages"]:
            result["process"] = call("/twin/processes", {"id": "chuyen-tien-ksv", "name": "Chuyển tiền có KSV duyệt", "stages": draft["stages"], "handoffs": draft["handoffs"]})
    return result


def http_poster(base_url: str) -> Callable[..., dict[str, Any]]:
    base = base_url.rstrip("/")

    def call(path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(base + path, data=data, method="GET" if body is None else "POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise SystemExit(f"{path}: máy chủ trả {error.code}: {error.read().decode('utf-8', 'replace')[:300]}") from error

    return call


def main() -> None:
    parser = argparse.ArgumentParser(description="Sinh ca tổng hợp (synthetic) cho Bản sao quy trình.")
    parser.add_argument("base_url", nargs="?", default="http://localhost:8000")
    parser.add_argument("--cases", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    call = http_poster(args.base_url)
    print(json.dumps(seed_cases(call, args.cases, args.seed), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
