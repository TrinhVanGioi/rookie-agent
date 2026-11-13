"""LLM access for the server. Every call goes through `LLMClient` (CLAUDE.md rule 7)."""

from app.llm.base import (
    CAUSES,
    DEFAULT_ROUNDING_THRESHOLD,
    Candidate,
    ExplainRow,
    Explanation,
    LLMClient,
    LLMError,
    Location,
    UnmaskedDataError,
    assert_masked,
)
from app.llm.factory import FallbackClient, get_llm_client
from app.llm.openai_compat import OpenAICompatClient
from app.llm.rule_based import RuleBasedClient

__all__ = [
    "CAUSES",
    "DEFAULT_ROUNDING_THRESHOLD",
    "Candidate",
    "ExplainRow",
    "Explanation",
    "FallbackClient",
    "LLMClient",
    "LLMError",
    "Location",
    "OpenAICompatClient",
    "RuleBasedClient",
    "UnmaskedDataError",
    "assert_masked",
    "get_llm_client",
]
