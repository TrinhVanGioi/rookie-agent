"""Rookie Agent server: receives recordings, learns workflows, keeps their versions and status."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import api_nodes
from app.auth import require, user as caller
from app.auth.access import NO_OWNER, can_change, can_see, can_share, sees_session
from app.learner import LearnError, learn, slug, with_adaptation
from app.schemas import SchemaError, validate_event, validate_workflow
from app.storage import Storage

DEFAULT_DB = Path(__file__).resolve().parents[1] / "rookie.db"
_ID = r"^[a-z0-9][a-z0-9-]{0,63}$"
# The only moves allowed. `tested` also needs a passed sandbox run.
_TRANSITIONS = {("draft", "tested"), ("tested", "approved")}


class SessionIn(BaseModel):
    """A recording. Unknown fields are refused, so nothing that identifies a person can ride along."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1, 2, 3, 4]
    engine: Literal["web", "java", "ie"]
    session_id: str = Field(min_length=1, max_length=64)
    events: list[dict[str, Any]] = Field(min_length=1)
    role: Literal["maker", "checker"] | None = None
    case_key: str | None = Field(default=None, pattern=r"^[0-9a-f]{16,64}$")   # HMAC of the case id, made on the PC; the server never sees the id
    synthetic: bool = False


class LearnIn(BaseModel):
    """Give a `title` (the GDV's own words) and the id is made from it, or give a `workflow_id`."""

    workflow_id: str | None = Field(default=None, pattern=_ID)
    title: str | None = Field(default=None, min_length=1, max_length=80)
    session_ids: list[str] = Field(min_length=1)
    traces: list[dict[str, Any]] | None = None   # the masked traces of the same recordings (trace.schema.json): the model builds from these


class TeachIn(BaseModel):
    """Task 12.5: the step after which the part taught again goes, and the recording of that part."""

    after_step: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=64)


class ReviseIn(BaseModel):
    modes: dict[str, Literal["auto", "review", "approve"]] = Field(min_length=1)


class TestRunIn(BaseModel):
    status: str
    message: str = ""
    steps: list[dict[str, Any]] = []


class StatusIn(BaseModel):
    status: Literal["draft", "tested", "approved"]


_WORD = r"^[a-z][a-z0-9_]{0,31}$"


class StepRunIn(BaseModel):
    """A step of a run: its id and how it ended. No detail text (it could hold a value)."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80)
    status: str = Field(pattern=_WORD)


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str = Field(min_length=1, max_length=80)
    kind: str = Field(pattern=_WORD)
    risk: Literal["read", "write", "money"]
    approved: bool | None = None


class AdaptationIn(BaseModel):
    """One adaptation decision (task 12.8): names and states only. A run of digits is a value and is refused."""

    model_config = ConfigDict(extra="forbid")
    step_id: str = Field(min_length=1, max_length=80)
    saw: str = Field(pattern=_WORD)
    change: Literal["technical", "business", "unknown"]
    action: Literal["reresolve", "ask"]
    outcome: str = Field(pattern=_WORD)
    risk: Literal["read", "write", "money"] | None = None

    @field_validator("step_id", "saw", "outcome")
    @classmethod
    def no_value(cls, value: str) -> str:
        if re.search(r"\d{4,}", value):
            raise ValueError("quyết định thích nghi không được chứa giá trị")
        return value


class RunIn(BaseModel):
    """A run as the PC's audit.jsonl has it, task 10.5: names and states only. Who ran it is the login, not a field."""

    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    time: str = Field(pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
    workflow_id: str = Field(pattern=_ID)
    version: int | None = Field(default=None, ge=1)
    title: str = Field(default="", max_length=80)
    mode: str = Field(pattern=_WORD)
    status: str = Field(pattern=_WORD)
    seconds: float = Field(default=0, ge=0)
    steps: list[StepRunIn] = Field(default=[], max_length=500)
    decisions: list[DecisionIn] = Field(default=[], max_length=200)
    adaptations: list[AdaptationIn] = Field(default=[], max_length=200)
    via: str | None = Field(default=None, pattern=r"^[a-z_]{0,24}$")
    input_names: list[str] = Field(default=[], max_length=50)


class RunsIn(BaseModel):
    runs: list[RunIn] = Field(min_length=1, max_length=200)


class EditIn(BaseModel):
    ops: list[dict[str, Any]] = Field(min_length=1, max_length=200)


class LayoutIn(BaseModel):
    layout: dict[str, tuple[float, float]] = Field(max_length=2000)


class ApiIn(BaseModel):
    api: list[dict[str, Any]] = Field(max_length=2000)


class ShareIn(BaseModel):
    visibility: Literal["private", "unit", "all"]
    confirm: bool = False      # the owner saw the preview (GET /workflows/{id}/share-preview)


class CloneIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)


class OwnerIn(BaseModel):
    owner: str = Field(min_length=1, max_length=64)
    owner_display: str = Field(default="", max_length=80)
    unit: str = Field(default="", max_length=80)


def digest(workflow: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON. The runner checks it to detect a changed copy."""
    canonical = json.dumps(workflow, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_app(db_path: str | Path | None = None, auth_mode: str | None = None, identity: Any = None,
               clock: Callable[[], float] = time.time) -> FastAPI:
    app = FastAPI(title="Rookie Agent Server")
    storage = Storage(db_path or os.environ.get("ROOKIE_DB") or DEFAULT_DB)
    app.state.storage = storage
    from app.auth import Auth, install

    install(app, Auth(storage, auth_mode, identity, clock))   # task 10.1: who is calling (ROOKIE_AUTH)
    # The model that builds a workflow from traces (Genie Codie on this PC). None: the rule-based learner builds it. A test can replace it.
    from app.llm.flow import CodieFlowBuilder

    builder = CodieFlowBuilder()
    app.state.flow_builder = builder if builder.available else None

    def workflow_reply(workflow: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
        api = storage.get_api(workflow["id"], workflow["version"])     # task 10.3: with a digest of their own; `digest` stays the workflow's
        return {"workflow": workflow, "digest": digest(workflow), "warnings": warnings, "api": api, "api_digest": api_nodes.digest(api)}

    def load(workflow_id: str, version: int | None = None, status: str | None = None):
        found = storage.get_workflow(workflow_id, version, status)
        if found is None:
            raise HTTPException(404, "Không tìm thấy workflow")
        return found

    # task 10.2: a flow the caller may not see is "not found" (not even that it exists); one they see but do not own is 403
    def visible(request: Request, workflow_id: str) -> dict[str, Any]:
        meta = storage.meta(workflow_id)
        if storage.get_workflow(workflow_id) is None or not can_see(caller(request), meta):
            raise HTTPException(404, "Không tìm thấy workflow")
        return meta

    def changeable(request: Request, workflow_id: str) -> dict[str, Any]:
        meta = visible(request, workflow_id)
        if not can_change(caller(request), meta):
            raise HTTPException(403, "Chỉ chủ luồng hoặc quản trị được sửa luồng này.")
        return meta

    def own(request: Request, workflow_id: str) -> None:
        if storage.meta(workflow_id)["owner"] is None and storage.get_workflow(workflow_id) is not None:
            who = caller(request)
            storage.set_owner(workflow_id, who.name, who.display, who.unit)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "server"}

    # ---- sessions -----------------------------------------------------------------

    @app.post("/sessions", status_code=201)
    def post_session(body: SessionIn, request: Request) -> dict[str, Any]:
        problems: list[str] = []
        for index, event in enumerate(body.events):
            try:
                validate_event(event)
            except SchemaError as error:
                problems.append(f"sự kiện {index}: {error}")
                continue
            if event["session_id"] != body.session_id or event["engine"] != body.engine:
                problems.append(f"sự kiện {index}: session_id hoặc engine khác với phiên")
            if event["schema_version"] != body.schema_version:
                problems.append(f"sự kiện {index}: schema_version khác với phiên")
            if event["seq"] != index:
                problems.append(f"sự kiện {index}: seq phải liên tục từ 0")
        if problems:
            raise HTTPException(422, problems[:20])
        if not storage.add_session(body.session_id, body.engine, body.events, body.role, body.case_key, body.synthetic,
                                   owner=caller(request).name):
            raise HTTPException(409, "Phiên ghi này đã được gửi")
        return {"session_id": body.session_id, "engine": body.engine, "event_count": len(body.events)}

    @app.get("/sessions")
    def list_sessions(request: Request, engine: Literal["web", "java", "ie"] | None = None) -> dict[str, Any]:
        who = caller(request)
        return {"sessions": storage.list_sessions(engine, owner=None if who.has("admin") else who.name)}

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str, request: Request) -> dict[str, Any]:
        session = storage.get_session(session_id)
        if session is None or not sees_session(caller(request), session):
            raise HTTPException(404, "Không tìm thấy phiên ghi")
        return {"schema_version": 2 if session["engine"] == "ie" else 1, **session}

    # ---- workflows ----------------------------------------------------------------

    def id_from_title(title: str) -> str:
        base = slug(title, "viec").replace("_", "-")[:48].strip("-") or "viec"
        candidate, counter = base, 2
        while storage.get_workflow(candidate) is not None:
            candidate, counter = f"{base}-{counter}", counter + 1
        return candidate

    @app.post("/workflows/learn", status_code=201)
    def learn_workflow(body: LearnIn, request: Request) -> dict[str, Any]:
        if body.workflow_id is None and body.title is None:
            raise HTTPException(422, "Cần đặt tên cho việc này.")
        workflow_id = body.workflow_id or id_from_title(body.title or "")
        if storage.get_workflow(workflow_id) is not None:
            changeable(request, workflow_id)          # a new version of someone else's flow: no
        sessions = []
        for session_id in body.session_ids:
            session = storage.get_session(session_id)
            if session is None or not sees_session(caller(request), session):
                raise HTTPException(404, f"Không tìm thấy phiên ghi {session_id}")
            sessions.append(session["events"])
        version = storage.next_version(workflow_id)
        extra: dict[str, Any] = {"method": "rule"}
        if body.traces:
            from app.llm.flow import FlowBuildError

            model = app.state.flow_builder
            if model is None:
                extra["fallback_reason"] = "Trợ lý (Codie) chưa bật hoặc chưa cài trên máy này, nên dùng cách học bằng luật."
            else:
                try:
                    built = model.build(body.traces, workflow_id, version, body.title)
                    built.workflow = with_adaptation(built.workflow, sessions)     # task 12.1: the same postconditions as the rules learn
                    storage.add_workflow(built.workflow, built.warnings)
                    storage.add_learn_sources(workflow_id, version, body.session_ids)
                    own(request, workflow_id)
                    return {**workflow_reply(built.workflow, built.warnings), "method": "codie", "questions": built.questions, "llm": {"calls": built.calls}}
                except FlowBuildError as error:
                    extra["fallback_reason"] = error.reason
                    extra["llm"] = {"calls": error.calls}
        try:
            workflow, warnings = learn(sessions, workflow_id, version, body.title)
        except LearnError as error:
            detail = str(error) + (f" (Trợ lý không dựng được: {extra['fallback_reason']})" if extra.get("fallback_reason") else "")
            raise HTTPException(422, detail) from error
        storage.add_workflow(workflow, warnings)
        storage.add_learn_sources(workflow_id, version, body.session_ids)
        own(request, workflow_id)
        return {**workflow_reply(workflow, warnings), **extra}

    @app.post("/assistant/plan")
    def assistant_plan(body: dict[str, Any]) -> dict[str, Any]:
        from app import assistant

        problems = assistant.check_request(body)
        if problems:
            raise HTTPException(422, problems[0])
        return assistant.plan(body, getattr(app.state, "assistant_client", None))

    @app.get("/workflows")
    def list_workflows(request: Request) -> dict[str, Any]:
        who = caller(request)
        rows = [{**row, "owner_display": row["owner_display"] or (NO_OWNER if row["owner"] is None else row["owner"])}
                for row in storage.list_workflows() if can_see(who, row)]
        highest: dict[str, str] = {}
        for workflow_id in {row["id"] for row in rows}:      # task 10.6: the highest risk of the newest version, for the list
            workflow, _ = load(workflow_id)
            risks = [s["risk"] for s in workflow["steps"]] + [n["risk"] for n in storage.get_api(workflow_id, workflow["version"]) or []]
            highest[workflow_id] = max(risks, key=lambda r: {"read": 0, "write": 1, "money": 2}[r], default="read")
        return {"workflows": [{**row, "max_risk": highest[row["id"]]} for row in rows]}

    @app.get("/workflows/{workflow_id}")
    def latest_workflow(workflow_id: str, request: Request) -> dict[str, Any]:
        visible(request, workflow_id)
        return workflow_reply(*load(workflow_id))

    @app.get("/workflows/{workflow_id}/approved")
    def approved_workflow(workflow_id: str, request: Request) -> dict[str, Any]:
        """The newest approved version. Runners outside the sandbox use only this."""
        visible(request, workflow_id)
        found = storage.get_workflow(workflow_id, status="approved")
        if found is None:
            raise HTTPException(404, "Workflow chưa có bản nào được duyệt")
        return workflow_reply(*found)

    @app.get("/workflows/{workflow_id}/versions/{version}")
    def workflow_version(workflow_id: str, version: int, request: Request) -> dict[str, Any]:
        visible(request, workflow_id)
        return workflow_reply(*load(workflow_id, version))

    @app.post("/workflows/{workflow_id}/versions/{version}/revise", status_code=201)
    def revise_workflow(workflow_id: str, version: int, body: ReviseIn, request: Request) -> dict[str, Any]:
        """Change how much control some steps have. Makes a new version that starts again as a draft."""
        changeable(request, workflow_id)
        workflow, warnings = load(workflow_id, version)
        revised = copy.deepcopy(workflow)
        steps = {step["id"]: step for step in revised["steps"]}
        for step_id, mode in body.modes.items():
            step = steps.get(step_id)
            if step is None:
                raise HTTPException(422, f"Không có bước {step_id} trong việc này.")
            if step["risk"] == "write" and mode != "approve":
                raise HTTPException(422, "Bước sửa dữ liệu luôn phải chờ bạn duyệt.")
            if step["risk"] == "money" and mode == "auto":
                raise HTTPException(422, "Bước liên quan tiền không thể tự làm, phải cho bạn xem hoặc chờ bạn duyệt.")
            step["mode"] = mode
        revised["version"] = storage.next_version(workflow_id)
        revised["status"] = "draft"
        validate_workflow(revised)
        storage.add_workflow(revised, warnings)
        return workflow_reply(revised, warnings)

    @app.post("/workflows/{workflow_id}/versions/{version}/test-runs", status_code=201)
    def add_test_run(workflow_id: str, version: int, body: TestRunIn, request: Request) -> dict[str, Any]:
        changeable(request, workflow_id)
        load(workflow_id, version)
        ok = body.status == "finished"
        storage.add_test_run(workflow_id, version, ok, body.model_dump())
        return {"ok": ok}

    @app.post("/workflows/{workflow_id}/versions/{version}/status")
    def set_status(workflow_id: str, version: int, body: StatusIn, request: Request) -> dict[str, Any]:
        changeable(request, workflow_id)
        workflow, warnings = load(workflow_id, version)
        move = (workflow["status"], body.status)
        if move not in _TRANSITIONS:
            raise HTTPException(409, f"Không chuyển được từ {move[0]} sang {move[1]}")
        if body.status == "tested" and not storage.has_passed_test_run(workflow_id, version):
            raise HTTPException(409, "Phải chạy thử thành công ở sandbox trước khi chuyển sang tested")
        edited = storage.get_edit(workflow_id, version)
        if (body.status == "approved" and edited is not None and app.state.auth.mode != "off"
                and edited["edited_by"] == caller(request).name):
            raise HTTPException(409, "Người sửa bản này không tự duyệt được. Nhờ chủ luồng hoặc quản trị khác duyệt.")
        validate_workflow({**workflow, "status": body.status})
        storage.set_status(workflow_id, version, body.status)
        return workflow_reply(*load(workflow_id, version))

    # ---- the API nodes of a version (task 10.3) -------------------------------------------------------------------

    @app.put("/workflows/{workflow_id}/versions/{version}/api")
    def put_api(workflow_id: str, version: int, body: ApiIn, request: Request) -> dict[str, Any]:
        changeable(request, workflow_id)
        load(workflow_id, version)
        try:
            api_nodes.check(body.api)
        except SchemaError as error:
            raise HTTPException(422, str(error)) from error
        storage.set_api(workflow_id, version, body.api)
        return {"api_digest": api_nodes.digest(body.api), "count": len(body.api)}

    # ---- editing on the admin page (task 10.4) ------------------------------------------------------------------------

    @app.post("/workflows/{workflow_id}/versions/{version}/edit", status_code=201)
    def edit_workflow(workflow_id: str, version: int, body: EditIn, request: Request) -> dict[str, Any]:
        """Every save is a new draft version; the base version does not change. The server checks every rule again."""
        from app import edit

        changeable(request, workflow_id)
        workflow, warnings = load(workflow_id, version)
        try:
            edited, api = edit.apply(workflow, storage.get_api(workflow_id, version), body.ops)
        except edit.EditError as error:
            raise HTTPException(422, str(error)) from error
        edited["version"], edited["status"] = storage.next_version(workflow_id), "draft"
        validate_workflow(edited)
        storage.add_workflow(edited, warnings)
        if api is not None:
            storage.set_api(workflow_id, edited["version"], api)
        storage.add_edit(workflow_id, edited["version"], version, caller(request).name, body.ops)
        return workflow_reply(edited, warnings)

    @app.post("/workflows/{workflow_id}/versions/{version}/teach", status_code=201)
    def teach_part(workflow_id: str, version: int, body: TeachIn, request: Request) -> dict[str, Any]:
        """Task 12.5 (Delta Learning): the part the teller taught again goes in after `after_step`, as a new draft version; the other
        steps and the version it was made from stay as they were."""
        from app import delta

        changeable(request, workflow_id)
        workflow, warnings = load(workflow_id, version)
        session = storage.get_session(body.session_id)
        if session is None or not sees_session(caller(request), session):
            raise HTTPException(404, f"Không tìm thấy phiên ghi {body.session_id}")
        new_version = storage.next_version(workflow_id)
        try:
            taught, change = delta.splice(workflow, body.after_step, [session["events"]], new_version)
        except delta.DeltaError as error:
            raise HTTPException(422, str(error)) from error
        storage.add_workflow(taught, warnings)
        api = storage.get_api(workflow_id, version)
        if api is not None:
            storage.set_api(workflow_id, new_version, api)     # the calls of the steps that stayed; the new part runs on the screen
        storage.add_edit(workflow_id, new_version, version, caller(request).name, [change])
        storage.add_learn_sources(workflow_id, new_version, [body.session_id])
        return {**workflow_reply(taught, warnings), "change": change}

    @app.post("/workflows/{workflow_id}/versions/{version}/restore", status_code=201)
    def restore_version(workflow_id: str, version: int, request: Request) -> dict[str, Any]:
        """Task 12.5: «Quay về bản này»: an older version comes back as a new draft (it is approved again before it is used)."""
        changeable(request, workflow_id)
        workflow, warnings = load(workflow_id, version)
        back = copy.deepcopy(workflow)
        back["version"], back["status"] = storage.next_version(workflow_id), "draft"
        validate_workflow(back)
        storage.add_workflow(back, warnings)
        api = storage.get_api(workflow_id, version)
        if api is not None:
            storage.set_api(workflow_id, back["version"], api)
        storage.add_edit(workflow_id, back["version"], version, caller(request).name, [{"op": "restore", "to": version}])
        return workflow_reply(back, warnings)

    @app.post("/workflows/{workflow_id}/versions/{version}/edit/preview")
    def edit_preview(workflow_id: str, version: int, body: EditIn, request: Request) -> dict[str, Any]:
        """The flow as it would be after the edits, checked by the same rules; nothing is kept (the canvas shows the server's truth)."""
        from app import edit

        changeable(request, workflow_id)
        workflow, warnings = load(workflow_id, version)
        try:
            edited, api = edit.apply(workflow, storage.get_api(workflow_id, version), body.ops)
        except edit.EditError as error:
            raise HTTPException(422, str(error)) from error
        return {"workflow": edited, "api": api, "warnings": warnings}

    @app.get("/workflows/{workflow_id}/versions/{version}/edit")
    def edit_record(workflow_id: str, version: int, request: Request) -> dict[str, Any]:
        visible(request, workflow_id)
        load(workflow_id, version)
        return {"edit": storage.get_edit(workflow_id, version)}

    @app.get("/workflows/{workflow_id}/layout")
    def get_layout(workflow_id: str, request: Request) -> dict[str, Any]:
        visible(request, workflow_id)
        return {"layout": storage.get_layout(workflow_id)}

    @app.put("/workflows/{workflow_id}/layout")
    def put_layout(workflow_id: str, body: LayoutIn, request: Request) -> dict[str, Any]:
        """Where the nodes are drawn on the canvas: not a new version (it changes nothing that runs)."""
        changeable(request, workflow_id)
        storage.set_layout(workflow_id, body.layout)
        return {"layout": body.layout}

    # ---- runs (task 10.5) ---------------------------------------------------------------------------------------------

    @app.post("/runs")
    def post_runs(body: RunsIn, request: Request) -> dict[str, int]:
        """Runs sent up by a PC. A run of a flow the caller does not see is skipped; one already kept is not kept twice."""
        who = caller(request)
        kept = known = skipped = 0
        for run in body.runs:
            if any(not re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in run.input_names):
                raise HTTPException(422, "input_names chỉ chứa tên ô nhập.")
            if storage.get_workflow(run.workflow_id) is None or not can_see(who, storage.meta(run.workflow_id)):
                skipped += 1
                continue
            if storage.add_run(run.model_dump(), {"name": who.name, "display": who.display, "unit": who.unit}):
                kept += 1
            else:
                known += 1
        return {"kept": kept, "known": known, "skipped": skipped}

    def _sadpt(workflow_id: str) -> dict[str, Any]:
        """Task 12.8 (Knowledge): the four SADPT numbers of one flow, from the runs sent up and the parts taught again."""
        from app.sadpt import measure

        rows: list[dict[str, Any]] = []
        risks: dict[tuple[Any, Any], dict[str, str]] = {}
        for run in storage.runs_of(workflow_id, limit=1000):
            key = (workflow_id, run.get("version"))
            if key not in risks:
                found = storage.get_workflow(workflow_id, run.get("version")) if run.get("version") else None
                steps = (found[0].get("steps") or []) if found else []
                risks[key] = {step["id"]: step.get("risk") for step in steps if step.get("id")}
            known = risks[key]
            for row in run.get("adaptations") or []:
                stored = known.get(row.get("step_id"))
                rows.append({**row, "risk": stored if stored in ("read", "write", "money") else row.get("risk")})
        taught = 0
        for edit in storage.edits_of(workflow_id):
            for op in edit.get("ops") or []:
                if op.get("op") == "teach":
                    taught += len([step for step in op.get("added") or [] if isinstance(step, str)])
        return measure(rows, taught)

    @app.get("/workflows/{workflow_id}/runs")
    def workflow_runs(workflow_id: str, request: Request) -> dict[str, Any]:
        visible(request, workflow_id)
        return {"runs": storage.runs_of(workflow_id), "sadpt": _sadpt(workflow_id)}

    def _savings(workflow_id: str) -> dict[str, Any]:
        """Task 11.8: by hand (the recordings it was learned from, first action to last) against the finished runs; medians, 3 of each at least."""
        import statistics
        from datetime import datetime

        manual: list[float] = []
        for wid, _, session_ids in storage.learn_sources():
            if wid != workflow_id:
                continue
            manual = []
            for session_id in session_ids:
                stamps = []
                for event in (storage.get_session(session_id) or {}).get("events") or []:
                    try:
                        stamps.append(datetime.fromisoformat(str(event.get("ts")).replace("Z", "+00:00")).timestamp())
                    except ValueError:
                        pass
                if len(stamps) >= 2:
                    manual.append(max(stamps) - min(stamps))
        runs = [float(r.get("seconds") or 0) for r in storage.runs_of(workflow_id) if r.get("status") == "finished" and r.get("mode") in ("run", "simulate")]
        if len(manual) < 3 or len(runs) < 3:
            return {}
        by_hand, agent = statistics.median(manual), statistics.median(runs)
        return {"manual_s": round(by_hand, 1), "agent_s": round(agent, 1), "saved_s": round(max(0.0, by_hand - agent), 1)}

    @app.get("/runs/summary")
    def run_summary(request: Request) -> dict[str, Any]:
        who = caller(request)
        return {"flows": {wid: {**row, **_savings(wid), "sadpt": _sadpt(wid)}
                          for wid, row in storage.run_summary().items() if can_see(who, storage.meta(wid))}}

    # ---- sharing, cloning, owners (task 10.2) ---------------------------------------------------------------------

    @app.get("/workflows/{workflow_id}/share-preview")
    def share_preview(workflow_id: str, request: Request) -> dict[str, Any]:
        """Exactly what others will see: steps, labels, names of the inputs. No value (there is none on the server)."""
        visible(request, workflow_id)
        workflow, _ = load(workflow_id)
        steps = [{"label": (step.get("target") or {}).get("label") or step["action"], "risk": step["risk"], "mode": step["mode"]}
                 for step in workflow["steps"]]
        inputs = [{"name": item["name"], "label": item.get("label") or item["name"], "type": item["type"]} for item in workflow["inputs"]]
        return {"title": workflow.get("title") or workflow_id, "steps": steps, "inputs": inputs, "visibility": storage.meta(workflow_id)["visibility"]}

    @app.post("/workflows/{workflow_id}/share")
    def share(workflow_id: str, body: ShareIn, request: Request) -> dict[str, Any]:
        meta = visible(request, workflow_id)
        if not can_share(caller(request), meta):
            raise HTTPException(403, "Chỉ chủ luồng mới chia sẻ được luồng này.")
        if not body.confirm:
            raise HTTPException(422, "Xem trước nội dung sẽ chia sẻ rồi xác nhận.")
        storage.set_visibility(workflow_id, body.visibility)
        return {"id": workflow_id, "visibility": body.visibility}

    @app.post("/workflows/{workflow_id}/clone", status_code=201)
    def clone(workflow_id: str, body: CloneIn, request: Request) -> dict[str, Any]:
        visible(request, workflow_id)
        source, warnings = storage.get_workflow(workflow_id, status="approved") or load(workflow_id)
        title = body.title or f"{source.get('title') or workflow_id} (bản sao)"[:80]
        new_id = id_from_title(title)
        copied = {**copy.deepcopy(source), "id": new_id, "version": 1, "status": "draft", "title": title}
        validate_workflow(copied)
        storage.add_workflow(copied, warnings)
        source_api = storage.get_api(workflow_id, source["version"])
        if source_api is not None:
            storage.set_api(new_id, 1, source_api)
        who = caller(request)
        storage.set_owner(new_id, who.name, who.display, who.unit, cloned_from=f"{workflow_id}@{source['version']}")
        return workflow_reply(copied, warnings)

    @app.post("/workflows/{workflow_id}/owner")
    def give_owner(workflow_id: str, body: OwnerIn, request: Request) -> dict[str, Any]:
        require(request, "admin")
        load(workflow_id)
        storage.set_owner(workflow_id, body.owner, body.owner_display or body.owner, body.unit)
        return storage.meta(workflow_id)

    # ---- the admin page (task 10.6): plain files, no build step, nothing from outside (offline network) ------------------
    from fastapi.staticfiles import StaticFiles

    app.mount("/admin", StaticFiles(directory=Path(__file__).resolve().parent / "admin", html=True), name="admin")

    from app.twin.routes import register as register_twin

    register_twin(app, storage)
    return app


def id_from_text(text: str, fallback: str, taken) -> str:
    """An id made from a name (`Chuyển tiền` -> `chuyen-tien`), made unique with a number."""
    base = slug(text, fallback).replace("_", "-")[:48].strip("-") or fallback
    candidate, counter = base, 2
    while taken(candidate):
        candidate, counter = f"{base}-{counter}", counter + 1
    return candidate


app = create_app()

# Kept importable for tools that check ids the same way the API does.
WORKFLOW_ID_PATTERN = re.compile(_ID)
