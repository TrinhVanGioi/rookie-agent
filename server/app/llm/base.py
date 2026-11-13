"""The one interface every LLM call goes through (CLAUDE.md rule 7).

Only masked data may be passed in: discrepancy rows without account numbers,
names or amounts, and element descriptions made of labels. `assert_masked` is a
last line of defence before anything is sent to a model.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Protocol, TypedDict

Cause = Literal["rounding", "amount_mismatch", "missing_in_a", "missing_in_b", "unknown"]
CAUSES: tuple[str, ...] = ("rounding", "amount_mismatch", "missing_in_a", "missing_in_b", "unknown")
DEFAULT_ROUNDING_THRESHOLD = 1000


class ExplainRow(TypedDict):
    """One discrepancy, already masked: the key, the difference, and which side lacks the row."""

    id: str
    diff: int | None
    missing_in: Literal["a", "b"] | None


class Explanation(TypedDict):
    id: str
    cause: Cause
    note: str
    confidence: float


class Candidate(TypedDict, total=False):
    """An element on screen described by non-sensitive attributes only."""

    role: str
    name: str


class Location(TypedDict):
    index: int
    confidence: float


class LLMError(RuntimeError):
    """The model could not be reached or its answer could not be trusted."""


class UnmaskedDataError(ValueError):
    """The payload looks like it still contains sensitive values. Nothing was sent."""


class LLMClient(Protocol):
    def explain(
        self, rows: list[ExplainRow], rounding_threshold: int = DEFAULT_ROUNDING_THRESHOLD
    ) -> list[Explanation]:
        """Give a likely cause for each discrepancy row, in the same order."""
        ...

    def locate(
        self, description: str, candidates: list[Candidate], screenshot: bytes | None = None
    ) -> Location | None:
        """Pick the candidate that matches the description, with a confidence from 0 to 1.

        Returns None when nothing matches. The caller compares the confidence with
        its threshold and stops to ask the GDV when it is too low.
        """
        ...


# Account numbers, CCCD and phone numbers are runs of 10 digits or more.
_LONG_DIGITS = re.compile(r"\d{10,}")


def assert_masked(payload: Any) -> None:
    """Raise UnmaskedDataError if any string in the payload holds a long run of digits."""
    if isinstance(payload, str):
        if _LONG_DIGITS.search(payload):
            raise UnmaskedDataError("Dữ liệu gửi LLM còn chứa dãy số dài chưa che.")
    elif isinstance(payload, dict):
        for key, value in payload.items():
            assert_masked(key)
            assert_masked(value)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            assert_masked(item)
