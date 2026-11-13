"""Validate events and workflows against the JSON Schemas in `schemas/`.

The schemas are the contract between extension, Windows agent and server.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


class SchemaError(ValueError):
    """The document does not match its schema. The message lists every problem."""


@lru_cache
def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _validate(name: str, document: Any) -> None:
    errors = sorted(_validator(name).iter_errors(document), key=lambda e: list(e.absolute_path))
    if errors:
        lines = [f"{'/'.join(str(part) for part in e.absolute_path) or '(root)'}: {e.message}" for e in errors]
        raise SchemaError(f"{name} không hợp lệ: " + "; ".join(lines))


def validate_event(document: Any) -> None:
    _validate("event", document)


def validate_workflow(document: Any) -> None:
    _validate("workflow", document)
