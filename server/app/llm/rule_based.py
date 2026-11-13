"""Offline client: fixed rules, no model, no network. Used in tests, demos and as the fallback."""

from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher

from app.llm.base import DEFAULT_ROUNDING_THRESHOLD, Candidate, ExplainRow, Explanation, Location, assert_masked


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


class RuleBasedClient:
    name = "rule_based"

    def explain(
        self, rows: list[ExplainRow], rounding_threshold: int = DEFAULT_ROUNDING_THRESHOLD
    ) -> list[Explanation]:
        assert_masked(rows)
        result: list[Explanation] = []
        for row in rows:
            missing, diff = row.get("missing_in"), row.get("diff")
            if missing in ("a", "b"):
                side = missing.upper()
                result.append(
                    {
                        "id": row["id"],
                        "cause": f"missing_in_{missing}",
                        "note": f"Dòng không có ở báo cáo {side}. Kiểm tra giao dịch đã được ghi nhận ở nguồn {side} chưa.",
                        "confidence": 1.0,
                    }
                )
            elif diff is None:
                result.append(
                    {"id": row["id"], "cause": "unknown", "note": "Không đủ dữ liệu để phân loại.", "confidence": 0.0}
                )
            elif abs(diff) < rounding_threshold:
                result.append(
                    {
                        "id": row["id"],
                        "cause": "rounding",
                        "note": f"Lệch {abs(diff):,} đồng, dưới ngưỡng {rounding_threshold:,} đồng: nhiều khả năng do làm tròn.",
                        "confidence": 0.9,
                    }
                )
            else:
                result.append(
                    {
                        "id": row["id"],
                        "cause": "amount_mismatch",
                        "note": f"Lệch {abs(diff):,} đồng, vượt ngưỡng làm tròn: cần đối chiếu chứng từ gốc.",
                        "confidence": 0.9,
                    }
                )
        return result

    def locate(
        self, description: str, candidates: list[Candidate], screenshot: bytes | None = None
    ) -> Location | None:
        """Match by label text. An exact match is certain; anything else gets its similarity as confidence."""
        wanted = _normalize(description)
        best: Location | None = None
        for index, candidate in enumerate(candidates):
            name = _normalize(candidate.get("name", ""))
            if not name:
                continue
            if name == wanted:
                return {"index": index, "confidence": 1.0}
            score = SequenceMatcher(None, wanted, name).ratio()
            if best is None or score > best["confidence"]:
                best = {"index": index, "confidence": round(score, 3)}
        return best
