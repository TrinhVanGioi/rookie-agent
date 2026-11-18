"""Client for an OpenAI-compatible chat endpoint, such as vLLM serving a model on the internal network.

The model's answer is never trusted as is: it must be JSON of the expected
shape, about the rows that were asked, with a cause from the fixed list.
Anything else raises LLMError so the caller can fall back to the rules.
"""

from __future__ import annotations

import base64
import json
import re
from typing import TYPE_CHECKING, Any

from app.llm.base import (
    CAUSES,
    DEFAULT_ROUNDING_THRESHOLD,
    Candidate,
    ExplainRow,
    Explanation,
    LLMError,
    Location,
    assert_masked,
)

if TYPE_CHECKING:
    import httpx

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_CODE_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

_EXPLAIN_SCHEMA = {
    "type": "object",
    "required": ["explanations"],
    "additionalProperties": False,
    "properties": {
        "explanations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "cause", "note", "confidence"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "cause": {"enum": list(CAUSES)},
                    "note": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        }
    },
}
_LOCATE_SCHEMA = {
    "type": "object",
    "required": ["index", "confidence"],
    "additionalProperties": False,
    "properties": {
        "index": {"type": ["integer", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}

_EXPLAIN_SYSTEM = (
    "Bạn hỗ trợ giao dịch viên ngân hàng đối chiếu hai báo cáo cuối ngày A và B. "
    "Mỗi dòng lệch có: id, diff (số tiền B trừ A, null nếu thiếu dòng), missing_in (a, b hoặc null). "
    "Với mỗi dòng, chọn một nguyên nhân trong: rounding, amount_mismatch, missing_in_a, missing_in_b, unknown; "
    "viết ghi chú ngắn bằng tiếng Việt và độ tin cậy từ 0 đến 1. "
    "Chỉ trả về JSON dạng {\"explanations\": [{\"id\", \"cause\", \"note\", \"confidence\"}]}, đủ mọi id, đúng thứ tự."
)
_LOCATE_SYSTEM = (
    "Giao diện ứng dụng đã thay đổi. Cho mô tả một phần tử và danh sách phần tử ứng viên (đánh số từ 0), "
    "chọn ứng viên đúng nhất. Không chắc thì cho độ tin cậy thấp; không có ứng viên phù hợp thì index là null. "
    "Chỉ trả về JSON dạng {\"index\": số hoặc null, \"confidence\": số từ 0 đến 1}."
)


_SIM_SCHEMA = {
    "type": "object",
    "required": ["explanation"],
    "additionalProperties": False,
    "properties": {"explanation": {"type": "string"}},
}
_SIM_SYSTEM = (
    "Bạn giải thích cho nhân viên ngân hàng kết quả mô phỏng quy trình: so ban_dau với thu_nghiem (số ca xong, thời gian một ca tính bằng giây, "
    "thời gian chờ từng hàng, điểm nghẽn). Viết 2 đến 3 câu tiếng Việt, đơn giản, chỉ dùng các số đã cho. "
    "Chỉ trả về JSON dạng {\"explanation\": \"...\"}."
)


def normalize_base_url(url: str) -> str:
    """Accept the base URL with or without the `/chat/completions` suffix."""
    url = url.strip().rstrip("/")
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
    return url


class OpenAICompatClient:
    name = "openai_compat"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 60.0,
        json_schema: bool = True,
        disable_thinking: bool = True,
        vision: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        self.model = model
        self._json_schema = json_schema
        self._disable_thinking = disable_thinking
        self._vision = vision
        try:
            import httpx   # only here: a package without httpx must still start the server with the rules (rule 7)
        except ImportError as error:
            raise LLMError("Máy này thiếu thư viện httpx nên không gọi được LLM; dùng luật.") from error
        self._httpx = httpx
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(timeout=timeout, headers=headers, transport=transport)

    # ---- transport ------------------------------------------------------------------

    def _chat(self, system: str, user: Any, schema_name: str, schema: dict[str, Any]) -> Any:
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self._json_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": schema},
            }
        if self._disable_thinking:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        try:
            response = self._http.post(f"{self.base_url}/chat/completions", json=body)
        except self._httpx.HTTPError as error:
            raise LLMError(f"Không gọi được LLM tại {self.base_url}: {error}") from error
        if response.status_code != 200:
            raise LLMError(f"LLM trả mã {response.status_code}: {response.text[:300]}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise LLMError("Phản hồi của LLM không đúng định dạng chat completions.") from error
        return _parse_json(content)

    # ---- LLMClient ---------------------------------------------------------------------

    def explain(
        self, rows: list[ExplainRow], rounding_threshold: int = DEFAULT_ROUNDING_THRESHOLD
    ) -> list[Explanation]:
        assert_masked(rows)
        if not rows:
            return []
        user = json.dumps(
            {"nguong_lam_tron": rounding_threshold, "dong_lech": rows}, ensure_ascii=False
        )
        answer = self._chat(_EXPLAIN_SYSTEM, user, "explanations", _EXPLAIN_SCHEMA)
        items = answer.get("explanations") if isinstance(answer, dict) else None
        if not isinstance(items, list) or len(items) != len(rows):
            raise LLMError("LLM không trả đủ giải thích cho mọi dòng lệch.")
        result: list[Explanation] = []
        for row, item in zip(rows, items):
            if not isinstance(item, dict) or item.get("id") != row["id"]:
                raise LLMError("LLM trả giải thích cho dòng không được hỏi.")
            if item.get("cause") not in CAUSES:
                raise LLMError(f"LLM trả nguyên nhân ngoài danh sách: {item.get('cause')!r}")
            result.append(
                {
                    "id": row["id"],
                    "cause": item["cause"],
                    "note": str(item.get("note", "")),
                    "confidence": _confidence(item.get("confidence")),
                }
            )
        return result

    def explain_simulation(self, baseline: dict[str, Any], scenario: dict[str, Any], changes: dict[str, Any] | None = None) -> str:
        payload = {"ban_dau": baseline, "thu_nghiem": scenario, "thay_doi": changes or {}}
        assert_masked(payload)
        answer = self._chat(_SIM_SYSTEM, json.dumps(payload, ensure_ascii=False), "simulation_text", _SIM_SCHEMA)
        text = answer.get("explanation") if isinstance(answer, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise LLMError("LLM không trả lời giải thích kết quả mô phỏng.")
        return text.strip()

    def locate(
        self, description: str, candidates: list[Candidate], screenshot: bytes | None = None
    ) -> Location | None:
        if not candidates:
            return None
        listing = [{"index": index, **candidate} for index, candidate in enumerate(candidates)]
        assert_masked([description, listing])
        text = json.dumps({"mo_ta": description, "ung_vien": listing}, ensure_ascii=False)
        user: Any = text
        if screenshot is not None and self._vision:
            image = base64.b64encode(screenshot).decode("ascii")
            user = [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}},
            ]
        answer = self._chat(_LOCATE_SYSTEM, user, "location", _LOCATE_SCHEMA)
        if not isinstance(answer, dict):
            raise LLMError("LLM không trả object JSON.")
        index = answer.get("index")
        if index is None:
            return None
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(candidates):
            raise LLMError(f"LLM chọn ứng viên không tồn tại: {index!r}")
        return {"index": index, "confidence": _confidence(answer.get("confidence"))}


def _parse_json(content: Any) -> Any:
    if not isinstance(content, str):
        raise LLMError("LLM không trả nội dung dạng văn bản.")
    text = _THINK_BLOCK.sub("", content).strip()
    fenced = _CODE_FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise LLMError("LLM không trả JSON hợp lệ.") from error


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise LLMError(f"Độ tin cậy không hợp lệ: {value!r}")
    return float(value)
