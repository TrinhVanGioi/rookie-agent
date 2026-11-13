"""Try the configured model with synthetic, masked data and compare it with the rules.

    cd server
    $env:ROOKIE_LLM_BASE_URL = "http://node:port/v1"
    $env:ROOKIE_LLM_MODEL = "<tên model đang serve>"
    python -m app.llm.check
"""

from __future__ import annotations

import sys
import time

from app.llm import FallbackClient, LLMError, RuleBasedClient, get_llm_client

ROWS = [
    {"id": "GD20261110-0003", "diff": 350, "missing_in": None},
    {"id": "GD20261110-0007", "diff": -125000, "missing_in": None},
    {"id": "GD20261110-0011", "diff": None, "missing_in": "b"},
    {"id": "GD20261110-0015", "diff": None, "missing_in": "a"},
]
CANDIDATES = [
    {"role": "push button", "name": "Tra cứu"},
    {"role": "push button", "name": "Xuất CSV"},
    {"role": "text", "name": "Ngày báo cáo"},
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    client = get_llm_client()
    if not isinstance(client, FallbackClient):
        print("Chưa đặt ROOKIE_LLM_BASE_URL: server đang dùng RuleBasedClient (offline).")
        return 0
    model = client.primary
    rules = RuleBasedClient()
    print(f"Model: {model.model} tại {model.base_url}")
    failed = False

    started = time.monotonic()
    try:
        answers = model.explain(ROWS)
    except LLMError as error:
        print(f"[LỖI] explain: {error}")
        failed = True
    else:
        expected = [row["cause"] for row in rules.explain(ROWS)]
        agree = sum(a["cause"] == e for a, e in zip(answers, expected))
        print(f"[OK] explain: {time.monotonic() - started:.1f} giây, khớp luật {agree}/{len(ROWS)} dòng")
        for answer in answers:
            print(f"   {answer['id']}: {answer['cause']} ({answer['confidence']:.2f}) {answer['note']}")

    started = time.monotonic()
    try:
        location = model.locate("nút Tìm kiếm báo cáo", CANDIDATES)
    except LLMError as error:
        print(f"[LỖI] locate: {error}")
        failed = True
    else:
        picked = CANDIDATES[location["index"]]["name"] if location else "không chọn"
        print(f"[OK] locate: {time.monotonic() - started:.1f} giây, chọn {picked!r} (mong đợi 'Tra cứu')")

    if failed:
        print("Khi model lỗi, server tự dùng luật thay thế. Thử đặt ROOKIE_LLM_JSON_SCHEMA=0 nếu lỗi do response_format.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
