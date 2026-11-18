import json
from pathlib import Path

import pytest

from app.schemas import SchemaError, validate_event, validate_log_row, validate_process, validate_trace, validate_workflow

EXAMPLES = Path(__file__).resolve().parents[2] / "schemas" / "examples"


def _examples(kind: str) -> list[Path]:
    return sorted((EXAMPLES / kind).glob("*.json"))


def _validate(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    if path.name.startswith("event-"):
        validate_event(document)
    elif path.name.startswith("process-"):
        validate_process(document)
    elif path.name.startswith("logrow-"):
        validate_log_row(document)
    elif path.name.startswith("trace-"):
        validate_trace(document)
    else:
        validate_workflow(document)


def test_examples_exist_for_both_engines():
    names = {path.name for path in _examples("valid")}
    assert {"event-web-click.json", "event-java-click.json", "workflow-web.json", "workflow-java.json"} <= names
    assert len(_examples("invalid")) >= 10


@pytest.mark.parametrize("path", _examples("valid"), ids=lambda p: p.stem)
def test_valid_examples_pass(path):
    _validate(path)


@pytest.mark.parametrize("path", _examples("invalid"), ids=lambda p: p.stem)
def test_invalid_examples_are_rejected(path):
    with pytest.raises(SchemaError):
        _validate(path)


def test_error_message_names_the_failing_field():
    document = json.loads((EXAMPLES / "valid" / "workflow-web.json").read_text(encoding="utf-8"))
    document["steps"][0]["risk"] = "danger"
    with pytest.raises(SchemaError) as error:
        validate_workflow(document)
    assert "steps/0/risk" in str(error.value)
