"""Talk to the Rookie Agent server with the standard library only (nothing to install on the GDV's PC)."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from typing import Any

TIMEOUT_SECONDS = 30


class ServerError(RuntimeError):
    """The server could not be reached or refused the request. The message is safe to show the GDV."""


def digest(workflow: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON. Same rule as `app.main.digest` on the server."""
    canonical = json.dumps(workflow, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ServerClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _call(self, method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read().decode("utf-8")).get("detail", "")
            except (ValueError, AttributeError):
                detail = ""
            raise ServerError(f"Máy chủ từ chối ({error.code}): {detail or error.reason}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ServerError(f"Không kết nối được máy chủ {self.base_url}: {error}") from error

    def health(self) -> dict[str, Any]:
        return self._call("GET", "/health")

    def post_session(self, session_id: str, engine: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        body = {"schema_version": 1, "engine": engine, "session_id": session_id, "events": events}
        return self._call("POST", "/sessions", body)

    def learn(self, workflow_id: str | None, session_ids: list[str], title: str | None = None) -> dict[str, Any]:
        """Give the id, or the teller's own `title` and the server makes the id from it."""
        body: dict[str, Any] = {"session_ids": session_ids}
        if workflow_id:
            body["workflow_id"] = workflow_id
        if title:
            body["title"] = title
        return self._call("POST", "/workflows/learn", body)

    def _verified(self, reply: dict[str, Any]) -> dict[str, Any]:
        """Refuse a workflow whose content does not match the digest the server sent with it."""
        if digest(reply["workflow"]) != reply.get("digest"):
            raise ServerError("Workflow nhận về không khớp mã kiểm tra (digest); không chạy.")
        return reply

    def approved_workflow(self, workflow_id: str) -> dict[str, Any]:
        return self._verified(self._call("GET", f"/workflows/{workflow_id}/approved"))

    def workflow_version(self, workflow_id: str, version: int) -> dict[str, Any]:
        return self._verified(self._call("GET", f"/workflows/{workflow_id}/versions/{version}"))

    def post_test_run(self, workflow_id: str, version: int, result: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", f"/workflows/{workflow_id}/versions/{version}/test-runs", result)

    def set_status(self, workflow_id: str, version: int, status: str) -> dict[str, Any]:
        return self._call("POST", f"/workflows/{workflow_id}/versions/{version}/status", {"status": status})
