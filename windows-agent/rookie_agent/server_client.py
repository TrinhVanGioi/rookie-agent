"""Talk to the Rookie Agent server with the standard library only (nothing to install on the GDV's PC)."""

from __future__ import annotations

import collections
import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any

TIMEOUT_SECONDS = 30
LEARN_TIMEOUT_SECONDS = 1500   # Học may call Codie twice on the server, up to 600 s each (ROOKIE_CODIE_TIMEOUT)
SHOWN_CHARS = 20000   # per message in the exchange log: enough to read, never a huge page

# The last exchanges with the server, for the "Gửi và nhận" screen. Kept in this process only, never written to disk.
# Everything sent is already masked (rule 2), so what is shown here is exactly what left the PC.
EXCHANGES: collections.deque[dict[str, Any]] = collections.deque(maxlen=40)
_EXCHANGES_LOCK = threading.Lock()


def _shown(text: str) -> str:
    return text if len(text) <= SHOWN_CHARS else text[:SHOWN_CHARS] + f"\n… (cắt bớt, tổng {len(text)} ký tự)"


def exchanges() -> list[dict[str, Any]]:
    with _EXCHANGES_LOCK:
        return list(reversed(EXCHANGES))


class ServerError(RuntimeError):
    """The server could not be reached or refused the request. The message is safe to show the GDV."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def digest(workflow: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON. Same rule as `app.main.digest` on the server."""
    canonical = json.dumps(workflow, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ServerClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _call(self, method: str, path: str, body: Any = None, timeout: float = TIMEOUT_SECONDS) -> Any:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        entry: dict[str, Any] = {"at": time.strftime("%H:%M:%S"), "method": method, "url": self.base_url + path,
                                 "sent": _shown(data.decode("utf-8")) if data else "", "status": None, "received": ""}
        started = time.monotonic()
        try:
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw = response.read().decode("utf-8")
                    entry["status"], entry["received"] = response.status, _shown(raw)
                    return json.loads(raw)
            except urllib.error.HTTPError as error:
                raw = error.read().decode("utf-8", "replace")
                entry["status"], entry["received"] = error.code, _shown(raw)
                try:
                    detail = json.loads(raw).get("detail", "")
                except (ValueError, AttributeError):
                    detail = ""
                raise ServerError(f"Máy chủ từ chối ({error.code}): {detail or error.reason}", error.code) from error
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                entry["received"] = f"(không kết nối được: {error})"
                raise ServerError(f"Không kết nối được máy chủ {self.base_url}: {error}") from error
        finally:
            entry["ms"] = round((time.monotonic() - started) * 1000)
            with _EXCHANGES_LOCK:
                EXCHANGES.append(entry)

    def health(self) -> dict[str, Any]:
        return self._call("GET", "/health")

    def post_session(self, session_id: str, engine: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        body = {"schema_version": 2 if engine == "ie" else 1, "engine": engine, "session_id": session_id, "events": events}
        return self._call("POST", "/sessions", body)

    def learn(self, workflow_id: str | None, session_ids: list[str], title: str | None = None, traces: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Give the id, or the teller's own `title` and the server makes the id from it. `traces` are the masked traces of the same
        recordings: with them the server may build the workflow with the model; without them it uses the rule-based learner."""
        body: dict[str, Any] = {"session_ids": session_ids}
        if traces:
            body["traces"] = traces
        if workflow_id:
            body["workflow_id"] = workflow_id
        if title:
            body["title"] = title
        return self._call("POST", "/workflows/learn", body, timeout=LEARN_TIMEOUT_SECONDS)

    def plan_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """The Assistant: the masked sentence and the catalog go up, the ranked candidates come back."""
        return self._call("POST", "/assistant/plan", payload)

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
