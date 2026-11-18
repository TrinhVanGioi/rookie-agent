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
    if document.get("schema_version", 0) < 3:
        used = [step["id"] for step in document["steps"] if "optional" in step] + [i["name"] for i in document["inputs"] if "required" in i]
        if used:
            raise SchemaError("workflow không hợp lệ: optional và required chỉ có từ schema_version 3 (" + ", ".join(used) + ")")
    if document.get("schema_version", 0) < 3 and any(step.get("action") == "read_fields" for step in document["steps"]):
        raise SchemaError("workflow không hợp lệ: read_fields chỉ có từ schema_version 3")
    optional_inputs = {i["name"] for i in document["inputs"] if i.get("required") is False}
    if optional_inputs:
        import re
        for step in document["steps"]:
            names = set(re.findall(r"\{([a-z][a-z0-9_]*)\}", step.get("value") or ""))
            if names & optional_inputs and (step.get("optional") or {}).get("mode") != "if_different":
                raise SchemaError(f"workflow không hợp lệ: bước {step['id']} dùng đầu vào không bắt buộc nhưng không phải bước optional if_different")


def validate_trace(document: Any) -> None:
    """A trace is the masked raw record of several sessions, the input of the LLM that designs a workflow.
    Beyond the schema: event ids are unique, and every event points to an element the trace describes."""
    _validate("trace", document)
    seen: set[str] = set()
    for session in document["sessions"]:
        for el_id in session.get("initial", {}):
            if el_id not in document["elements"]:
                raise SchemaError(f"trace không hợp lệ: initial trỏ tới phần tử {el_id} không có trong elements")
        for event in session["events"]:
            if event["eid"] in seen:
                raise SchemaError(f"trace không hợp lệ: eid {event['eid']} xuất hiện hai lần")
            seen.add(event["eid"])
            if event["el_id"] is not None and event["el_id"] not in document["elements"]:
                raise SchemaError(f"trace không hợp lệ: {event['eid']} trỏ tới phần tử {event['el_id']} không có trong elements")
