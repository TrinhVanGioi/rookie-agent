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
CREATE TABLE IF NOT EXISTS learn_sources (
    workflow_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    session_ids TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (workflow_id, version)
);
CREATE TABLE IF NOT EXISTS process_models (
    id TEXT NOT NULL,
    version INTEGER NOT NULL,
    document TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (id, version)
);
CREATE TABLE IF NOT EXISTS workflow_meta (
    id TEXT PRIMARY KEY,
    owner TEXT,
    owner_display TEXT,
    unit TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'private',
    shared_at TEXT,
    cloned_from TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_api (
    id TEXT NOT NULL,
    version INTEGER NOT NULL,
    api TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (id, version)
);
CREATE TABLE IF NOT EXISTS auth_tokens (
    hash TEXT PRIMARY KEY,
    user TEXT NOT NULL,
    kind TEXT NOT NULL,
    expires_at REAL NOT NULL
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
            have = {row["name"] for row in self._db.execute("PRAGMA table_info(sessions)")}
            for column, kind in (("role", "TEXT"), ("case_key", "TEXT"), ("synthetic", "INTEGER NOT NULL DEFAULT 0"), ("owner", "TEXT")):
                if column not in have:   # a database made before Gate 9 (role, case_key, synthetic) or Gate 10 (owner)
                    self._db.execute(f"ALTER TABLE sessions ADD COLUMN {column} {kind}")

    def close(self) -> None:
        self._db.close()

    # ---- sessions -----------------------------------------------------------------

    def add_session(
        self,
        session_id: str,
        engine: str,
        events: list[dict[str, Any]],
        role: str | None = None,
        case_key: str | None = None,
        synthetic: bool = False,
        owner: str | None = None,
    ) -> bool:
        """Store a session. Returns False when the id already exists. `case_key` is already a hash made on the PC."""
        with self._lock, self._db:
            try:
                self._db.execute(
                    "INSERT INTO sessions (id, engine, created_at, events, role, case_key, synthetic, owner) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (session_id, engine, _now(), _dump(events), role, case_key, int(synthetic), owner),
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
            "role": row["role"],
            "case_key": row["case_key"],
            "synthetic": bool(row["synthetic"]),
            "owner": row["owner"],
        }

    def list_sessions(self, engine: str | None = None, owner: str | None = None) -> list[dict[str, Any]]:
        """`owner`: only the sessions of that person (None: all of them, for the admin or with login off)."""
        query, where, args = "SELECT id, engine, created_at, json_array_length(events) AS n FROM sessions", [], []
        if engine:
            where, args = where + ["engine = ?"], args + [engine]
        if owner is not None:
            where, args = where + ["owner = ?"], args + [owner]
        if where:
            query += " WHERE " + " AND ".join(where)
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
                "SELECT w.id, w.version, w.status, w.created_at, json_extract(w.document, '$.engine') AS engine, "
                "json_extract(w.document, '$.title') AS title, m.owner, m.owner_display, COALESCE(m.unit, '') AS unit, "
                "COALESCE(m.visibility, 'private') AS visibility, m.cloned_from "
                "FROM workflows w LEFT JOIN workflow_meta m ON m.id = w.id ORDER BY w.id, w.version"
            ).fetchall()
        return [dict(row) for row in rows]

    # ---- the API nodes of a version (task 10.3): masked templates; the full ones stay on the PC ----------------------------

    def set_api(self, workflow_id: str, version: int, api: list[dict[str, Any]]) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO workflow_api VALUES (?, ?, ?, ?)", (workflow_id, version, _dump(api), _now()))

    def get_api(self, workflow_id: str, version: int) -> list[dict[str, Any]] | None:
        with self._lock:
            row = self._db.execute("SELECT api FROM workflow_api WHERE id = ? AND version = ?", (workflow_id, version)).fetchone()
        return json.loads(row["api"]) if row else None

    # ---- whose flow it is and who sees it (task 10.2) ----------------------------------------------------------------

    def meta(self, workflow_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute("SELECT * FROM workflow_meta WHERE id = ?", (workflow_id,)).fetchone()
        if row is None:     # learned before Gate 10: no owner
            return {"id": workflow_id, "owner": None, "owner_display": None, "unit": "", "visibility": "private", "cloned_from": None}
        return dict(row)

    def set_owner(self, workflow_id: str, owner: str, owner_display: str, unit: str, cloned_from: str | None = None) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO workflow_meta (id, owner, owner_display, unit, cloned_from, created_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET owner = excluded.owner, owner_display = excluded.owner_display, unit = excluded.unit",
                (workflow_id, owner, owner_display, unit, cloned_from, _now()),
            )

    def set_visibility(self, workflow_id: str, visibility: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE workflow_meta SET visibility = ?, shared_at = ? WHERE id = ?", (visibility, _now(), workflow_id))

    def forget_owner(self, workflow_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM workflow_meta WHERE id = ?", (workflow_id,))

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

    # ---- which sessions a workflow was learned from ------------------------------------

    def add_learn_sources(self, workflow_id: str, version: int, session_ids: list[str]) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO learn_sources VALUES (?, ?, ?, ?)", (workflow_id, version, _dump(session_ids), _now())
            )

    def learn_sources(self) -> list[tuple[str, int, list[str]]]:
        """(workflow id, version, session ids), oldest first."""
        with self._lock:
            rows = self._db.execute("SELECT * FROM learn_sources ORDER BY created_at, rowid").fetchall()
        return [(r["workflow_id"], r["version"], json.loads(r["session_ids"])) for r in rows]

    def all_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            ids = [r["id"] for r in self._db.execute("SELECT id FROM sessions ORDER BY created_at, id")]
        return [s for s in (self.get_session(i) for i in ids) if s is not None]

    def agent_run_ms(self, workflow_id: str) -> dict[str, list[float]]:
        """Measured agent run time per step id, from passed sandbox runs whose step records carry a duration in ms."""
        with self._lock:
            rows = self._db.execute("SELECT result FROM test_runs WHERE workflow_id = ? AND ok = 1", (workflow_id,)).fetchall()
        found: dict[str, list[float]] = {}
        for row in rows:
            for step in json.loads(row["result"]).get("steps") or []:
                ms = next((step[k] for k in ("duration_ms", "ms", "elapsed_ms") if isinstance(step.get(k), (int, float))), None)
                step_id = step.get("id") or step.get("step_id")
                if ms is not None and step_id:
                    found.setdefault(step_id, []).append(float(ms))
        return found

    # ---- login tokens (task 10.1): only the SHA-256 of a token is kept -------------------------------------------------------

    def add_token(self, token_hash: str, user: dict[str, Any], kind: str, expires_at: float) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO auth_tokens VALUES (?, ?, ?, ?)", (token_hash, _dump(user), kind, expires_at))

    def get_token(self, token_hash: str) -> tuple[dict[str, Any], str, float] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM auth_tokens WHERE hash = ?", (token_hash,)).fetchone()
        return (json.loads(row["user"]), row["kind"], row["expires_at"]) if row else None

    def delete_token(self, token_hash: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM auth_tokens WHERE hash = ?", (token_hash,))

    def purge_tokens(self, now: float) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM auth_tokens WHERE expires_at <= ?", (now,))

    # ---- process models -------------------------------------------------------------------

    def next_process_version(self, process_id: str) -> int:
        with self._lock:
            row = self._db.execute("SELECT MAX(version) AS v FROM process_models WHERE id = ?", (process_id,)).fetchone()
        return (row["v"] or 0) + 1

    def add_process(self, process: dict[str, Any]) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO process_models VALUES (?, ?, ?, ?)", (process["id"], process["version"], _dump(process), _now()))

    def get_process(self, process_id: str, version: int | None = None) -> dict[str, Any] | None:
        query, args = "SELECT document FROM process_models WHERE id = ?", [process_id]
        if version is not None:
            query, args = query + " AND version = ?", args + [version]
        with self._lock:
            row = self._db.execute(query + " ORDER BY version DESC LIMIT 1", args).fetchone()
        return json.loads(row["document"]) if row else None

    def list_processes(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, version, created_at, json_extract(document, '$.name') AS name FROM process_models ORDER BY id, version"
            ).fetchall()
        return [dict(r) for r in rows]
