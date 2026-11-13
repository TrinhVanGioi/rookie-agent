import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def event_validator() -> Draft202012Validator:
    schema = json.loads((REPO / "schemas" / "event.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


@pytest.fixture
def assert_valid_events(event_validator):
    def check(events: list[dict]) -> None:
        for event in events:
            errors = [error.message for error in event_validator.iter_errors(event)]
            assert not errors, f"event {event.get('seq')} sai schema: {errors}"
        assert [event["seq"] for event in events] == list(range(len(events)))

    return check
