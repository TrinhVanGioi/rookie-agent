"""Talk to the Rookie Agent server with the standard library only (nothing to install on the GDV's PC)."""

from __future__ import annotations

import collections
import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
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


def session_body(session_id: str, engine: str, events: list[dict[str, Any]], role: str | None = None, case_key: str | None = None) -> dict[str, Any]:
    """The body of `POST /sessions`. An ie session is schema 3 (api_calls with timings), or 4 when its events say what the screen
    showed after them (task 12.1); the session's version is the one its events carry."""
    version = max([3] + [int(e.get("schema_version") or 0) for e in events]) if engine == "ie" else 1
    body: dict[str, Any] = {"schema_version": version, "engine": engine, "session_id": session_id, "events": events}
    if role:
        body["role"] = role
    if case_key:
        body["case_key"] = case_key
    return body


class ServerError(RuntimeError):
    """The server could not be reached or refused the request. The message is safe to show the GDV."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def digest(workflow: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON. Same rule as `app.main.digest` on the server."""
    canonical = json.dumps(workflow, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hidden(path: str, text: str) -> str:
    """What the exchange log shows of a login: never the password, never the token."""
    if not path.startswith("/auth/"):
        return text
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if isinstance(data, dict):
        data = {k: ("***" if k in ("password", "token") else v) for k, v in data.items()}
    return json.dumps(data, ensure_ascii=False)


class ServerClient:
    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token   # task 10.1: from a login on the server; sent as `Authorization: Bearer`

    def _call(self, method: str, path: str, body: Any = None, timeout: float = TIMEOUT_SECONDS) -> Any:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        entry: dict[str, Any] = {"at": time.strftime("%H:%M:%S"), "method": method, "url": self.base_url + path,
                                 "sent": _shown(_hidden(path, data.decode("utf-8"))) if data else "", "status": None, "received": ""}
        started = time.monotonic()
        try:
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw = response.read().decode("utf-8")
                    entry["status"], entry["received"] = response.status, _shown(_hidden(path, raw))
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

    def login(self, username: str, password: str) -> dict[str, Any]:
        """Task 10.1: the server checks the password (AD) and gives a token; the password is not kept anywhere."""
        return self._call("POST", "/auth/login", {"username": username, "password": password, "client": "agent"})

    def handoff(self) -> dict[str, Any]:
        """Task 11.5: a one-time code (60 s) that opens the admin page signed in as this PC's login."""
        return self._call("POST", "/auth/handoff", {})

    def logout(self) -> dict[str, Any]:
        return self._call("POST", "/auth/logout", {})

    def post_session(self, session_id: str, engine: str, events: list[dict[str, Any]], role: str | None = None,
                     case_key: str | None = None) -> dict[str, Any]:
        """`role` ("maker" or "checker") and `case_key` (a keyed hash of the case id, never the id) are for the process log (Gate 9);
        events of an ie session may carry `api_calls` ({method, path (template, no query), status, ms}), which is schema 3."""
        return self._call("POST", "/sessions", session_body(session_id, engine, events, role, case_key))

    # ---- Gate 9: the process twin on the server (the body of a reply is passed on as it is) -------------------------------------

    def twin_processes(self) -> dict[str, Any]:
        return self._call("GET", "/twin/processes")

    def twin_process(self, process_id: str) -> dict[str, Any]:
        return self._call("GET", f"/twin/processes/{urllib.parse.quote(process_id, safe='')}")

    def twin_save(self, process: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", "/twin/processes", process)

    def twin_discover(self, process_id: str = "") -> dict[str, Any]:
        return self._call("GET", "/twin/discover" + (f"?process_id={urllib.parse.quote(process_id, safe='')}" if process_id else ""))

    def twin_suggest(self) -> dict[str, Any]:
        return self._call("GET", "/twin/suggest")

    def twin_metrics(self, process_id: str) -> dict[str, Any]:
        return self._call("GET", f"/twin/processes/{urllib.parse.quote(process_id, safe='')}/metrics")

    def twin_simulate(self, process_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", f"/twin/processes/{urllib.parse.quote(process_id, safe='')}/simulate", payload, timeout=120)

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

    def flow_version(self, workflow_id: str, version: int | None = None) -> dict[str, Any]:
        """Task 10.7: a version (the newest when None) with its API nodes; both digests checked."""
        path = f"/workflows/{urllib.parse.quote(workflow_id, safe='')}" + (f"/versions/{int(version)}" if version else "")
        reply = self._verified(self._call("GET", path))
        api = reply.get("api")
        if api is not None and digest(api) != reply.get("api_digest"):
            raise ServerError("Nút API nhận về không khớp mã kiểm tra (digest); không dùng.")
        return reply

    def list_workflows(self) -> list[dict[str, Any]]:
        return self._call("GET", "/workflows").get("workflows") or []

    def edit_record(self, workflow_id: str, version: int) -> dict[str, Any] | None:
        return self._call("GET", f"/workflows/{urllib.parse.quote(workflow_id, safe='')}/versions/{int(version)}/edit").get("edit")

    def approved_workflow(self, workflow_id: str) -> dict[str, Any]:
        return self._verified(self._call("GET", f"/workflows/{workflow_id}/approved"))

    def workflow_version(self, workflow_id: str, version: int) -> dict[str, Any]:
        return self._verified(self._call("GET", f"/workflows/{workflow_id}/versions/{version}"))

    def put_api(self, workflow_id: str, version: int, api: list[dict[str, Any]]) -> dict[str, Any]:
        """Task 10.3: the API nodes of a version, already masked by `ie.api_share.for_server`."""
        return self._call("PUT", f"/workflows/{workflow_id}/versions/{version}/api", {"api": api})

    def teach(self, workflow_id: str, version: int, after_step: str, session_id: str) -> dict[str, Any]:
        """Task 12.5: the part taught again (a recording already sent) goes in after `after_step`; the server answers the new draft."""
        return self._call("POST", f"/workflows/{urllib.parse.quote(workflow_id, safe='')}/versions/{int(version)}/teach",
                          {"after_step": after_step, "session_id": session_id})

    def delete_workflow(self, workflow_id: str) -> dict[str, Any]:
        """The owner or an admin removes the learned flow on the server. The page has already asked the teller."""
        return self._call("POST", f"/workflows/{urllib.parse.quote(workflow_id, safe='')}/delete", {"confirm": True})

    def restore(self, workflow_id: str, version: int) -> dict[str, Any]:
        """Task 12.5: an older version back, as a new draft to approve."""
        return self._call("POST", f"/workflows/{urllib.parse.quote(workflow_id, safe='')}/versions/{int(version)}/restore", {})

    def post_runs(self, runs: list[dict[str, Any]]) -> dict[str, Any]:
        """Task 10.5: runs of this PC, names and states only (built by `Core._send_runs`)."""
        return self._call("POST", "/runs", {"runs": runs})

    def post_test_run(self, workflow_id: str, version: int, result: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", f"/workflows/{workflow_id}/versions/{version}/test-runs", result)

    def set_status(self, workflow_id: str, version: int, status: str) -> dict[str, Any]:
        return self._call("POST", f"/workflows/{workflow_id}/versions/{version}/status", {"status": status})
