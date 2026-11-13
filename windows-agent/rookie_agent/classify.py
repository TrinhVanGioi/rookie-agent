"""Decide how a field's value may be stored (docs/design.md 4.2).

`ignore`: no event at all (passwords, OTP). `sensitive`: the event keeps only
the class of the field, never the value. `plain`: the value is kept so the
Learner can compare recordings. Anything unknown is sensitive.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "field-classes.json"

Kind = Literal["ignore", "sensitive", "plain"]


@dataclass(frozen=True)
class FieldClass:
    kind: Kind
    value_class: str | None = None


@dataclass(frozen=True)
class _Config:
    default: FieldClass
    ignore_roles: frozenset[str]
    rules: tuple[tuple[re.Pattern[str], FieldClass], ...]


@lru_cache
def _load(path: Path) -> _Config:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rules = tuple(
        (re.compile(rule["pattern"], re.IGNORECASE), FieldClass(rule["kind"], rule.get("value_class")))
        for rule in raw["rules"]
    )
    default = FieldClass(raw["default"]["kind"], raw["default"].get("value_class"))
    return _Config(default, frozenset(raw.get("ignore_roles", [])), rules)


def normalize(label: str) -> str:
    return " ".join(unicodedata.normalize("NFC", label).lower().split())


def classify(label: str, role: str = "", config_path: Path = CONFIG_PATH) -> FieldClass:
    """Classify a field by its accessible role and its label or name."""
    config = _load(config_path)
    if role in config.ignore_roles:
        return FieldClass("ignore")
    text = normalize(label)
    for pattern, field_class in config.rules:
        if pattern.search(text):
            return field_class
    return config.default
