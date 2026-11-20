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
    if document.get("schema_version", 0) < 4:
        adaptive = [step["id"] for step in document["steps"] if {"intent", "expect", "adapt"} & set(step)]
        if adaptive:
            raise SchemaError("workflow không hợp lệ: intent, expect và adapt chỉ có từ schema_version 4 (" + ", ".join(adaptive) + ")")
    if document.get("schema_version", 0) < 3 and any(step.get("action") == "read_fields" for step in document["steps"]):
        raise SchemaError("workflow không hợp lệ: read_fields chỉ có từ schema_version 3")
    optional_inputs = {i["name"] for i in document["inputs"] if i.get("required") is False}
    if optional_inputs:
        import re
        for step in document["steps"]:
            names = set(re.findall(r"\{([a-z][a-z0-9_]*)\}", step.get("value") or ""))
            if names & optional_inputs and (step.get("optional") or {}).get("mode") != "if_different":
                raise SchemaError(f"workflow không hợp lệ: bước {step['id']} dùng đầu vào không bắt buộc nhưng không phải bước optional if_different")


def validate_api_nodes(document: Any) -> None:
    """The API nodes of a flow as the server keeps them (task 10.3). Beyond the schema: ids unique. (A link may point to a node that
    is not in the flow: the node then lists that name in `unresolved` and does not run.)"""
    _validate("api-nodes", document)
    ids = [node["id"] for node in document]
    if len(set(ids)) != len(ids):
        raise SchemaError("api-nodes không hợp lệ: id nút bị trùng")


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


def validate_process(document: Any) -> None:
    """A process model: stages (each one workflow, with a role) and the handoffs between them."""
    _validate("process", document)
    ids = [stage["id"] for stage in document["stages"]]
    if len(set(ids)) != len(ids):
        raise SchemaError("process không hợp lệ: id chặng bị trùng")
    for handoff in document["handoffs"]:
        for end in (handoff["from_stage"], handoff["to_stage"]):
            if end not in ids:
                raise SchemaError(f"process không hợp lệ: điểm bàn giao trỏ tới chặng {end} không có")


@lru_cache
def _log_row_validator() -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / "process.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/log_row"})


def validate_log_row(document: Any) -> None:
    errors = sorted(_log_row_validator().iter_errors(document), key=lambda e: list(e.absolute_path))
    if errors:
        raise SchemaError("dòng nhật ký không hợp lệ: " + "; ".join(e.message for e in errors))
