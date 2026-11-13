"""Assign `risk` to a recorded action with fixed rules (docs/design.md 4.3). No LLM involved."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "risk-rules.json"


@dataclass(frozen=True)
class Risk:
    level: str  # read, write or money
    human_only: bool = False  # the step must be done by a person; a workflow stops before it


READ = Risk("read")


@lru_cache
def _config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(text: str | None) -> str:
    return " ".join(unicodedata.normalize("NFC", text or "").lower().split())


def _matches(pattern: str | None, text: str) -> bool:
    return pattern is None or re.search(pattern, text, re.IGNORECASE) is not None


def _java_risk(event: dict[str, Any], config: dict[str, Any]) -> Risk:
    target = event.get("target") or {}
    if event["type"] not in ("click", "submit"):
        return READ  # typing, choosing a tab or an option changes nothing on the server side
    if event["type"] == "click" and target.get("tag") not in config["click_roles"]:
        return READ  # a click on something that is not a button or a menu item
    screen, label = _norm(event.get("url")), _norm(target.get("label"))
    for rule in config["rules"]:
        if rule.get("types") is not None and event["type"] not in rule["types"]:
            continue
        if _matches(rule.get("screen"), screen) and _matches(rule.get("label"), label):
            return Risk(rule["risk"], bool(rule.get("human_only")))
    return Risk(config["default_click"])


def _web_risk(event: dict[str, Any], config: dict[str, Any]) -> Risk:
    order = {"read": 0, "write": 1, "money": 2}
    worst = READ
    for call in event.get("api_calls") or []:
        method, path = call["method"].upper(), call["path"]
        found: Risk | None = None
        for rule in config["rules"]:
            if re.fullmatch(rule["method"], method) and re.search(rule["path"], path):
                found = Risk(rule["risk"], bool(rule.get("human_only")))
                break
        if found is None and method not in ("GET", "HEAD", "OPTIONS"):
            found = Risk(config["default_mutation"])
        if found is not None and (order[found.level], found.human_only) > (order[worst.level], worst.human_only):
            worst = found
    return worst


def risk_of(event: dict[str, Any], config_path: Path = CONFIG_PATH) -> Risk:
    config = _config(config_path)
    return _java_risk(event, config["java"]) if event["engine"] == "java" else _web_risk(event, config["web"])


def mode_for(risk: str) -> str:
    """Default control mode for a risk level. `write` and `money` always wait for approval."""
    return "auto" if risk == "read" else "approve"
