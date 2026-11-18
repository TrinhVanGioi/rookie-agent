"""Choose the LLM client from the environment.

    ROOKIE_LLM_BASE_URL          e.g. http://node:8000/v1  (unset: rules only, fully offline)
    ROOKIE_LLM_MODEL             model name as served, required with the URL
    ROOKIE_LLM_API_KEY           optional
    ROOKIE_LLM_TIMEOUT           seconds, default 60
    ROOKIE_LLM_JSON_SCHEMA       0 to stop sending response_format (default 1)
    ROOKIE_LLM_DISABLE_THINKING  0 to let the model think (default 1)
    ROOKIE_LLM_VISION            1 if the model accepts images (default 0)
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from app.llm.base import (
    DEFAULT_ROUNDING_THRESHOLD,
    Candidate,
    ExplainRow,
    Explanation,
    LLMClient,
    LLMError,
    Location,
)
from app.llm.openai_compat import OpenAICompatClient
from app.llm.rule_based import RuleBasedClient


class FallbackClient:
    """Ask the model first; on LLMError use the rules. Unmasked data is never retried: it is refused."""

    name = "fallback"

    def __init__(self, primary: OpenAICompatClient, fallback: RuleBasedClient) -> None:
        self.primary = primary
        self.fallback = fallback
        self.last_error: LLMError | None = None

    def explain(
        self, rows: list[ExplainRow], rounding_threshold: int = DEFAULT_ROUNDING_THRESHOLD
    ) -> list[Explanation]:
        try:
            return self.primary.explain(rows, rounding_threshold)
        except LLMError as error:
            self.last_error = error
            return self.fallback.explain(rows, rounding_threshold)

    def locate(
        self, description: str, candidates: list[Candidate], screenshot: bytes | None = None
    ) -> Location | None:
        try:
            return self.primary.locate(description, candidates, screenshot)
        except LLMError as error:
            self.last_error = error
            return self.fallback.locate(description, candidates, screenshot)


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    value = env.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


def get_llm_client(env: Mapping[str, str] | None = None) -> LLMClient:
    env = os.environ if env is None else env
    base_url = env.get("ROOKIE_LLM_BASE_URL", "").strip()
    if not base_url:
        return RuleBasedClient()
    model = env.get("ROOKIE_LLM_MODEL", "").strip()
    if not model:
        raise ValueError("Đã đặt ROOKIE_LLM_BASE_URL thì phải đặt ROOKIE_LLM_MODEL (tên model đang serve).")
    try:
        primary = OpenAICompatClient(
            base_url=base_url,
            model=model,
            api_key=env.get("ROOKIE_LLM_API_KEY") or None,
            timeout=float(env.get("ROOKIE_LLM_TIMEOUT", "60")),
            json_schema=_flag(env, "ROOKIE_LLM_JSON_SCHEMA", True),
            disable_thinking=_flag(env, "ROOKIE_LLM_DISABLE_THINKING", True),
            vision=_flag(env, "ROOKIE_LLM_VISION", False),
        )
    except LLMError:   # no httpx in this package: the rules still work offline
        return RuleBasedClient()
    return FallbackClient(primary, RuleBasedClient())
