"""The /twin/* routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.schemas import SchemaError, validate_log_row, validate_process
from app.storage import Storage
from app.twin import discover as discovery
from app.twin import metrics, simulate
from app.twin.log import build_log

_ID = r"^[a-z0-9][a-z0-9-]{0,63}$"


class StageIn(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    workflow_id: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=120)
    role: Literal["maker", "checker"]


class HandoffIn(BaseModel):
    from_stage: str
    to_stage: str
    queue: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")


class ProcessIn(BaseModel):
    id: str | None = Field(default=None, pattern=_ID)
    name: str = Field(min_length=1, max_length=120)
    stages: list[StageIn] = Field(min_length=1)
    handoffs: list[HandoffIn] = []


class WorkHours(BaseModel):
    start: int = Field(ge=0, le=23)
    end: int = Field(ge=1, le=24)

    @model_validator(mode="after")
    def _ordered(self) -> "WorkHours":
        if self.end <= self.start:
            raise ValueError("Giờ kết thúc phải sau giờ bắt đầu.")
        return self


Staff = dict[Literal["maker", "checker"], int]


class SimulateIn(BaseModel):
    seed: int = 1
    hours: float = Field(default=8, gt=0, le=720)
    arrivals_per_hour: float | None = Field(default=None, gt=0, le=10000)
    staff: Staff | None = None
    baseline_staff: Staff | None = None
    api_factor: float = Field(default=1.0, ge=0, le=10)
    steps: dict[str, Literal["keep", "remove", "agent"]] = {}
    work_hours: WorkHours | None = None

    @model_validator(mode="after")
    def _staff_range(self) -> "SimulateIn":
        for staff in (self.staff, self.baseline_staff):
            if staff and any(not 1 <= n <= 100 for n in staff.values()):
                raise ValueError("Số người mỗi vai trò phải từ 1 đến 100.")
        return self


def register(app: FastAPI, storage: Storage) -> None:
    def process_or_404(process_id: str) -> dict[str, Any]:
        found = storage.get_process(process_id)
        if found is None:
            raise HTTPException(404, "Không tìm thấy quy trình")
        return found

    def process_rows(process: dict[str, Any]) -> list[dict[str, Any]]:
        return build_log(storage, [s["workflow_id"] for s in process["stages"]])

    @app.post("/twin/processes", status_code=201)
    def post_process(body: ProcessIn) -> dict[str, Any]:
        from app.main import id_from_text

        for stage in body.stages:
            if storage.get_workflow(stage.workflow_id) is None:
                raise HTTPException(422, f"Chặng {stage.id}: không có việc {stage.workflow_id}")
        process_id = body.id or id_from_text(body.name, "quy-trinh", lambda candidate: storage.get_process(candidate) is not None)
        process = {
            "schema_version": 1,
            "id": process_id,
            "name": body.name,
            "version": storage.next_process_version(process_id),
            "stages": [s.model_dump() for s in body.stages],
            "handoffs": [h.model_dump() for h in body.handoffs],
        }
        try:
            validate_process(process)
        except SchemaError as error:
            raise HTTPException(422, str(error)) from error
        storage.add_process(process)
        return process

    @app.get("/twin/processes")
    def list_processes() -> dict[str, Any]:
        return {"processes": storage.list_processes()}

    @app.get("/twin/processes/{process_id}")
    def get_process(process_id: str) -> dict[str, Any]:
        return process_or_404(process_id)

    @app.get("/twin/log")
    def get_log(workflow_id: str | None = None) -> dict[str, Any]:
        rows = build_log(storage, [workflow_id] if workflow_id else None)
        for row in rows:
            validate_log_row(row)
        return {"rows": rows, "count": len(rows)}

    @app.get("/twin/discover")
    def get_discover(process_id: str | None = None, workflow_ids: str | None = None) -> dict[str, Any]:
        if process_id:
            process = process_or_404(process_id)
            return discovery.discover(process_rows(process), process)
        ids = [i for i in (workflow_ids or "").split(",") if i]
        if not ids:
            raise HTTPException(422, "Cần process_id hoặc workflow_ids.")
        return discovery.discover(build_log(storage, ids))

    @app.get("/twin/suggest")
    def get_suggest(workflow_ids: str | None = None) -> dict[str, Any]:
        ids = [i for i in (workflow_ids or "").split(",") if i]
        return discovery.suggest(build_log(storage, ids or None), storage)

    @app.get("/twin/processes/{process_id}/metrics")
    def get_metrics(process_id: str) -> dict[str, Any]:
        process = process_or_404(process_id)
        return metrics.compute(process, process_rows(process), storage)

    @app.post("/twin/processes/{process_id}/simulate")
    def post_simulate(process_id: str, body: SimulateIn) -> dict[str, Any]:
        from app.llm.factory import get_llm_client

        process = process_or_404(process_id)
        rows = process_rows(process)
        if len({r["case"] for r in rows}) < metrics.MIN_CASES:
            raise HTTPException(409, f"Cần ít nhất {metrics.MIN_CASES} ca đã ghi để mô phỏng (không dùng số đo từ quá ít ca).")
        client = getattr(app.state, "llm_client", None) or get_llm_client()
        params = body.model_dump(exclude_none=True)
        try:
            return simulate.simulate(process, rows, params, storage, client)
        except simulate.SimError as error:
            raise HTTPException(422, str(error)) from error
