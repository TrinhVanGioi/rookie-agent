"""Which steps are write only by default (docs/design.md 6.4 point 4).

The server gives a step `write` when no rule of `config/risk-rules.json` (section "ie") matches its label and screen: the click is
unknown, so it is taken as a change. The agent reads the same rules (they travel with it in `config\\`) to tell that case from a
step an explicit `write` rule matched. Only the first may be asked of the teller as «chỉ xem?». Any doubt (no file, a broken file,
a step that is not a click) answers "no": the agent never asks and the step is refused as before.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from rookie_agent.classify import CONFIG_PATH as _FIELD_CLASSES

RULES_PATH = _FIELD_CLASSES.parent / "risk-rules.json"


def load(path: Path = RULES_PATH) -> dict[str, Any] | None:
    """The "ie" section of the rules, or None when the agent cannot read it."""
    try:
        section = json.loads(path.read_text(encoding="utf-8"))["ie"]
        if section["default_click"] == "write" and isinstance(section["rules"], list) and isinstance(section["click_roles"], list):
            return section
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _norm(text: str | None) -> str:
    return " ".join(unicodedata.normalize("NFC", text or "").lower().split())


def _matches(pattern: str | None, text: str) -> bool:
    return pattern is None or re.search(pattern, text, re.IGNORECASE) is not None


def write_by_default(step: dict[str, Any], rules: dict[str, Any] | None) -> bool:
    """True when the step is `write` and no rule of the section matched it, judged as the server does (`risk._java_risk`)."""
    if rules is None or step.get("risk") != "write" or step.get("action") not in ("click", "submit"):
        return False
    target = step.get("target") or {}
    kind = str(step["action"])
    if kind == "click" and target.get("tag") not in rules["click_roles"]:
        return False                       # not a button or a link: the server would have said read, so this is not the default case
    screen, label = _norm(step.get("url")), _norm(target.get("label"))
    try:
        for rule in rules["rules"]:
            if rule.get("types") is not None and kind not in rule["types"]:
                continue
            if _matches(rule.get("screen"), screen) and _matches(rule.get("label"), label):
                return False               # a rule matched, whatever its risk: it is not the default
    except (re.error, TypeError, KeyError):
        return False
    return True
