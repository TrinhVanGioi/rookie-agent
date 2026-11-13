"""Synthetic end-of-day report data for the mock site.

Everything here is generated from (date, seed). No real customer data is used.
Report A and report B describe the same transactions as seen by two source
systems; a few rows are made to disagree on purpose so the agent has something
to find.
"""

import random
from typing import Literal, TypedDict

DEFAULT_SEED = 42
ROW_COUNT = 40
ROUNDING_THRESHOLD = 1000

Kind = Literal["amount_mismatch", "rounding", "missing_in_a", "missing_in_b"]

_FAMILY_NAMES = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ", "Đặng", "Bùi"]
_MIDDLE_NAMES = ["Văn", "Thị", "Minh", "Thu", "Quốc", "Ngọc"]
_GIVEN_NAMES = ["An", "Bình", "Chi", "Dũng", "Giang", "Hà", "Khánh", "Lan", "Nam", "Oanh"]
_STATUSES = ["Thành công", "Thành công", "Thành công", "Chờ xử lý"]


class Row(TypedDict):
    id: str
    account: str
    customer: str
    amount: int
    status: str


class Planted(TypedDict):
    id: str
    kind: Kind


class Discrepancy(TypedDict):
    id: str
    kind: Kind
    amount_a: int | None
    amount_b: int | None
    diff: int | None


def _build(date: str, seed: int) -> tuple[list[Row], list[Row], list[Planted]]:
    # A string seed is hashed deterministically, unlike hash() of a tuple.
    rng = random.Random(f"{seed}:{date}")
    compact_date = date.replace("-", "")

    base: list[Row] = []
    for index in range(1, ROW_COUNT + 1):
        base.append(
            {
                "id": f"GD{compact_date}-{index:04d}",
                "account": "".join(rng.choice("0123456789") for _ in range(12)),
                "customer": " ".join(
                    [rng.choice(_FAMILY_NAMES), rng.choice(_MIDDLE_NAMES), rng.choice(_GIVEN_NAMES)]
                ),
                "amount": rng.randrange(50_000, 500_000_000),
                "status": rng.choice(_STATUSES),
            }
        )

    picked = rng.sample(range(ROW_COUNT), 8)
    plan: dict[int, Kind] = {
        picked[0]: "amount_mismatch",
        picked[1]: "amount_mismatch",
        picked[2]: "rounding",
        picked[3]: "rounding",
        picked[4]: "rounding",
        picked[5]: "missing_in_b",
        picked[6]: "missing_in_b",
        picked[7]: "missing_in_a",
    }

    report_a: list[Row] = []
    report_b: list[Row] = []
    planted: list[Planted] = []
    for index, row in enumerate(base):
        kind = plan.get(index)
        row_b = dict(row)
        if kind == "amount_mismatch":
            row_b["amount"] = row["amount"] + rng.choice([-1, 1]) * rng.randrange(5_000, 500_000)
        elif kind == "rounding":
            row_b["amount"] = row["amount"] + rng.choice([-1, 1]) * rng.randrange(1, ROUNDING_THRESHOLD)
        if kind != "missing_in_a":
            report_a.append(row)
        if kind != "missing_in_b":
            report_b.append(row_b)  # type: ignore[arg-type]
        if kind is not None:
            planted.append({"id": row["id"], "kind": kind})
    return report_a, report_b, planted


def generate_reports(date: str, seed: int = DEFAULT_SEED) -> tuple[list[Row], list[Row]]:
    """Return (report A, report B) for a date. Same date and seed give the same rows."""
    report_a, report_b, _ = _build(date, seed)
    return report_a, report_b


def planted_discrepancies(date: str, seed: int = DEFAULT_SEED) -> list[Planted]:
    """The rows that were made to disagree on purpose. Ground truth for tests and metrics."""
    return _build(date, seed)[2]


def find_discrepancies(
    report_a: list[Row], report_b: list[Row], rounding_threshold: int = ROUNDING_THRESHOLD
) -> list[Discrepancy]:
    """Reference reconciliation: match rows by id, report missing rows and amount differences.

    An amount difference below `rounding_threshold` is classed as `rounding`.
    """
    by_id_a = {row["id"]: row for row in report_a}
    by_id_b = {row["id"]: row for row in report_b}
    result: list[Discrepancy] = []
    for row_id in sorted(by_id_a.keys() | by_id_b.keys()):
        row_a = by_id_a.get(row_id)
        row_b = by_id_b.get(row_id)
        if row_a is None and row_b is not None:
            result.append(
                {"id": row_id, "kind": "missing_in_a", "amount_a": None, "amount_b": row_b["amount"], "diff": None}
            )
        elif row_b is None and row_a is not None:
            result.append(
                {"id": row_id, "kind": "missing_in_b", "amount_a": row_a["amount"], "amount_b": None, "diff": None}
            )
        elif row_a is not None and row_b is not None and row_a["amount"] != row_b["amount"]:
            diff = row_b["amount"] - row_a["amount"]
            kind: Kind = "rounding" if abs(diff) < rounding_threshold else "amount_mismatch"
            result.append(
                {"id": row_id, "kind": kind, "amount_a": row_a["amount"], "amount_b": row_b["amount"], "diff": diff}
            )
    return result
