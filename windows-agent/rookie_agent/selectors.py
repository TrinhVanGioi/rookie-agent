"""Selectors for Java components (docs/design.md 3B).

A component is described by its place in the accessible tree, never by screen
coordinates. Two selector forms, in priority order:

    role=push button[name='Gửi duyệt']      role plus accessible name
    path=frame/root pane[0]/.../text[1]     roles and child indexes from the window
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    """One level of the accessible tree: the role and the index among its siblings."""

    role: str
    index: int


@dataclass(frozen=True)
class Element:
    """A component as the recorder sees it. `path` runs from the window down to the component."""

    role: str
    name: str
    path: tuple[Step, ...]
    window: str

    @property
    def key(self) -> str:
        """Identity of the component within its window."""
        return path_selector(self.path)


def _quote(name: str) -> str:
    return name.replace("\\", "\\\\").replace("'", "\\'")


def role_selector(role: str, name: str) -> str:
    return f"role={role}[name='{_quote(name)}']"


def path_selector(path: tuple[Step, ...]) -> str:
    parts = [path[0].role] + [f"{step.role}[{step.index}]" for step in path[1:]]
    return "path=" + "/".join(parts)


def selectors_for(element: Element) -> list[str]:
    """Selectors for an element, most stable first."""
    result = []
    if element.name.strip():
        result.append(role_selector(element.role, element.name))
    result.append(path_selector(element.path))
    return result


_ROLE_PATTERN = re.compile(r"^role=(?P<role>[^\[]+)\[name='(?P<name>(?:[^'\\]|\\.)*)'\]$")
_STEP_PATTERN = re.compile(r"^(?P<role>[^\[]+)\[(?P<index>\d+)\]$")


def parse_role_selector(selector: str) -> tuple[str, str] | None:
    """Return (role, name) for a `role=` selector, or None for any other form."""
    match = _ROLE_PATTERN.match(selector)
    if match is None:
        return None
    return match["role"], re.sub(r"\\(.)", r"\1", match["name"])


def parse_path_selector(selector: str) -> tuple[Step, ...] | None:
    """Return the steps of a `path=` selector, or None for any other form."""
    if not selector.startswith("path="):
        return None
    parts = selector[len("path="):].split("/")
    steps = [Step(parts[0], -1)]
    for part in parts[1:]:
        match = _STEP_PATTERN.match(part)
        if match is None:
            return None
        steps.append(Step(match["role"], int(match["index"])))
    return tuple(steps)
