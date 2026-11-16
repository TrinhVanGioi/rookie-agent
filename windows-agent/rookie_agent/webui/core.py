"""What the local web page does. No HTTP in here, so it can be tested with fakes.

The page runs on the teller's own PC and talks to this module. Everything it shows is in plain words:
no ids, no selectors. What is kept on disk (the recorded sessions) never holds a typed value of a sensitive
field; the Recorder has already removed it.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rookie_agent import __version__, diagnose
from rookie_agent.native_host import Host
from rookie_agent.server_client import ServerClient, ServerError

DEFAULT_SERVER = "http://localhost:8000"
IE_PREFIX = "Internet Explorer: "

ACTION_WORDS = {
    "click": "Bấm", "input": "Nhập vào", "select": "Chọn ở", "submit": "Nhấn Enter ở", "navigate": "Mở màn hình",
    "fill": "Nhập vào", "goto": "Mở màn hình", "read_value": "Đọc giá trị ở", "wait_for": "Chờ",
}
RISK_WORDS = {"read": "chỉ xem", "write": "ghi dữ liệu, luôn hỏi trước khi làm", "money": "liên quan tiền, luôn hỏi trước khi làm"}
MODE_WORDS = {"auto": "tự chạy", "review": "dừng cho bạn xem", "approve": "chờ bạn duyệt"}


class UserError(Exception):
    """A problem to show the teller as it is written."""


def friendly_step(kind: str, label: str | None) -> str:
    verb = ACTION_WORDS.get(kind, "Thao tác")
    return f"{verb} «{label}»" if label else verb


def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    typed = [event for event in events if event.get("type") == "input"]
    return {
        "steps": [friendly_step(str(e.get("type")), (e.get("target") or {}).get("label")) for e in events],
        "events": len(events),
        "typed_fields": len(typed),
        "typed_values_kept": sum(1 for e in typed if e.get("value") is not None),
    }


def slug(text: str) -> str:
    plain = unicodedata.normalize("NFD", text).replace("đ", "d").replace("Đ", "D")
    plain = "".join(c for c in plain if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:48] or "viec"


class Store:
    """Recorded sessions and settings on this PC, under the agent folder."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self.sessions = home / "sessions"
        self.sessions.mkdir(parents=True, exist_ok=True)

    def _settings(self) -> dict[str, Any]:
        try:
            return json.loads((self.home / "settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._settings().get(key, default)

    def put(self, key: str, value: Any) -> None:
        data = self._settings()
        data[key] = value
        (self.home / "settings.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def save(self, session_id: str, events: list[dict[str, Any]], name: str, engine: str = "java") -> dict[str, Any]:
        document = {
            "schema_version": 2 if engine == "ie" else 1, "engine": engine, "session_id": session_id, "events": events,
            "name": name, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "uploaded": False,
        }
        (self.sessions / f"{session_id}.json").write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        return document

    def load(self, session_id: str) -> dict[str, Any]:
        try:
            return json.loads((self.sessions / f"{session_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise UserError("Không đọc được bản ghi này.") from error

    def update(self, session_id: str, **fields: Any) -> None:
        document = self.load(session_id)
        document.update(fields)
        (self.sessions / f"{session_id}.json").write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    def delete(self, session_id: str) -> None:
        (self.sessions / f"{session_id}.json").unlink(missing_ok=True)

    def listing(self) -> list[dict[str, Any]]:
        rows = []
        for path in sorted(self.sessions.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rows.append({
                "id": document["session_id"], "name": document.get("name", ""), "saved_at": document.get("saved_at", ""),
                "uploaded": bool(document.get("uploaded")), **summarize_events(document["events"]),
            })
        return rows


class Core:
    def __init__(
        self,
        home: Path,
        open_session: Callable[[], Any],
        own_bits: int,
        dll_info: Callable[[], tuple[str | None, str | None]],
        installs: Callable[[], list[diagnose.JavaInstall]] = diagnose.find_java_installs,
        users: Callable[[], list[diagnose.JavaUser]] = diagnose.java_users,
        switched_on: Callable[[], bool] = diagnose.bridge_switched_on,
        feed_factory: Callable[[Any], Any] | None = None,
        server_starter: Callable[[], str] | None = None,
        relauncher: Callable[[int], None] | None = None,
        server_client: Callable[[str], Any] = ServerClient,
        ie_bridge: Callable[[], Any] | None = None,
    ) -> None:
        self.store = Store(home)
        self._open_session = open_session
        self._own_bits = own_bits
        self._dll_info = dll_info
        self._installs, self._users, self._switched_on = installs, users, switched_on
        self._feed_factory = feed_factory
        self._server_starter = server_starter
        self._relauncher = relauncher
        self._server_client = server_client
        self._session: Any = None
        self._session_error: str | None = None
        self._host: Host | None = None
        self._ie_factory = ie_bridge
        self._ie_bridge: Any = None
        self._ie_error: str | None = None
        self._ie_session: Any = None

    # ---- web pages in Internet Explorer ---------------------------------------------------

    def _ie(self) -> Any:
        if self._ie_factory is None:
            return None
        if self._ie_bridge is None:
            try:
                self._ie_bridge, self._ie_error = self._ie_factory(), None
            except Exception as error:
                self._ie_bridge, self._ie_error = None, str(error)
        return self._ie_bridge

    def _ie_tabs(self) -> list[dict[str, Any]]:
        bridge = self._ie()
        if bridge is None:
            return []
        try:
            return bridge.tabs()
        except Exception as error:  # the bridge stopped: start a fresh one next time
            self._ie_bridge, self._ie_error = None, str(error)
            return []

    # ---- the Java bridge ---------------------------------------------------------------

    def _ensure_host(self) -> Host:
        if self._host is None or (self._host._session is None):
            try:
                self._session = self._open_session()
                self._session_error = None
            except Exception as error:
                self._session, self._session_error = None, str(error)
            self._host = Host(self._session, self._session_error, self._own_bits, feed_factory=self._feed_factory)
        return self._host

    def _windows(self) -> list[str]:
        self._ensure_host()
        if self._session is None:
            return []
        try:
            return [title for _, title in self._session.windows()]
        except Exception:
            return []

    # ---- routes ------------------------------------------------------------------------

    def state(self, _: dict[str, Any]) -> dict[str, Any]:
        host = self._host
        recording = bool(host and host._recorder is not None) or self._ie_session is not None
        return {
            "version": __version__, "bits": self._own_bits, "recording": recording,
            "server": self.store.get("server_url", DEFAULT_SERVER), "recordings": len(self.store.listing()),
        }

    def check(self, _: dict[str, Any]) -> dict[str, Any]:
        windows = self._windows()
        dll_path, dll_error = self._dll_info() if self._session is None else (self._session.call(lambda b: str(b.dll_path)), None)
        if self._session is None and not dll_error:
            dll_error = self._session_error
        report = diagnose.check(self._own_bits, dll_path, dll_error, windows, self._installs(), self._users(), self._switched_on())
        if self._ie_factory is None:
            return report
        tabs = self._ie_tabs()
        infos: dict[int, dict[str, Any]] = {}
        for tab in tabs[:3]:
            try:
                infos[tab["id"]] = self._ie_bridge.probe(tab["id"])
            except Exception as error:
                self._ie_error = str(error)
        return diagnose.with_ie(report, diagnose.ie_items(tabs, infos, None if tabs else self._ie_error), readable=bool(tabs))

    def enable_bridge(self, _: dict[str, Any]) -> dict[str, Any]:
        report = diagnose.check(self._own_bits, None, None, [], self._installs(), self._users(), True)
        try:
            return {"done": diagnose.enable_bridge(self._installs(), report["wanted_bits"]),
                    "next": "Đóng hết Edge/IE, mở lại màn hình cần ghi, rồi bấm Kiểm tra lại."}
        except RuntimeError as error:
            raise UserError(str(error)) from error

    def switch_bits(self, _: dict[str, Any]) -> dict[str, Any]:
        report = self.check({})
        if report["wanted_bits"] == self._own_bits:
            return {"switched": False}
        if self._relauncher is None:
            raise UserError(f"Máy này chưa có bản {report['wanted_bits']}-bit của agent.")
        self._relauncher(report["wanted_bits"])
        return {"switched": True, "bits": report["wanted_bits"]}

    def windows(self, _: dict[str, Any]) -> dict[str, Any]:
        java = self._windows()
        pages = [IE_PREFIX + tab["title"] for tab in self._ie_tabs()]
        return {"windows": java + pages, "error": None if pages else self._session_error}

    # ---- recording ---------------------------------------------------------------------

    def _record_start_ie(self, title: str) -> dict[str, Any]:
        from rookie_agent.ie.session import IeSession

        if self._ie_session is not None:
            raise UserError("Đang ghi rồi. Bấm Dừng ghi trước.")
        tab = next((t for t in self._ie_tabs() if t["title"] == title), None)
        if tab is None:
            raise UserError("Không thấy trang này trong Internet Explorer. Mở màn hình cần ghi rồi thử lại.")
        session = IeSession(self._ie_bridge, tab["id"], title)
        try:
            info = session.start()
        except Exception as error:
            raise UserError(f"Chưa ghi được trang Internet Explorer: {error}") from error
        if info.get("frames") and not info.get("attached"):
            session.stop()
            raise UserError("Không gắn được bộ ghi vào trang này (trang bị chặn hoặc các khung khác nguồn). "
                            "Chạy lệnh ie-probe trong thư mục windows-agent rồi gửi kết quả cho nhóm phát triển.")
        self._ie_session = session
        return {"recording": True}

    def _record_stop_ie(self, name: str) -> dict[str, Any]:
        session, self._ie_session = self._ie_session, None
        events = session.stop()
        if not events:
            hint = f" ({session.error})" if session.error else ""
            if session.info.get("frames"):
                hint += f" Bộ ghi đã gắn vào {session.info.get('attached', 0)}/{session.info['frames']} khung của trang."
            raise UserError("Chưa ghi được thao tác nào. Hãy thao tác trên ứng dụng sau khi bấm Bắt đầu ghi, rồi mới Dừng." + hint)
        document = self.store.save(session.session_id, events, name, engine="ie")
        return {"id": document["session_id"], **summarize_events(document["events"])}

    def record_start(self, body: dict[str, Any]) -> dict[str, Any]:
        title = str(body.get("window") or "")
        if title.startswith(IE_PREFIX):
            return self._record_start_ie(title[len(IE_PREFIX):])
        host = self._ensure_host()
        if self._session is None:
            raise UserError(self._session_error or "Chưa dùng được cầu nối Java. Mở mục Kiểm tra máy.")
        try:
            self._session.wait_for_window(title, timeout=3)
        except Exception:
            raise UserError("Không thấy cửa sổ Java nào. Mở màn hình cần ghi rồi thử lại.") from None
        reply = host.handle({"cmd": "start"})
        if not reply["ok"]:
            raise UserError(reply["error"])
        return {"recording": True}

    def record_stop(self, body: dict[str, Any]) -> dict[str, Any]:
        if self._ie_session is not None:
            return self._record_stop_ie(str(body.get("name") or "").strip())
        host = self._ensure_host()
        reply = host.handle({"cmd": "stop"})
        if not reply["ok"]:
            raise UserError(reply["error"])
        if not reply["events"]:
            raise UserError("Chưa ghi được thao tác nào. Hãy thao tác trên ứng dụng sau khi bấm Bắt đầu ghi, rồi mới Dừng.")
        name = str(body.get("name") or "").strip()
        document = self.store.save(reply["session_id"], reply["events"], name)
        return {"id": document["session_id"], **summarize_events(document["events"])}

    def recordings(self, _: dict[str, Any]) -> dict[str, Any]:
        return {"recordings": self.store.listing()}

    def delete_recording(self, body: dict[str, Any]) -> dict[str, Any]:
        self.store.delete(str(body.get("id")))
        return {}

    # ---- server and learning -------------------------------------------------------------

    def _server(self) -> Any:
        return self._server_client(self.store.get("server_url", DEFAULT_SERVER))

    def server_check(self, body: dict[str, Any]) -> dict[str, Any]:
        url = str(body.get("url") or self.store.get("server_url", DEFAULT_SERVER)).strip()
        if not url.startswith(("http://", "https://")):
            raise UserError("Địa chỉ máy chủ phải bắt đầu bằng http://")
        self.store.put("server_url", url)
        try:
            self._server_client(url).health()
        except ServerError as error:
            return {"ok": False, "url": url, "message": str(error)}
        return {"ok": True, "url": url, "message": "Kết nối được máy chủ."}

    def server_start(self, _: dict[str, Any]) -> dict[str, Any]:
        if self._server_starter is None:
            raise UserError("Máy này chưa có gói máy chủ đi kèm.")
        url = self._server_starter()
        self.store.put("server_url", url)
        return self.server_check({"url": url})

    def learn(self, body: dict[str, Any]) -> dict[str, Any]:
        ids = [str(i) for i in body.get("ids") or []]
        title = str(body.get("title") or "").strip()
        if len(ids) < 2:
            raise UserError("Chọn ít nhất 2 bản ghi của cùng một việc. Nên ghi 3 lần.")
        if not title:
            raise UserError("Đặt tên cho việc này, ví dụ: Vấn tin tài khoản.")
        client = self._server()
        try:
            for session_id in ids:
                document = self.store.load(session_id)
                client.post_session(session_id, document["engine"], document["events"])
                self.store.update(session_id, uploaded=True)
            reply = client.learn(None, ids, title)
        except ServerError as error:
            raise UserError(str(error)) from error
        workflow = reply["workflow"]
        shown = {
            "title": workflow.get("title") or title,
            "inputs": [item.get("label") or item["name"] for item in workflow["inputs"]],
            "steps": [
                {"text": friendly_step(step["action"], (step.get("target") or {}).get("label")),
                 "risk": RISK_WORDS.get(step["risk"], step["risk"]), "mode": MODE_WORDS.get(step["mode"], step["mode"]),
                 "risk_key": step["risk"], "mode_key": step["mode"]}
                for step in workflow["steps"]
            ],
            "warnings": reply["warnings"],
        }
        flows = [flow for flow in self.store.get("flows", []) if flow.get("title") != shown["title"]]
        self.store.put("flows", flows + [{**shown, "learned_at": time.strftime("%Y-%m-%d %H:%M:%S")}])
        return shown

    def flows(self, _: dict[str, Any]) -> dict[str, Any]:
        return {"flows": self.store.get("flows", [])}

    # ---- a file to send back to the developers -----------------------------------------------

    def diagnostics(self, _: dict[str, Any]) -> dict[str, Any]:
        report = self.check({})
        content = {"version": __version__, "bits": self._own_bits, "check": report,
                   "recordings": [{k: r[k] for k in ("steps", "events", "typed_fields", "typed_values_kept")} for r in self.store.listing()]}
        path = self.store.home / "chan-doan.json"
        path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"path": str(path)}

    ROUTES = {
        "GET /api/state": "state", "GET /api/check": "check", "POST /api/enable-bridge": "enable_bridge",
        "POST /api/switch-bits": "switch_bits", "GET /api/windows": "windows", "POST /api/record/start": "record_start",
        "POST /api/record/stop": "record_stop", "GET /api/recordings": "recordings", "POST /api/recordings/delete": "delete_recording",
        "POST /api/server/check": "server_check", "POST /api/server/start": "server_start", "POST /api/learn": "learn",
        "POST /api/diagnostics": "diagnostics", "GET /api/flows": "flows",
    }

    def dispatch(self, method: str, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        name = self.ROUTES.get(f"{method} {path}")
        if name is None:
            return 404, {"error": "Không có chức năng này."}
        try:
            return 200, getattr(self, name)(body)
        except UserError as error:
            return 400, {"error": str(error)}
        except Exception as error:  # never show a stack trace to a teller
            return 500, {"error": f"Có lỗi ngoài dự kiến: {error}"}
