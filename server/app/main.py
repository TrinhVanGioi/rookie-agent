"""Rookie Agent server: receives recordings, learns workflows, keeps their versions and status."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.learner import LearnError, learn
from app.schemas import SchemaError, validate_event, validate_workflow
from app.storage import Storage

DEFAULT_DB = Path(__file__).resolve().parents[1] / "rookie.db"
_ID = r"^[a-z0-9][a-z0-9-]{0,63}$"
# The only moves allowed. `tested` also needs a passed sandbox run.
_TRANSITIONS = {("draft", "tested"), ("tested", "approved")}


class SessionIn(BaseModel):
    schema_version: Literal[1]
    engine: Literal["web", "java"]
    session_id: str = Field(min_length=1, max_length=64)
    events: list[dict[str, Any]] = Field(min_length=1)


class LearnIn(BaseModel):
    workflow_id: str = Field(pattern=_ID)
    session_ids: list[str] = Field(min_length=1)


class TestRunIn(BaseModel):
    status: str
    message: str = ""
    steps: list[dict[str, Any]] = []


class StatusIn(BaseModel):
    status: Literal["draft", "tested", "approved"]


def digest(workflow: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON. The runner checks it to detect a changed copy."""
    canonical = json.dumps(workflow, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_app(db_path: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="Rookie Agent Server")
    storage = Storage(db_path or os.environ.get("ROOKIE_DB") or DEFAULT_DB)
    app.state.storage = storage

    def workflow_reply(workflow: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
        return {"workflow": workflow, "digest": digest(workflow), "warnings": warnings}

    def load(workflow_id: str, version: int | None = None, status: str | None = None):
        found = storage.get_workflow(workflow_id, version, status)
        if found is None:
            raise HTTPException(404, "Không tìm thấy workflow")
        return found

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "server"}

    # ---- sessions -----------------------------------------------------------------

    @app.post("/sessions", status_code=201)
    def post_session(body: SessionIn) -> dict[str, Any]:
        problems: list[str] = []
        for index, event in enumerate(body.events):
            try:
                validate_event(event)
            except SchemaError as error:
                problems.append(f"sự kiện {index}: {error}")
                continue
            if event["session_id"] != body.session_id or event["engine"] != body.engine:
                problems.append(f"sự kiện {index}: session_id hoặc engine khác với phiên")
            if event["seq"] != index:
                problems.append(f"sự kiện {index}: seq phải liên tục từ 0")
        if problems:
            raise HTTPException(422, problems[:20])
        if not storage.add_session(body.session_id, body.engine, body.events):
            raise HTTPException(409, "Phiên ghi này đã được gửi")
        return {"session_id": body.session_id, "engine": body.engine, "event_count": len(body.events)}

    @app.get("/sessions")
    def list_sessions(engine: Literal["web", "java"] | None = None) -> dict[str, Any]:
        return {"sessions": storage.list_sessions(engine)}

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        session = storage.get_session(session_id)
        if session is None:
            raise HTTPException(404, "Không tìm thấy phiên ghi")
        return {"schema_version": 1, **session}

    # ---- workflows ----------------------------------------------------------------

    @app.post("/workflows/learn", status_code=201)
    def learn_workflow(body: LearnIn) -> dict[str, Any]:
        sessions = []
        for session_id in body.session_ids:
            session = storage.get_session(session_id)
            if session is None:
                raise HTTPException(404, f"Không tìm thấy phiên ghi {session_id}")
            sessions.append(session["events"])
        try:
            workflow, warnings = learn(sessions, body.workflow_id, storage.next_version(body.workflow_id))
        except LearnError as error:
            raise HTTPException(422, str(error)) from error
        storage.add_workflow(workflow, warnings)
        return workflow_reply(workflow, warnings)

    @app.get("/workflows")
    def list_workflows() -> dict[str, Any]:
        return {"workflows": storage.list_workflows()}

    @app.get("/workflows/{workflow_id}")
    def latest_workflow(workflow_id: str) -> dict[str, Any]:
        return workflow_reply(*load(workflow_id))

    @app.get("/workflows/{workflow_id}/approved")
    def approved_workflow(workflow_id: str) -> dict[str, Any]:
        """The newest approved version. Runners outside the sandbox use only this."""
        found = storage.get_workflow(workflow_id, status="approved")
        if found is None:
            raise HTTPException(404, "Workflow chưa có bản nào được duyệt")
        return workflow_reply(*found)

    @app.get("/workflows/{workflow_id}/versions/{version}")
    def workflow_version(workflow_id: str, version: int) -> dict[str, Any]:
        return workflow_reply(*load(workflow_id, version))

    @app.post("/workflows/{workflow_id}/versions/{version}/test-runs", status_code=201)
    def add_test_run(workflow_id: str, version: int, body: TestRunIn) -> dict[str, Any]:
        load(workflow_id, version)
        ok = body.status == "finished"
        storage.add_test_run(workflow_id, version, ok, body.model_dump())
        return {"ok": ok}

    @app.post("/workflows/{workflow_id}/versions/{version}/status")
    def set_status(workflow_id: str, version: int, body: StatusIn) -> dict[str, Any]:
        workflow, warnings = load(workflow_id, version)
        move = (workflow["status"], body.status)
        if move not in _TRANSITIONS:
            raise HTTPException(409, f"Không chuyển được từ {move[0]} sang {move[1]}")
        if body.status == "tested" and not storage.has_passed_test_run(workflow_id, version):
            raise HTTPException(409, "Phải chạy thử thành công ở sandbox trước khi chuyển sang tested")
        validate_workflow({**workflow, "status": body.status})
        storage.set_status(workflow_id, version, body.status)
        return workflow_reply(*load(workflow_id, version))

    return app


app = create_app()

# Kept importable for tools that check ids the same way the API does.
WORKFLOW_ID_PATTERN = re.compile(_ID)
