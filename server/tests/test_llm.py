import json

import httpx
import pytest

from app.llm import (
    FallbackClient,
    LLMError,
    OpenAICompatClient,
    RuleBasedClient,
    UnmaskedDataError,
    assert_masked,
    get_llm_client,
)

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


def vllm(handler) -> OpenAICompatClient:
    """A client wired to an in-process fake of the vLLM endpoint. No network."""
    return OpenAICompatClient(
        base_url="http://node:8000/v1", model="qwen", transport=httpx.MockTransport(handler)
    )


def chat_reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


# ---- RuleBasedClient: offline ----------------------------------------------------------


def test_rule_based_explains_each_kind_of_discrepancy():
    result = RuleBasedClient().explain(ROWS, rounding_threshold=1000)
    assert [(r["id"], r["cause"]) for r in result] == [
        ("GD20261110-0003", "rounding"),
        ("GD20261110-0007", "amount_mismatch"),
        ("GD20261110-0011", "missing_in_b"),
        ("GD20261110-0015", "missing_in_a"),
    ]
    assert all(0 <= r["confidence"] <= 1 and r["note"] for r in result)


def test_rule_based_threshold_is_a_parameter():
    assert RuleBasedClient().explain(ROWS[:1], rounding_threshold=100)[0]["cause"] == "amount_mismatch"


def test_rule_based_locates_by_label():
    client = RuleBasedClient()
    exact = client.locate("Xuất CSV", CANDIDATES)
    assert exact == {"index": 1, "confidence": 1.0}
    close = client.locate("nút Tra cứu", CANDIDATES)
    assert close["index"] == 0 and 0.5 < close["confidence"] < 1.0


def test_rule_based_gives_low_confidence_instead_of_guessing():
    result = RuleBasedClient().locate("Phê duyệt lệnh", CANDIDATES)
    assert result is None or result["confidence"] < 0.6
    assert RuleBasedClient().locate("Tra cứu", []) is None


# ---- masking guard -------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["001012345678", "tk 970412345678 lệch", {"note": ["0912345678"]}])
def test_unmasked_long_digit_runs_are_refused(value):
    with pytest.raises(UnmaskedDataError):
        assert_masked({"rows": [value]})


def test_masked_rows_pass():
    assert_masked(ROWS)
    assert_masked({"account": "{tai_khoan}", "amount": "***", "diff": -125000})


def test_vllm_client_never_sends_unmasked_data():
    calls = []

    def handler(request):
        calls.append(request)
        return chat_reply("{}")

    with pytest.raises(UnmaskedDataError):
        vllm(handler).explain([{"id": "GD1", "diff": 5, "missing_in": None, "account": "001012345678"}])
    assert calls == []


# ---- OpenAICompatClient against a fake vLLM ------------------------------------------------


def test_vllm_explain_posts_to_chat_completions_and_parses_json():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        answer = {"explanations": [
            {"id": row["id"], "cause": "rounding", "note": "Lệch do làm tròn", "confidence": 0.9} for row in ROWS
        ]}
        return chat_reply(json.dumps(answer, ensure_ascii=False))

    result = vllm(handler).explain(ROWS, rounding_threshold=1000)
    assert seen["url"] == "http://node:8000/v1/chat/completions"
    assert seen["body"]["model"] == "qwen"
    assert seen["body"]["response_format"]["type"] == "json_schema"
    assert "GD20261110-0003" in seen["body"]["messages"][-1]["content"]
    assert [r["id"] for r in result] == [row["id"] for row in ROWS]


def test_vllm_reply_with_thinking_block_and_code_fence_is_still_parsed():
    content = '<think>để xem nào</think>\n```json\n{"index": 0, "confidence": 0.8}\n```'
    assert vllm(lambda request: chat_reply(content)).locate("Tra cứu", CANDIDATES) == {"index": 0, "confidence": 0.8}


def test_vllm_api_key_is_sent_only_when_set():
    headers = {}

    def handler(request):
        headers.update(request.headers)
        return chat_reply('{"index": 0, "confidence": 0.8}')

    vllm(handler).locate("Tra cứu", CANDIDATES)
    assert "authorization" not in headers
    client = OpenAICompatClient("http://node:8000/v1", "qwen", api_key="k", transport=httpx.MockTransport(handler))
    client.locate("Tra cứu", CANDIDATES)
    assert headers["authorization"] == "Bearer k"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="boom"),
        chat_reply("xin lỗi, tôi không chắc"),
        chat_reply('{"explanations": [{"id": "GD-khac", "cause": "rounding", "note": "x", "confidence": 0.9}]}'),
        chat_reply('{"explanations": [{"id": "GD20261110-0003", "cause": "bịa", "note": "x", "confidence": 0.9}]}'),
        chat_reply('{"explanations": [{"id": "GD20261110-0003", "cause": "rounding", "note": "x", "confidence": 7}]}'),
        httpx.Response(200, json={"unexpected": True}),
    ],
)
def test_vllm_bad_answers_raise_llm_error(response):
    with pytest.raises(LLMError):
        vllm(lambda request: response).explain(ROWS[:1])


def test_vllm_locate_rejects_an_index_out_of_range():
    with pytest.raises(LLMError):
        vllm(lambda request: chat_reply('{"index": 9, "confidence": 0.9}')).locate("Tra cứu", CANDIDATES)


def test_vllm_locate_null_index_means_not_found():
    client = vllm(lambda request: chat_reply('{"index": null, "confidence": 0.0}'))
    assert client.locate("Tra cứu", CANDIDATES) is None


def test_vllm_connection_error_is_llm_error():
    def handler(request):
        raise httpx.ConnectError("no route to host")

    with pytest.raises(LLMError):
        vllm(handler).explain(ROWS[:1])


# ---- fallback and factory --------------------------------------------------------------------


def test_fallback_uses_rules_when_the_model_fails():
    client = FallbackClient(vllm(lambda request: httpx.Response(503)), RuleBasedClient())
    result = client.explain(ROWS, rounding_threshold=1000)
    assert [r["cause"] for r in result] == ["rounding", "amount_mismatch", "missing_in_b", "missing_in_a"]
    assert client.last_error is not None


def test_fallback_does_not_hide_unmasked_data():
    client = FallbackClient(vllm(lambda request: chat_reply("{}")), RuleBasedClient())
    with pytest.raises(UnmaskedDataError):
        client.explain([{"id": "GD1", "diff": 1, "missing_in": None, "note": "001012345678"}])


def test_factory_defaults_to_rules_and_reads_the_environment():
    assert isinstance(get_llm_client({}), RuleBasedClient)
    client = get_llm_client(
        {"ROOKIE_LLM_BASE_URL": "http://node:8000/v1/chat/completions", "ROOKIE_LLM_MODEL": "qwen"}
    )
    assert isinstance(client, FallbackClient)
    assert client.primary.base_url == "http://node:8000/v1"
    assert client.primary.model == "qwen"


def test_factory_requires_a_model_name():
    with pytest.raises(ValueError):
        get_llm_client({"ROOKIE_LLM_BASE_URL": "http://node:8000/v1"})
