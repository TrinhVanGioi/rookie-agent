"""SQLite storage for recorded sessions, workflow versions and sandbox runs."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    engine TEXT NOT NULL,
    created_at TEXT NOT NULL,
    events TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflows (
    id TEXT NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL,
    document TEXT NOT NULL,
    warnings TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (id, version)
);
CREATE TABLE IF NOT EXISTS test_runs (
    workflow_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    ok INTEGER NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


class Storage:
    def __init__(self, path: str | Path) -> None:
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    # ---- sessions -----------------------------------------------------------------

    def add_session(self, session_id: str, engine: str, events: list[dict[str, Any]]) -> bool:
        """Store a session. Returns False when the id already exists."""
        with self._lock, self._db:
            try:
                self._db.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?)", (session_id, engine, _now(), _dump(events))
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        return {
            "session_id": row["id"],
            "engine": row["engine"],
            "created_at": row["created_at"],
            "events": json.loads(row["events"]),
        }

    def list_sessions(self, engine: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT id, engine, created_at, json_array_length(events) AS n FROM sessions"
        args: tuple = ()
        if engine:
            query, args = query + " WHERE engine = ?", (engine,)
        with self._lock:
            rows = self._db.execute(query + " ORDER BY created_at, id", args).fetchall()
        return [
            {"session_id": r["id"], "engine": r["engine"], "created_at": r["created_at"], "event_count": r["n"]}
            for r in rows
        ]

    # ---- workflows ----------------------------------------------------------------

    def next_version(self, workflow_id: str) -> int:
        with self._lock:
            row = self._db.execute("SELECT MAX(version) AS v FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        return (row["v"] or 0) + 1

    def add_workflow(self, workflow: dict[str, Any], warnings: list[str]) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO workflows VALUES (?, ?, ?, ?, ?, ?)",
                (workflow["id"], workflow["version"], workflow["status"], _dump(workflow), _dump(warnings), _now()),
            )

    def get_workflow(
        self, workflow_id: str, version: int | None = None, status: str | None = None
    ) -> tuple[dict[str, Any], list[str]] | None:
        """A specific version, or the latest one (optionally the latest with a given status)."""
        query, args = "SELECT * FROM workflows WHERE id = ?", [workflow_id]
        if version is not None:
            query, args = query + " AND version = ?", args + [version]
        if status is not None:
            query, args = query + " AND status = ?", args + [status]
        with self._lock:
            row = self._db.execute(query + " ORDER BY version DESC LIMIT 1", args).fetchone()
        if row is None:
            return None
        return json.loads(row["document"]), json.loads(row["warnings"])

    def list_workflows(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, version, status, created_at, json_extract(document, '$.engine') AS engine "
                "FROM workflows ORDER BY id, version"
            ).fetchall()
        return [dict(row) for row in rows]

    def set_status(self, workflow_id: str, version: int, status: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE workflows SET status = ?, document = json_set(document, '$.status', ?) "
                "WHERE id = ? AND version = ?",
                (status, status, workflow_id, version),
            )

    # ---- sandbox runs ---------------------------------------------------------------

    def add_test_run(self, workflow_id: str, version: int, ok: bool, result: dict[str, Any]) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO test_runs VALUES (?, ?, ?, ?, ?)", (workflow_id, version, int(ok), _dump(result), _now())
            )

    def has_passed_test_run(self, workflow_id: str, version: int) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM test_runs WHERE workflow_id = ? AND version = ? AND ok = 1 LIMIT 1",
                (workflow_id, version),
            ).fetchone()
        return row is not None
