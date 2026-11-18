"""Line up several recordings of the same task, allowing steps that are not in every recording (task 4.15).

The recordings are sequences of actions on elements. Lined up with a longest-common-subsequence match, an action that every recording
has is one column; an action that only some recordings have is a column with gaps. The learner decides what a gap means (an optional
step, or a refusal); this module only lines up and says what it found. Nothing here guesses: when the same action appears in a
different order in two recordings, that is reported, not merged.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _lcs_pairs(a: list[str], b: list[str]) -> list[tuple[int, int]]:
    """The (index in a, index in b) pairs of a longest common subsequence."""
    rows, cols = len(a), len(b)
    table = [[0] * (cols + 1) for _ in range(rows + 1)]
    for i in range(rows - 1, -1, -1):
        for j in range(cols - 1, -1, -1):
            table[i][j] = table[i + 1][j + 1] + 1 if a[i] == b[j] else max(table[i + 1][j], table[i][j + 1])
    pairs: list[tuple[int, int]] = []
    i = j = 0
    while i < rows and j < cols:
        if a[i] == b[j]:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def align(runs: list[list[dict[str, Any]]], key: Callable[[dict[str, Any]], Any]) -> list[list[dict[str, Any] | None]]:
    """The columns: each is a list with one entry per recording, the event of that recording or None when it has no such action."""
    count = len(runs)
    columns: list[list[dict[str, Any] | None]] = [[event] + [None] * (count - 1) for event in runs[0]]
    for number in range(1, count):
        master_keys = [str(key(next(c for c in column if c is not None))) for column in columns]
        run_keys = [str(key(event)) for event in runs[number]]
        pairs = _lcs_pairs(master_keys, run_keys) + [(len(columns), len(runs[number]))]
        merged: list[list[dict[str, Any] | None]] = []
        taken, used = 0, 0
        for master_index, run_index in pairs:
            while taken < master_index:
                merged.append(columns[taken])
                taken += 1
            while used < run_index:
                fresh: list[dict[str, Any] | None] = [None] * count
                fresh[number] = runs[number][used]
                merged.append(fresh)
                used += 1
            if master_index < len(columns):
                columns[master_index][number] = runs[number][run_index]
                merged.append(columns[master_index])
                taken, used = master_index + 1, run_index + 1
        columns = merged
    return columns


def present(column: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
    return [event for event in column if event is not None]


def reordered(columns: list[list[dict[str, Any] | None]], key: Callable[[dict[str, Any]], Any]) -> list[tuple[Any, int, int]]:
    """Actions that two recordings both did, but in a different order: (key, one recording, the other). They do not line up in the
    same column, so each shows as a step of its own; a person must decide, the learner does not."""
    where: dict[str, list[tuple[int, set[int]]]] = {}
    for index, column in enumerate(columns):
        events = present(column)
        marker = str(key(events[0]))
        where.setdefault(marker, []).append((index, {i for i, e in enumerate(column) if e is not None}))
    found: list[tuple[Any, int, int]] = []
    for marker, places in where.items():
        if len(places) < 2:
            continue
        for first in range(len(places)):
            for second in range(first + 1, len(places)):
                one, other = places[first][1], places[second][1]
                if one.isdisjoint(other) and len(one) + len(other) >= 2:
                    found.append((marker, min(one), min(other)))
    return found
