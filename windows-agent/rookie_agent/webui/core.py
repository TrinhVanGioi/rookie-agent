"""What the local web page does. No HTTP in here, so it can be tested with fakes.

The page runs on the teller's own PC and talks to this module. Everything it shows is in plain words:
no ids, no selectors. What is kept on disk (the recorded sessions) never holds a typed value of a sensitive
field; the Recorder has already removed it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
import unicodedata
import urllib.parse
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rookie_agent import __version__, diagnose
from rookie_agent.ie import files
from rookie_agent.native_host import Host
from rookie_agent.server_client import ServerClient, ServerError

DEFAULT_SERVER = "http://localhost:8000"
DEFAULT_CACHE_SECONDS = 300   # task 8.7: a look-up answered in this session is shown again for 5 minutes without calling the server
IE_PREFIX = "Internet Explorer: "
DEFAULT_CASE_REGEX = r"LCT\d{5}"   # the transfer ids of the mock site
ROLE_NAMES = ("maker", "checker")

ACTION_WORDS = {
    "click": "Bấm", "input": "Nhập vào", "select": "Chọn ở", "submit": "Nhấn Enter ở", "navigate": "Mở màn hình",
    "fill": "Nhập vào", "goto": "Mở màn hình", "read_value": "Đọc giá trị ở", "wait_for": "Chờ",
}
RISK_WORDS = {"read": "chỉ xem", "write": "ghi dữ liệu, luôn hỏi trước khi làm", "money": "liên quan tiền, luôn hỏi trước khi làm"}
MODE_WORDS = {"auto": "tự chạy", "review": "dừng cho bạn xem", "approve": "chờ bạn duyệt"}


HOOK_BLOCK_FILE = "request-hook-blocked-v2.json"
DIAG_LEVELS = ("noread", "nolisten", "none", "only-click", "only-key", "only-field", "only-page",
               "only-focusin", "only-focusout", "only-change", "field-empty", "body-prop", "body-label", "body-place", "body-uid", "body-value", "body-meta")   # to find what upsets a page


def replay_has_twin(api: list[dict[str, Any]]) -> bool:
    return bool(api) and all(n.get("shape") for n in api)


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
        self._run: dict[str, Any] | None = None   # the flow being run now, or the last one run
        self._last_requests: list[dict[str, Any]] = []   # the requests of the last recording, in memory only
        self._cache: dict[str, dict[str, Any]] = {}       # task 8.7: look-ups of this session, in memory only; gone when the agent closes
        self._last_seen: list[dict[str, Any]] = []   # what the screen showed in the last recording, in memory only

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
            "version": __version__, "bits": self._own_bits, "recording": recording, "preview": bool(getattr(self._ie_session, "preview", False)),
            "server": self.store.get("server_url", DEFAULT_SERVER), "recordings": len(self.store.listing()),
            "server_user": (self.store.get("server_user") or {}).get("display"),
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
        tabs = self._ie_tabs()
        pages = [IE_PREFIX + tab["title"] for tab in tabs]
        return {"windows": java + pages, "ie": [{"id": tab["id"], "title": tab["title"]} for tab in tabs],
                "error": None if pages else self._session_error}

    def _find_ie_tab(self, window: str) -> dict[str, Any] | None:
        """The tab the teller chose. By its id when the choice has one (the title of a page changes after the sign in, the tab does
        not). By title otherwise; a title that no longer matches finds the page only when it is the one Internet Explorer page open:
        with several, nothing is guessed."""
        tabs = self._ie_tabs()
        if window.startswith("ie-tab:"):
            try:
                wanted = int(window.split(":", 1)[1])
            except ValueError:
                return None
            return next((t for t in tabs if t["id"] == wanted), None)
        title = window[len(IE_PREFIX):] if window.startswith(IE_PREFIX) else window
        found = next((t for t in tabs if t["title"] == title), None)
        return found or (tabs[0] if len(tabs) == 1 else None)

    # ---- recording ---------------------------------------------------------------------

    # -v2: the sites blocked before the fix of the TouchPoint tabs (VML) were blocked by mistake; that list is no longer read.
    def _hook_blocked(self) -> set[str]:
        """Sites (host names only) where recording the requests upset the page: they are recorded without it from then on."""
        try:
            return set(json.loads((self.store.home / HOOK_BLOCK_FILE).read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return set()

    def _hook_block(self, host: str) -> None:
        blocked = self._hook_blocked() | {host}
        (self.store.home / HOOK_BLOCK_FILE).write_text(json.dumps(sorted(blocked)), encoding="utf-8")

    def _record_start_ie(self, window: str, preview: bool = False, requests: bool | None = None, diag: str = "") -> dict[str, Any]:
        from rookie_agent.ie.session import IeSession

        if self._ie_session is not None:
            raise UserError("Đang ghi rồi. Bấm Dừng ghi trước.")
        tab = self._find_ie_tab(window)
        if tab is None:
            raise UserError("Không thấy trang này trong Internet Explorer (trang có thể đã đổi tên). Bấm Tải lại rồi chọn lại màn hình cần ghi.")
        host = str(tab.get("host") or "")
        if requests is None:       # automatic: record the requests unless this site once upset by it
            blocked = self._hook_blocked()
            requests = host not in blocked and "*" not in blocked     # "*" in the file: no site is hooked (to tell a page error from the recorder's)
        if diag:                      # a diagnosis run changes nothing else: the requests are left alone too
            requests = False
        session = IeSession(self._ie_bridge, tab["id"], tab["title"], requests=requests, diag=diag)
        session.on_hook_failed = self._hook_block
        words = {"noread": "không đọc lại màn hình sau mỗi thao tác", "nolisten": "không nghe sự kiện nào (chỉ đọc màn hình)",
                 "none": "không chạy script nào trong trang (chỉ nhìn qua cửa sổ)",
                 "only-click": "chỉ nghe click", "only-key": "chỉ nghe phím", "only-field": "chỉ nghe ô nhập (vào ô, rời ô, đổi giá trị)",
                 "only-page": "chỉ nghe việc tải và rời trang", "only-focusin": "chỉ nghe việc vào ô", "only-focusout": "chỉ nghe việc rời ô",
                 "only-change": "chỉ nghe việc đổi giá trị", "field-empty": "có gắn trình nghe vào ô nhưng trình nghe không làm gì",
                 "body-prop": "trình nghe ô chỉ đọc thuộc tính của ô", "body-label": "trình nghe ô chỉ đọc nhãn của ô",
                 "body-place": "trình nghe ô chỉ đọc vị trí của ô và tiêu đề trang",
                 "body-uid": "trình nghe ô chỉ đọc uniqueID", "body-value": "trình nghe ô chỉ đọc giá trị", "body-meta": "trình nghe ô chỉ đọc kiểu, tên và id"}
        if diag:
            session.notes.append(f"{time.strftime('%H:%M:%S')} Chẩn đoán lỗi trang: {words[diag]}. Ghi yêu cầu: tắt.")
        else:
            session.notes.append(f"{time.strftime('%H:%M:%S')} Ghi yêu cầu: " + ("bật." if requests else f"tắt (trang «{host or '?'}» từng bị lỗi khi ghi yêu cầu, hoặc đã tắt bằng cấu hình)."))
        session.preview = preview           # a preview follows what the teller does and keeps nothing
        try:
            info = session.start()
        except Exception as error:
            raise UserError(f"Chưa ghi được trang Internet Explorer: {error}") from error
        if not info.get("frames") and diag != "none":
            session.stop()
            raise UserError("Không thấy khung nào của trang để ghi (trang đang tải lại hoặc đã đóng). Đợi trang tải xong, bấm Tải lại rồi Bắt đầu ghi lại.")
        if info.get("frames") and not info.get("attached") and diag not in ("nolisten", "none"):
            session.stop()
            reason = str(info.get("inject_error") or "").strip()
            raise UserError((f"Trang từ chối bộ ghi: {reason[:200]}. " if reason else "") +
                            "Không gắn được bộ ghi vào trang này (trang bị chặn hoặc các khung khác nguồn). "
                            "Chạy lệnh ie-probe trong thư mục windows-agent rồi gửi kết quả cho nhóm phát triển.")
        self._ie_session = session
        return {"recording": True}

    def _record_stop_ie(self, name: str) -> dict[str, Any]:
        session, self._ie_session = self._ie_session, None
        events = session.stop()
        self._last_seen = session.seen
        self._last_requests = session.requests
        if getattr(session, "preview", False):
            return {"preview": True, **summarize_events(events)}       # nothing is saved, no trace file is written
        trace_path = self._write_trace(session)
        if not events:
            hint = f" ({session.error})" if session.error else ""
            if session.info.get("frames"):
                hint += f" Bộ ghi đã gắn vào {session.info.get('attached', 0)}/{session.info['frames']} khung của trang."
            if trace_path:
                hint += f" Bản ghi thô đã che để xem: {trace_path}"
            raise UserError("Chưa ghi được thao tác nào. Hãy thao tác trên ứng dụng sau khi bấm Bắt đầu ghi, rồi mới Dừng." + hint)
        try:    # task 12.1 (SADPT): what the screen showed after each action, names only; it becomes the steps' postconditions
            from rookie_agent.adaptive import expect

            events = expect.attach_shows(events, list(getattr(session, "seen", []) or []))
        except Exception:  # noqa: BLE001  the recording is saved whatever happens here
            pass
        document = self.store.save(session.session_id, events, name, engine="ie")
        kept = 0
        try:   # Gate 7: the page's requests as templates, on this PC only (what was typed is a mark, never a value)
            from rookie_agent.ie import replay

            found = replay.templates(getattr(session, "raw", []), document["events"], list(getattr(session, "requests", []) or []))
            if found:
                self.store.update(session.session_id, requests=found)
                kept = len(found)
        except Exception:  # noqa: BLE001  the recording itself is saved whatever happens here
            pass
        try:    # task 11.11: a screen the page fills from an answer, field by field: the labels and where each comes from (no value)
            from rookie_agent.ie import report

            maps = report.learn(list(getattr(session, "requests", []) or []), list(getattr(session, "seen", []) or []))
            if maps:
                self.store.update(session.session_id, report_maps=maps)
        except Exception:  # noqa: BLE001
            pass
        try:    # Gate 9: the case this recording is about (a keyed hash, never the id) and the role it was recorded in
            extra: dict[str, Any] = {"role": self._role()}
            key = self._case_key([str(r.get(k) or "") for r in getattr(session, "requests", []) or [] for k in ("url", "req", "res")])
            if key:
                extra["case_key"] = key
            self.store.update(session.session_id, **extra)
        except Exception:  # noqa: BLE001
            pass
        findings: list[dict[str, str]] = []
        try:    # task 11.3: the recording checks itself and says, in plain words, what to record again
            from rookie_agent.ie import check

            findings = check.check(self.store.load(session.session_id), notes=list(getattr(session, "notes", []) or []),
                                   requests_on=bool(getattr(session, "_requests", True)))
        except Exception:  # noqa: BLE001
            pass
        return {"id": document["session_id"], "trace_file": trace_path, "requests_kept": kept, "check": findings, **summarize_events(document["events"])}

    def _write_trace(self, session: Any) -> str | None:
        """Everything the page reported, masked, as one file the teller or the team can open to see what was recorded.
        It never breaks the stop: a failure here only means no file."""
        try:
            from rookie_agent.ie.trace import TraceBuilder

            builder = TraceBuilder(app_title=session.app_title, trace_id=session.session_id)
            builder.add_session(session.session_id, session.raw)
            builder.add_screens(session.session_id, getattr(session, "seen", []))
            builder.add_requests(session.session_id, getattr(session, "requests", []))
            folder = self.store.home / "traces"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{session.session_id}.trace.json"
            path.write_text(json.dumps(builder.build(), ensure_ascii=False, indent=2), encoding="utf-8")
            (folder / f"{session.session_id}.reach.txt").write_text("\n".join(getattr(session, "notes", [])), encoding="utf-8")
            return str(path)
        except Exception:  # noqa: BLE001
            return None

    def record_start(self, body: dict[str, Any]) -> dict[str, Any]:
        title = str(body.get("window") or "")
        if title.startswith(IE_PREFIX) or title.startswith("ie-tab:"):
            return self._record_start_ie(title, preview=bool(body.get("preview")), requests=None if body.get("requests") is None else bool(body.get("requests")),
                                         diag=str(body.get("diag") or "") if str(body.get("diag") or "") in DIAG_LEVELS else "")
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
        url = self.store.get("server_url", DEFAULT_SERVER)
        if self._server_starter is not None and url.rstrip("/") in (DEFAULT_SERVER, "http://127.0.0.1:8000"):
            # the bundled server stops with the agent: start it again on use instead of "cannot connect" (it returns at once when it already runs)
            try:
                url = self._server_starter()
            except RuntimeError as error:
                raise UserError(str(error)) from error
        client = self._server_client(url)
        token = self.store.get("server_token")
        if token:
            client.token = token          # task 10.1: the login of this PC on the server
        return client

    def server_login(self, body: dict[str, Any]) -> dict[str, Any]:
        """Log in to the server once (its AD account); only the token it gives is kept on this PC, never the password."""
        name, password = str(body.get("username") or "").strip(), str(body.get("password") or "")
        if not name or not password:
            raise UserError("Nhập tên đăng nhập và mật khẩu.")
        client = self._server()
        client.token = None
        try:
            reply = client.login(name, password)
        except ServerError as error:
            if getattr(error, "status", None) == 409:
                raise UserError("Máy chủ này không cần đăng nhập: cứ dùng bình thường.") from error
            raise UserError(str(error).split(": ", 1)[-1] if getattr(error, "status", None) in (401, 429) else str(error)) from error
        self.store.put("server_token", reply["token"])
        self.store.put("server_user", reply["user"])
        return {"user": reply["user"]}

    def admin_open(self, body: dict[str, Any]) -> dict[str, Any]:
        """Task 11.5: the address of the admin page for one flow («Sửa trên sơ đồ», «Chia sẻ»), signed in by a one-time code when the
        server asks for logins. The page opens it in a new window; nothing else is sent."""
        client = self._server()
        base = str(getattr(client, "base_url", "") or self.store.get("server_url", DEFAULT_SERVER)).rstrip("/")
        params: dict[str, str] = {}
        flow_id = str(body.get("workflow_id") or "")
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", flow_id):
            params["flow"] = flow_id
        try:
            code = (client.handoff() or {}).get("code") if getattr(client, "token", None) else None
        except ServerError as error:
            raise UserError(str(error)) from error
        if code:
            params["code"] = code
        return {"url": base + "/admin/" + ("?" + urllib.parse.urlencode(params) if params else "")}

    def server_logout(self, _: dict[str, Any]) -> dict[str, Any]:
        try:
            self._server().logout()
        except (ServerError, UserError):
            pass                          # the token is dropped on this PC either way
        self.store.put("server_token", None)
        self.store.put("server_user", None)
        return {}

    def server_check(self, body: dict[str, Any]) -> dict[str, Any]:
        url = str(body.get("url") or self.store.get("server_url", DEFAULT_SERVER)).strip()
        if not url.startswith(("http://", "https://")):
            raise UserError("Địa chỉ máy chủ phải bắt đầu bằng http://")
        self.store.put("server_url", url)
        client = self._server_client(url)
        try:
            client.health()
        except ServerError as error:
            return {"ok": False, "url": url, "message": str(error)}
        login = True
        try:      # a server with logins off (ROOKIE_AUTH=off, the bundled one) needs none: the page hides the login row
            login = (client._call("GET", "/auth/me").get("mode") or "off") != "off"
        except ServerError as error:
            login = getattr(error, "status", None) == 401       # 401: logins are on and this PC is not signed in; 404: a server before Gate 10
        except Exception:  # noqa: BLE001
            login = False
        return {"ok": True, "url": url, "login": login,
                "message": "Kết nối được máy chủ." + ("" if login else " Máy chủ này không cần đăng nhập.")}

    def server_start(self, _: dict[str, Any]) -> dict[str, Any]:
        if self._server_starter is None:
            raise UserError("Máy này chưa có gói máy chủ đi kèm.")
        url = self._server_starter()
        self.store.put("server_url", url)
        return self.server_check({"url": url})

    def learn(self, body: dict[str, Any]) -> dict[str, Any]:
        ids = [str(i) for i in body.get("ids") or []]
        title = str(body.get("title") or "").strip()
        if not ids:
            raise UserError("Chọn ít nhất 1 bản ghi. Nên ghi 3 lần với dữ liệu khác nhau để agent học chắc hơn.")
        if not title:
            raise UserError("Đặt tên cho việc này, ví dụ: Vấn tin tài khoản.")
        client = self._server()
        documents = {session_id: self.store.load(session_id) for session_id in ids}
        if all(d.get("engine") == "ie" for d in documents.values()):
            from rookie_agent.ie import clean

            # task 11.4: the recordings cleaned together by the rules of ie/clean.py; the stored recordings are not changed
            documents = dict(zip(ids, clean.clean([documents[i] for i in ids])))
        self._cleaned = documents
        try:
            for session_id in ids:
                document = documents[session_id]
                try:
                    client.post_session(session_id, document["engine"], self._events_for_server(document), **self._process_fields(document))
                except ServerError as error:
                    if getattr(error, "status", None) != 409:   # 409: the server already has this recording, from an earlier Học
                        raise
                self.store.update(session_id, uploaded=True)
            reply = client.learn(None, ids, title, traces=self._traces_of(ids))
        except ServerError as error:
            raise UserError(str(error)) from error
        for call in (reply.get("llm") or {}).get("calls", []):
            self._call_log().add("codie", str(call.get("mode") or ""), bool(call.get("ok")), float(call.get("seconds") or 0),
                                 prompt_chars=int(call.get("prompt_chars") or 0), note=str(call.get("note") or ""))
        workflow = reply["workflow"]
        shown = {
            "title": workflow.get("title") or title,
            "inputs": [item.get("label") or item["name"] for item in workflow["inputs"]],
            "steps": [
                {"text": friendly_step(step["action"], (step.get("target") or {}).get("label")),
                 "risk": RISK_WORDS.get(step["risk"], step["risk"]), "mode": MODE_WORDS.get(step["mode"], step["mode"]),
                 "risk_key": step["risk"], "mode_key": step["mode"], "optional": (step.get("optional") or {}).get("mode")}
                for step in workflow["steps"]
            ],
            "warnings": reply["warnings"],
            "method": reply.get("method", "rule"), "questions": list(reply.get("questions") or []),
            "fallback_reason": reply.get("fallback_reason"),
        }
        api = self._api_for(workflow, ids)
        shown["api_count"] = len(api)
        try:      # task 11.4: what the flow can do, in plain words, right after Học
            from rookie_agent.ie import check

            shown["quality"] = check.learned(api, workflow)
        except Exception:  # noqa: BLE001
            pass
        put_api = getattr(client, "put_api", None)
        if api and put_api is not None and workflow.get("id") and workflow.get("version"):
            from rookie_agent.ie import api_share

            try:      # task 10.3: the server gets the nodes masked; the full templates stay on this PC
                put_api(workflow["id"], workflow["version"], api_share.for_server(api))
            except ServerError as error:
                shown["warnings"] = list(shown["warnings"]) + [f"Chưa gửi được nút API lên máy chủ ({error}); luồng vẫn chạy được trên máy này."]
        from rookie_agent.assistant import savings

        manual = [s for s in (savings.recording_seconds(self.store.load(i).get("events") or []) for i in ids) if s]   # task 11.8: by hand
        flows = [flow for flow in self.store.get("flows", []) if flow.get("title") != shown["title"]]
        self.store.put("flows", flows + [{**shown, "workflow": workflow, "api": api, "input_formats": self._input_formats(workflow, ids),
                                          "manual_seconds": manual, "learned_at": time.strftime("%Y-%m-%d %H:%M:%S")}])
        return shown

    def _input_formats(self, workflow: dict[str, Any], ids: list[str]) -> dict[str, str]:
        """How the teller typed each date input while recording (only the shape, like dd/mm/yyyy; never the value), kept on this PC so the
        Assistant writes a date the way the page expects it."""
        from rookie_agent.assistant import slots

        names = {str(i.get("label") or i["name"]): i["name"] for i in workflow.get("inputs", [])}
        found: dict[str, str] = {}
        for session_id in ids:
            try:
                events = self.store.load(session_id).get("events") or []
            except (OSError, ValueError):
                continue
            for event in events:
                name = names.get(str((event.get("target") or {}).get("label") or ""))
                tag = slots.detect_format(str(event["value"])) if event.get("type") == "input" and event.get("value") is not None else None
                if name and tag and name not in found:
                    found[name] = tag
        return found

    def _api_for(self, workflow: dict[str, Any], ids: list[str]) -> list[dict[str, Any]]:
        """Task 8.4: the API calls of the first chosen recording that has them, as the nodes of the flow (kept on this PC only)."""
        from rookie_agent.ie import replay

        for session_id in ids:
            try:
                document = (getattr(self, "_cleaned", None) or {}).get(session_id) or self.store.load(session_id)
            except (OSError, ValueError):
                continue
            if document.get("requests"):
                from rookie_agent.ie import report

                nodes = replay.build_api(workflow, document["events"], document["requests"],
                                         describe=lambda s: friendly_step(s["action"], (s.get("target") or {}).get("label")))
                report.attach(nodes, document.get("report_maps"))      # the printable page a node's answer makes (task 11.11)
                return nodes
        return []

    def _traces_of(self, ids: list[str]) -> list[dict[str, Any]] | None:
        """The masked traces of the chosen recordings, in the order chosen. None unless there is one for every recording: the model
        needs all of them to compare, and a recording without a trace (a Java one, an older one) is learned the old way."""
        found = []
        for session_id in ids:
            path = self.store.home / "traces" / f"{session_id}.trace.json"
            try:
                found.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                return None
        return found

    def flows(self, _: dict[str, Any]) -> dict[str, Any]:
        def api_nodes(api: list[dict[str, Any]], flow: dict[str, Any]) -> list[dict[str, Any]]:
            from rookie_agent.ie import read_rules, replay

            rules, steps = read_rules.load(), {s["id"]: s for s in (flow.get("workflow") or {}).get("steps", []) if "id" in s}
            by_id = {n["id"]: n for n in api}
            call_group = {c: g["id"] for g in replay.groups_of(api) for c in g["calls"]}
            out = []
            for g in replay.groups_of(api):
                calls = [by_id[c] for c in g["calls"]]
                links: dict[str, str] = {}
                for n in calls:                 # where a value comes from: the step whose answer gave it (a link inside the step is not shown)
                    for name, rule in n["links"].items():
                        if call_group.get(rule["from"], g["id"]) != g["id"]:
                            links[name] = call_group[rule["from"]]
                by_default = g["risk"] == "write" and g["step_id"] in steps and read_rules.write_by_default(steps[g["step_id"]], rules)
                kept = (flow.get("read_confirmed") or {}).get(g["step_id"]) if by_default else None
                out.append({"id": g["id"], "label": g["label"], "risk": g["risk"], "step_id": g["step_id"], "ms": g["ms"],
                            "asks_read": by_default, "read_confirmed": (kept or {}).get("at") or "" if kept is not None else None,
                            "kind": calls[0]["kind"], "call_count": len(calls),
                            "ready": all(n["complete"] and not n["unresolved"] for n in calls),
                            "inputs": sorted({x for n in calls for x in re.findall("⟦([a-z0-9_]+)⟧", n["url"] + n["body"] + n["headers"])}
                                             - {x for n in calls for x in n["links"]}),
                            "links": links,
                            "calls": [{"id": n["id"], "method": n["method"], "name": replay.call_name(n), "kind": n["kind"],
                                       "ready": bool(n["complete"] and not n["unresolved"])} for n in calls]})
            return out

        from rookie_agent.assistant import savings

        def listed(flow: dict[str, Any]) -> dict[str, Any]:
            workflow = flow.get("workflow") or {}
            return {k: v for k, v in flow.items() if k not in ("workflow", "requests", "api", "read_confirmed", "previous")} | {
                # task 12.5: what the draft waiting for Duyệt is (a step pointed at again, a part taught again, an old version back)
                "repair_kind": (flow.get("repair") or {}).get("kind") or ("pick" if flow.get("repair") else None),
                "has_previous": bool(flow.get("previous")),
                "savings": savings.summary(list(flow.get("manual_seconds") or []), savings.run_seconds(self.store.home / "audit.jsonl", str(flow.get("title")))),
                # the nodes the canvas draws (task 8.5): one per step, with the calls it fires; never a template's body
                "api_nodes": api_nodes(flow.get("api") or [], flow),
                "approved": workflow.get("status") == "approved", "engine": workflow.get("engine"),
                "workflow_id": workflow.get("id"), "twin_ready": replay_has_twin(flow.get("api") or []), "has_api": bool(flow.get("api")),
                "step_count": len(workflow.get("steps", [])),
                "repair_pending": bool(flow.get("repair")), "repair": None, "fingerprint": None,
                "step_ids": [step.get("id", "") for step in workflow.get("steps", [])],   # the canvas lights the node of the step running
                # task 12.5: «Dạy lại đoạn này» on the flow card starts after one of these steps; the draft's version is what a twin trial runs
                "teach_steps": [{"id": step["id"], "label": (step.get("target") or {}).get("label") or step.get("intent") or step["id"]}
                                for step in workflow.get("steps") or [] if step.get("id")],
                "repair_version": ((flow.get("repair") or {}).get("workflow") or {}).get("version"),
                "input_fields": [{"name": i["name"], "label": i.get("label") or i["name"]} for i in workflow.get("inputs", [])]}

        return {"flows": [listed(flow) for flow in self.store.get("flows", [])]}

    # ---- running a learned flow (tasks 4.42 to 4.45) -------------------------------------------

    def _flow(self, title: str) -> dict[str, Any]:
        flow = next((f for f in self.store.get("flows", []) if f.get("title") == title), None)
        if flow is None or not flow.get("workflow"):
            raise UserError("Không thấy luồng này. Hãy Học lại rồi chạy.")
        return flow

    def flow_approve(self, body: dict[str, Any]) -> dict[str, Any]:
        """The person approves this agent: only then can it run (outside a trial). The approval is of this version of the flow."""
        title = str(body.get("title") or "")
        flows = self.store.get("flows", [])
        flow = next((f for f in flows if f.get("title") == title), None)
        if flow is None or not flow.get("workflow"):
            raise UserError("Không thấy luồng này. Hãy Học lại rồi duyệt.")
        repaired = flow.pop("repair", None)
        if repaired:                      # the corrected version is what the person approves now (task 6.3)
            # task 12.5: the version it replaces is kept (the last few) so that it can be brought back, approved again
            flow["previous"] = (list(flow.get("previous") or []) + [flow["workflow"]])[-3:]
            flow["workflow"] = repaired["workflow"]
            self._audit_line({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "title": title, "mode": "repair", "status": "approved",
                              "version": flow["workflow"].get("version"), "steps": [{"id": s, "status": "selectors_changed", "detail": ""} for s in repaired.get("steps", [])]})
        flow["workflow"]["status"] = "approved"
        self.store.put("flows", flows)
        return {"approved": True}

    # ---- task 12.5 (SADPT, Delta Learning): teach again only the part that changed --------------------------------------------

    def _flow_named(self, title: str) -> dict[str, Any]:
        flow = next((f for f in self.store.get("flows", []) if f.get("title") == title), None)
        if flow is None or not flow.get("workflow"):
            raise UserError("Không thấy việc này trên máy. Hãy Học lại.")
        return flow

    def teach_start(self, body: dict[str, Any]) -> dict[str, Any]:
        """«Dạy lại đoạn này»: record only the new part, from the step where the run stopped."""
        title, after = str(body.get("title") or ""), str(body.get("after_step") or "")
        flow = self._flow_named(title)
        if not after or after not in {s["id"] for s in flow["workflow"]["steps"]}:
            raise UserError("Cần biết dạy lại từ bước nào: bấm «Dạy lại đoạn này» ngay ở chỗ việc vừa dừng.")
        if not flow["workflow"].get("id"):
            raise UserError("Việc này chưa có trên máy chủ nên chưa dạy lại từng đoạn được. Hãy Học lại khi có máy chủ.")
        started = self._record_start_ie(str(body.get("window") or ""), requests=True)
        self._teach = {"title": title, "after_step": after}
        return {**started, "teaching": True, "after_step": after}

    def teach_stop(self, body: dict[str, Any]) -> dict[str, Any]:
        teach = getattr(self, "_teach", None)
        if not teach or self._ie_session is None:
            raise UserError("Chưa bắt đầu dạy lại đoạn nào.")
        self._teach = None
        saved = self._record_stop_ie(f"Dạy lại «{teach['title']}»")
        made = self._teach_finish(teach["title"], teach["after_step"], saved["id"])
        return {**saved, **made}

    def _teach_finish(self, title: str, after_step: str, session_id: str) -> dict[str, Any]:
        """The recorded part to the server, which puts it in after `after_step`; the answer is kept as a draft of this flow, waiting for
        a person's Duyệt (`flow_approve`). The version in use does not change until then."""
        from rookie_agent.ie import clean

        flow = self._flow_named(title)
        workflow = flow["workflow"]
        document = clean.clean([self.store.load(session_id)])[0]
        client = self._server()
        try:
            try:
                client.post_session(session_id, "ie", self._events_for_server(document), **self._process_fields(document))
            except ServerError as error:
                if getattr(error, "status", None) != 409:
                    raise
            reply = client.teach(workflow["id"], int(workflow.get("version") or 1), after_step, session_id)
        except ServerError as error:
            raise UserError(str(error)) from error
        draft = reply["workflow"]
        added = list((reply.get("change") or {}).get("added") or [])
        flows = self.store.get("flows", [])
        for one in flows:
            if one.get("title") == title:
                one["repair"] = {"workflow": draft, "steps": added, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": "teach"}
        self.store.put("flows", flows)
        self._audit_line({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "title": title, "mode": "teach", "status": "waiting_approval",
                          "version": draft.get("version"), "after": after_step, "steps": [{"id": s, "status": "added", "detail": ""} for s in added]})
        by_id = {s["id"]: s for s in draft.get("steps") or []}
        return {"version": draft.get("version"), "added": [friendly_step(by_id[s]["action"], (by_id[s].get("target") or {}).get("label")) for s in added if s in by_id],
                "warnings": list(reply.get("warnings") or [])}

    def flow_delete(self, body: dict[str, Any]) -> dict[str, Any]:
        """Remove a learned flow from this PC (the Luồng list of Rookie Agent). Recordings stay. If the server also has it, that copy
        is removed when this PC is allowed to; a server that cannot be reached does not keep the flow on this PC."""
        title = str(body.get("title") or "").strip()
        flows = self.store.get("flows", [])
        flow = next((item for item in flows if item.get("title") == title), None)
        if flow is None:
            raise UserError("Không thấy luồng này.")
        if self._run is not None and self._run.get("thread") is not None and self._run["thread"].is_alive() and self._run.get("title") == title:
            raise UserError("Luồng này đang chạy. Bấm Dừng khẩn rồi xoá.")
        workflow_id = (flow.get("workflow") or {}).get("id")
        note = ""
        if workflow_id and self.store.get("server_url"):
            try:
                self._server().delete_workflow(workflow_id)
            except ServerError as error:
                if error.status == 403:
                    note = "Đã xoá trên máy này. Bản trên máy chủ vẫn còn: chỉ chủ luồng hoặc quản trị xoá được."
                elif error.status != 404:
                    note = "Đã xoá trên máy này. Máy chủ chưa xoá được."
        self.store.put("flows", [item for item in flows if item.get("title") != title])
        self._cache_clear()
        return {"deleted": title, "server": note}

    def flow_restore(self, body: dict[str, Any]) -> dict[str, Any]:
        """«Quay về bản trước»: the version before comes back as a new draft; it is approved again before it is used."""
        title = str(body.get("title") or "")
        flow = self._flow_named(title)
        previous = list(flow.get("previous") or [])
        if not previous:
            raise UserError("Chưa có bản trước để quay về.")
        before = previous[-1]
        draft = None
        if before.get("id"):
            try:
                draft = self._server().restore(before["id"], int(before.get("version") or 1))["workflow"]
            except ServerError:
                draft = None             # no server now: the draft is made here, the same way
        if draft is None:
            draft = {**json.loads(json.dumps(before)), "version": int(flow["workflow"].get("version") or 1) + 1, "status": "draft"}
        flows = self.store.get("flows", [])
        for one in flows:
            if one.get("title") == title:
                one["repair"] = {"workflow": draft, "steps": [], "time": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": "restore"}
        self.store.put("flows", flows)
        self._audit_line({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "title": title, "mode": "restore", "status": "waiting_approval",
                          "version": draft.get("version"), "to": before.get("version"), "steps": []})
        return {"version": draft.get("version"), "to": before.get("version")}

    def _read_confirm(self, title: str, step_id: str) -> None:
        """The teller said this step only looks: kept on the flow saved on this PC, per step (the time only; no value, no name)."""
        flows = self.store.get("flows", [])
        flow = next((f for f in flows if f.get("title") == title), None)
        if flow is not None:
            flow.setdefault("read_confirmed", {})[step_id] = {"at": time.strftime("%Y-%m-%d %H:%M:%S")}
            self.store.put("flows", flows)

    def flow_read_withdraw(self, body: dict[str, Any]) -> dict[str, Any]:
        """Take the confirmation back: the next run asks again. What a look-up kept in memory is forgotten too."""
        title, step_id = str(body.get("title") or ""), str(body.get("step_id") or "")
        flows = self.store.get("flows", [])
        flow = next((f for f in flows if f.get("title") == title), None)
        if flow is None or step_id not in (flow.get("read_confirmed") or {}):
            raise UserError("Bước này chưa được xác nhận là chỉ xem.")
        del flow["read_confirmed"][step_id]
        if not flow["read_confirmed"]:
            del flow["read_confirmed"]
        self.store.put("flows", flows)
        self._cache_clear()
        return {"withdrawn": True}

    # ---- versions edited on the admin page (task 10.7) ---------------------------------------------------------------------------
    # The PC keeps running its own copy until the teller takes a new one. A draft is tried on the twin here (its result goes up, so
    # the version can become «đã chạy thử»); only a version approved on the server, by someone other than whoever edited it, is taken.

    @staticmethod
    def _flow_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
        """What changed, in words, between two copies of a flow ({workflow, api}): nodes added, removed, renamed, risk, Duyệt, order."""
        from rookie_agent.ie import replay

        def nodes(copy: dict[str, Any]) -> list[dict[str, Any]]:
            if copy.get("api"):
                return [{"id": g["id"], "label": g["label"], "risk": g["risk"], "approve": bool(g.get("approve"))} for g in replay.groups_of(copy["api"])]
            return [{"id": s["id"], "label": friendly_step(s["action"], (s.get("target") or {}).get("label")), "risk": s.get("risk", "read"),
                     "approve": s.get("mode") == "approve"} for s in (copy.get("workflow") or {}).get("steps", [])]

        before, after = nodes(old), nodes(new)
        was, now = {n["id"]: n for n in before}, {n["id"]: n for n in after}
        lines = [f"Thêm nút «{n['label']}» ({RISK_WORDS.get(n['risk'], n['risk'])})" for n in after if n["id"] not in was]
        lines += [f"Xoá nút «{n['label']}»" for n in before if n["id"] not in now]
        for n in after:
            o = was.get(n["id"])
            if o is None:
                continue
            if o["label"] != n["label"]:
                lines.append(f"Đổi tên «{o['label']}» thành «{n['label']}»")
            if o["risk"] != n["risk"]:
                lines.append(f"«{n['label']}»: rủi ro {RISK_WORDS.get(o['risk'], o['risk'])} → {RISK_WORDS.get(n['risk'], n['risk'])}")
            if n["approve"] and not o["approve"]:
                lines.append(f"«{n['label']}»: thêm bước Duyệt")
        if [n["id"] for n in after if n["id"] in was] != [n["id"] for n in before if n["id"] in now]:
            lines.append("Đổi thứ tự các nút")
        return lines or ["Không khác về các nút (có thể chỉ đổi nhãn ô nhập)."]

    def _server_copy(self, flow: dict[str, Any], reply: dict[str, Any]) -> dict[str, Any]:
        from rookie_agent.ie import api_share

        api = api_share.merge(flow.get("api") or [], reply["api"]) if reply.get("api") is not None else (flow.get("api") or [])
        return {"workflow": reply["workflow"], "api": api}

    def flow_updates(self, _: dict[str, Any]) -> dict[str, Any]:
        """For each flow of this PC that the server knows: a newer version there, what changed, and what the teller can do with it."""
        found = []
        try:
            client = self._server()
            for flow in self.store.get("flows", []):
                workflow = flow.get("workflow") or {}
                if not workflow.get("id"):
                    continue
                try:
                    reply = client.flow_version(workflow["id"])
                except ServerError as error:
                    if getattr(error, "status", None) in (403, 404):
                        continue
                    raise
                newest = reply["workflow"]
                if int(newest["version"]) <= int(workflow.get("version") or 0):
                    continue
                edit = client.edit_record(workflow["id"], newest["version"])
                found.append({"title": flow["title"], "workflow_id": workflow["id"], "local_version": workflow.get("version"),
                              "version": newest["version"], "status": newest["status"], "edited_by": (edit or {}).get("edited_by"),
                              "changes": self._flow_changes({"workflow": workflow, "api": flow.get("api")}, self._server_copy(flow, reply)),
                              "can_take": newest["status"] == "approved", "can_try": newest["status"] == "draft"})
        except (ServerError, UserError) as error:
            return {"updates": found, "error": f"Chưa hỏi được máy chủ ({error}). Luồng trên máy này vẫn chạy như cũ."}
        return {"updates": found}

    def _update_target(self, body: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], Any]:
        flows = self.store.get("flows", [])
        flow = next((f for f in flows if f.get("title") == str(body.get("title") or "")), None)
        if flow is None or not (flow.get("workflow") or {}).get("id"):
            raise UserError("Không thấy luồng này trên máy.")
        client = self._server()
        try:
            reply = client.flow_version(flow["workflow"]["id"], int(body.get("version") or 0) or None)
        except ServerError as error:
            raise UserError(str(error)) from error
        return flows, flow, reply, client

    def flow_update_take(self, body: dict[str, Any]) -> dict[str, Any]:
        """Take a version approved on the server: it replaces this PC's copy (the full templates stay from this PC)."""
        flows, flow, reply, client = self._update_target(body)
        if reply["workflow"]["status"] != "approved":
            raise UserError("Bản này chưa được Duyệt trên máy chủ. Chạy thử trên bản sao, rồi nhờ người khác (không phải người sửa) Duyệt.")
        copy = self._server_copy(flow, reply)
        old_version = flow["workflow"].get("version")
        steps = {s["id"] for s in copy["workflow"].get("steps", [])}
        flow["workflow"], flow["api"] = copy["workflow"], copy["api"]
        flow.pop("repair", None)
        if flow.get("read_confirmed"):
            flow["read_confirmed"] = {k: v for k, v in flow["read_confirmed"].items() if k in steps}
        flow["inputs"] = [i.get("label") or i["name"] for i in copy["workflow"].get("inputs", [])]
        self.store.put("flows", flows)
        self._cache_clear()
        edit = None
        try:
            edit = client.edit_record(copy["workflow"]["id"], copy["workflow"]["version"])
        except ServerError:
            pass
        self._audit_line({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "title": flow["title"], "mode": "update", "status": "taken",
                          "from_version": old_version, "version": copy["workflow"]["version"], "edited_by": (edit or {}).get("edited_by")})
        return {"taken": True, "version": copy["workflow"]["version"]}

    # ---- a flow shared by someone else (task 11.7): take it, then make it runnable here with one recording of this PC --------------

    def flows_shared(self, _: dict[str, Any]) -> dict[str, Any]:
        """Approved flows the server lets this login see that this PC does not have yet (shared with the unit or everyone)."""
        try:
            rows = self._server().list_workflows()
        except ServerError as error:
            raise UserError(str(error)) from error
        here = {(f.get("workflow") or {}).get("id") for f in self.store.get("flows", [])}
        approved: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row.get("status") == "approved" and row["id"] not in here:
                approved[row["id"]] = {"workflow_id": row["id"], "title": row.get("title") or row["id"], "owner": row.get("owner_display"), "version": row["version"]}
        return {"flows": list(approved.values())}

    def flow_import(self, body: dict[str, Any]) -> dict[str, Any]:
        from rookie_agent.ie import api_share

        workflow_id = str(body.get("workflow_id") or "")
        try:
            reply = self._server().approved_workflow(workflow_id)
        except ServerError as error:
            raise UserError(str(error)) from error
        from rookie_agent.server_client import digest

        if reply.get("api") is not None and digest(reply["api"]) != reply.get("api_digest"):
            raise UserError("Nút API nhận về không khớp mã kiểm tra (digest); không lấy.")
        workflow = reply["workflow"]
        title = str(workflow.get("title") or workflow_id)
        api = api_share.merge([], reply.get("api") or []) if reply.get("api") else []
        flows = [f for f in self.store.get("flows", []) if f.get("title") != title]
        self.store.put("flows", flows + [{"title": title, "workflow": workflow, "api": api, "imported": True, "warnings": [],
                                          "inputs": [i.get("label") or i["name"] for i in workflow.get("inputs", [])], "steps": [],
                                          "learned_at": time.strftime("%Y-%m-%d %H:%M:%S")}])
        need = sum(1 for n in api if n.get("complete") is False)
        return {"title": title, "needs_recording": need > 0,
                "message": f"Đã lấy «{title}». " + ("Làm mẫu một lần trên máy này (Ghi rồi bấm «Làm mẫu một lần để dùng») để chạy được bằng yêu cầu." if need else "")}

    def flow_bind(self, body: dict[str, Any]) -> dict[str, Any]:
        """One recording of this PC gives the shared flow the full templates it lacks (api_share.bind)."""
        from rookie_agent.ie import api_share, clean, replay

        flows = self.store.get("flows", [])
        flow = next((f for f in flows if f.get("title") == str(body.get("title") or "")), None)
        if flow is None:
            raise UserError("Không thấy luồng này trên máy.")
        listing = self.store.listing()
        recording = str(body.get("recording_id") or (listing[0]["id"] if listing else ""))
        if not recording:
            raise UserError("Chưa có bản ghi nào. Bấm Ghi, làm việc này một lần, Dừng ghi rồi bấm lại.")
        (document,) = clean.clean([self.store.load(recording)])
        local = replay.build_api(flow["workflow"], document["events"], document.get("requests") or [],
                                 describe=lambda s: friendly_step(s["action"], (s.get("target") or {}).get("label")))
        nodes, missing = api_share.bind(flow.get("api") or [], local)
        flow["api"] = nodes
        self.store.put("flows", flows)
        bound = sum(1 for n in nodes if n.get("bound"))
        return {"bound": bound, "missing": missing,
                "message": (f"Đã ghép {bound} lời gọi từ bản ghi của máy này." + (f" Chưa ghép được: {', '.join(missing)}; hãy ghi đủ các bước đó rồi bấm lại." if missing else ""))}

    def flow_update_try(self, body: dict[str, Any]) -> dict[str, Any]:
        """Try a draft version on the twin, without taking it. When it finishes, the server is told (a passed sandbox run), and the
        version becomes «đã chạy thử»; someone other than whoever edited it then approves it on the admin page."""
        _, flow, reply, client = self._update_target(body)
        if reply["workflow"]["status"] != "draft":
            raise UserError("Chỉ chạy thử bản nháp. Bản này đã qua bước chạy thử.")
        copy = self._server_copy(flow, reply)
        trial = {**flow, "workflow": copy["workflow"], "api": copy["api"]}
        workflow_id, version = copy["workflow"]["id"], copy["workflow"]["version"]

        def told(result: dict[str, Any]) -> None:
            try:
                client.post_test_run(workflow_id, version, {"status": result["status"], "message": str(result.get("message") or "")[:300],
                                                            "steps": [{"id": s["id"], "status": s["status"]} for s in result.get("steps", [])]})
                if result["status"] == "finished":
                    client.set_status(workflow_id, version, "tested")
            except ServerError:
                pass          # the person sees the result here; the server can be told by trying again

        stage = {"flow": trial, "role": "maker", "label": f"{flow['title']} (bản v{version}, thử)"}
        return self.twin_run({"inputs": body.get("inputs") or {}, "name": stage["label"]}, stages=[stage], on_done=told,
                             ref={"id": workflow_id, "version": version})

    def run_start(self, body: dict[str, Any], via: str | None = None) -> dict[str, Any]:
        from rookie_agent.ie.driver import IeDriver
        from rookie_agent.runner import required_inputs, run_workflow
        from rookie_agent.webui.run import WebController, trial_of
        from rookie_agent.ie import read

        if self._run is not None and self._run["thread"].is_alive():
            raise UserError("Đang chạy một luồng. Đợi xong hoặc bấm Dừng khẩn.")
        if self._ie_session is not None:
            raise UserError("Đang ghi. Bấm Dừng ghi trước khi chạy.")
        flow = self._flow(str(body.get("title") or ""))
        if body.get("mode") == "simulate":
            return self._simulate_start(flow, body, via)
        workflow = flow["workflow"]
        mode = "dry" if body.get("mode") == "dry" else "run"
        inputs = {str(k): str(v) for k, v in (body.get("inputs") or {}).items() if str(v) != ""}
        if workflow.get("engine") != "ie":
            raise UserError("Luồng này không phải của Internet Explorer; chạy luồng Java bằng lệnh `run`.")
        stops_before = None
        pending = (flow.get("repair") or {}).get("workflow")
        if pending:
            # task 6.3: a corrected agent not yet approved again: only its read-only part runs, on this PC (where it was corrected)
            workflow, stops_before = trial_of(pending)
            if not workflow["steps"]:
                raise UserError("Agent này có bản sửa đang chờ Duyệt và bắt đầu bằng bước ghi hoặc tiền. Bấm «Duyệt agent này» trước khi chạy.")
            mode = "dry"
        if mode == "dry" and not pending:
            workflow, stops_before = trial_of(workflow)
            if not workflow["steps"]:
                raise UserError("Luồng này bắt đầu bằng bước ghi hoặc tiền, nên không có phần chỉ-đọc để chạy thử.")
        elif workflow.get("status") != "approved":
            raise UserError("Luồng này chưa được duyệt. Bấm «Duyệt agent này» trước khi chạy.")
        missing = [name for name in required_inputs(workflow) if name not in inputs]
        if missing:
            raise UserError("Còn thiếu thông tin cần nhập: " + ", ".join(missing))
        bridge = self._ie()
        if bridge is None:
            raise UserError("Chưa dùng được cầu nối Internet Explorer. Mở mục Kiểm tra máy.")
        tab = self._find_ie_tab(str(body.get("window") or ""))
        if tab is None:
            raise UserError("Không thấy trang Internet Explorer để chạy. Mở màn hình rồi chọn lại.")
        # task 6.4: the start screen against the one of the last run that went through; changed -> say so before a real run
        from rookie_agent.ie import locate

        try:
            now_print = IeDriver(bridge, tab["id"]).fingerprint()
        except Exception:  # noqa: BLE001  no fingerprint: nothing to compare, the run is as before
            now_print = []
        before = flow.get("fingerprint") or []
        changed = bool(now_print and before and locate.screen_similarity(before, now_print) < locate.SAME_SCREEN)
        # task 12.3 (SADPT): a version 4 flow that only reads checks every step itself (postconditions, finding an element again), so
        # a changed screen is no reason to refuse it; a flow with a write or money step is still stopped here first
        self_checking = int(workflow.get("schema_version") or 0) >= 4 and all(s["risk"] == "read" for s in workflow["steps"])
        if changed and mode == "run" and not body.get("confirm_changed") and not self_checking:
            try:
                bridge.unbind()
            except Exception:  # noqa: BLE001
                pass
            raise UserError("Màn hình đã đổi so với lần chạy trước (ô hoặc nút khác đi). Bấm «Chạy thử (chỉ đọc)» để xem bước nào cần chỉ lại, "
                            "hoặc bấm Chạy lần nữa nếu vẫn muốn chạy.")
        stop = threading.Event()

        def see() -> str:
            return read.describe(read.parse(bridge.read()))

        shared: dict[str, Any] = {**{i["name"]: str(i["default"]) for i in workflow.get("inputs", []) if i.get("default") is not None}, **inputs}
        controller = WebController(stop, shared, see)       # the run and the card read and write the same values, in memory only
        state: dict[str, Any] = {"mode": mode, "title": flow["title"], "controller": controller, "stop": stop, "result": None,
                                 "stops_before": stops_before, "started": time.time(), "via": via, "input_names": sorted(inputs)}

        def work() -> None:
            try:
                driver = IeDriver(bridge, tab["id"])
                result = run_workflow(workflow, inputs, driver, controller, stop, values=shared, engine="ie", versions=(2, 3, 4),
                                      allow_write_on_real=bool(self.store.get("ie_allow_write_on_real", False)),
                                      download_steps={n["step_id"]: str(n.get("label") or n["step_id"]).split(" → ")[0] for n in flow.get("api") or []
                                                      if n.get("kind") == "file" and n.get("step_id")})
                if mode == "dry" and result["status"] == "finished":
                    result["message"] = "Chạy thử xong" + (f", dừng trước bước «{stops_before}» (bước ghi hoặc tiền)." if stops_before else ".")
            except Exception as error:  # noqa: BLE001  the person sees a plain sentence, never a stack
                result = {"status": "failed", "message": f"Chạy bị lỗi: {error}", "steps": []}
            finally:
                try:
                    bridge.unbind()
                except Exception:  # noqa: BLE001
                    pass
            if changed and mode == "dry":
                result["message"] = "Màn hình đã đổi so với lần chạy trước. " + str(result.get("message") or "")
            elif changed and self_checking:
                result["message"] = "Màn hình đã đổi so với lần chạy trước; agent đã tự kiểm từng bước. " + str(result.get("message") or "")
            state["result"] = result
            if result["status"] == "finished" and mode == "run" and now_print:
                self._keep_fingerprint(flow["title"], now_print)
            if result.get("repairs"):
                self._save_repair(flow["title"], result["repairs"])
            self._audit(state, result)

        state["thread"] = threading.Thread(target=work, name="ie-run", daemon=True)
        self._run = state
        state["thread"].start()
        return {"started": True}

    def _simulate_start(self, flow: dict[str, Any], body: dict[str, Any], via: str | None) -> dict[str, Any]:
        """Task 7.5: the flow run by its learned requests, sent from inside the teller's IE page (the page's own session). The screen is
        not touched; only read-only steps send; what comes back is shown on the canvas and kept in memory only."""
        from rookie_agent.ie import read_rules, replay
        from rookie_agent.runner import required_inputs
        from rookie_agent.webui.run import WebController

        workflow, api = flow["workflow"], flow.get("api") or []
        if workflow.get("engine") != "ie":
            raise UserError("Chạy trên sơ đồ chỉ có ở luồng Internet Explorer.")
        if not api:
            raise UserError("Luồng này chưa có API nào để chạy. Ghi lại việc này khi «Ghi yêu cầu: bật», rồi Học lại.")
        inputs = {str(k): str(v) for k, v in (body.get("inputs") or {}).items() if str(v) != ""}
        sign_in = replay._sign_in_steps(workflow)
        needed = {name for n in api if n.get("step_id") not in sign_in for name in replay._MARK.findall(n["url"] + n["body"] + n["headers"])}
        missing = sorted(n for n in needed if n not in inputs and n in set(required_inputs(workflow)) | {i["name"] for i in workflow.get("inputs", [])})
        if missing:
            labels = {i["name"]: i.get("label") or i["name"] for i in workflow.get("inputs", [])}
            raise UserError("Còn thiếu thông tin cần nhập: " + ", ".join(labels.get(n, n) for n in missing))
        bridge = self._ie()
        if bridge is None:
            raise UserError("Chưa dùng được cầu nối Internet Explorer. Mở mục Kiểm tra máy.")
        tab = self._find_ie_tab(str(body.get("window") or ""))
        if tab is None:
            raise UserError("Chọn trang Internet Explorer đã đăng nhập (request đi trong phiên của trang đó; giao diện không bị đụng tới).")
        stop = threading.Event()
        controller = WebController(stop, dict(inputs), lambda: "")
        state: dict[str, Any] = {"mode": "simulate", "title": flow["title"], "controller": controller, "stop": stop, "result": None,
                                 "stops_before": None, "started": time.time(), "via": via, "input_names": sorted(inputs)}
        # Task 8.7: what a look-up answered is kept for this session, in memory only, so the same customer is not asked again and again.
        # The key is this PC's user, the IE tab (its sign-in), the flow as learned and the values given; a closed tab, a sign-in page in
        # an answer, «Xoá bộ nhớ phiên» or the agent closing ends it. Only finished runs are kept: they sent read-only calls only.
        self._cache_prune(bridge)
        key = self._cache_key(flow, tab, inputs)
        kept = None if body.get("refresh") else self._cache.get(key)
        if kept is not None:
            controller.steps = json.loads(json.dumps(kept["steps"]))
            controller.details = json.loads(json.dumps(kept["details"]))
            result = json.loads(json.dumps(kept["result"]))
            age = int(time.time() - kept["at"])
            result["message"] = (f"Lấy từ bộ nhớ phiên lúc {time.strftime('%H:%M:%S', time.localtime(kept['at']))} ({age} giây trước), "
                                 "không gọi lại máy chủ. Bấm «Làm mới» để lấy dữ liệu mới.")
            result["cached"] = True
            state["result"] = result
            state["thread"] = threading.Thread(target=lambda: None, name="ie-simulate-cached", daemon=True)
            state["thread"].start()
            self._run = state
            self._audit(state, result)
            return {"started": True, "cached": True}

        def work() -> None:
            try:
                bridge.bind(tab["id"], peek=True)   # the page's requests are remembered in its memory, to find the session it uses now

                def peek(node: dict[str, Any]) -> list[str]:
                    path = node["url"].split("?", 1)[0]
                    path = re.sub(r"^[A-Za-z][A-Za-z0-9+.\-]*://[^/]*", "", path)
                    return bridge.last_requests(node.get("frame") or "*", path) or bridge.last_requests("*", path)

                def peek_urls() -> list[str]:
                    return bridge.live_urls()

                def send(node: dict[str, Any], url: str, headers: str, body_text: str) -> dict[str, Any]:
                    answer = bridge.send(node["frame"], node["method"], url, headers, body_text)
                    if answer.get("error") == "no_frame" and node["frame"] != "top":
                        # the frame of the recording is named or placed differently now: the tab's top page sends it, same site, same session
                        answer = bridge.send("top", node["method"], url, headers, body_text)
                    elif (answer.get("error") == "không lấy được nội dung file từ trang" and node["frame"] != "top" and node.get("kind") == "file"
                          and str(node.get("risk") or "read") == "read" and url.startswith(("/", "http://", "https://"))):
                        # task 11.2 (the TouchPoint look-alike): the bytes of a file a frame's request got cannot always be read over COM;
                        # the same read-only call from the tab's top page (same site, same session, an address that does not depend on the frame) can
                        answer = bridge.send("top", node["method"], url, headers, body_text)
                    return answer

                def save_file(data: bytes, ctype: str, disposition: str) -> dict[str, Any]:
                    # the file answer of a call: written here, on this PC, and nowhere else (docs/design.md 6.4)
                    folder = self._download_dir()
                    path = files.save(folder, files.file_name(flow["title"], ctype, disposition, data=data), data)
                    made: dict[str, Any] = {"name": path.name, "path": str(path)}
                    if files.sniff(data) == "xml":       # data sent as XML: a readable, printable page is made beside the file as it came
                        rows = files.xml_rows(data)
                        if rows:
                            page = files.save(folder, f"{path.stem} (bản đọc).html", files.xml_report_html(flow["title"], rows).encode("utf-8"))
                            made["report"] = {"name": page.name, "path": str(page)}
                    return made

                def save_report(title: str, html: str) -> dict[str, Any]:
                    # the printable page made from the data a call returned: on this PC, in the Rookie folder, like a file (docs/design.md 14)
                    page = files.save(self._download_dir(), f"{files.clean_title(flow['title'])}-{time.strftime('%Y%m%d-%H%M%S')} (bản in).html", html.encode("utf-8"))
                    return {"name": page.name, "path": str(page)}

                result = replay.run_api(workflow, api, inputs, send, controller, stop, peek=peek, peek_urls=peek_urls, save_report=save_report, read_rules=read_rules.load(),
                                        confirmed=flow.get("read_confirmed") or {},
                                        remember=lambda step_id: self._read_confirm(flow["title"], step_id), save_file=save_file)
            except Exception as error:  # noqa: BLE001
                result = {"status": "failed", "message": f"Chạy mô phỏng bị lỗi: {error}", "steps": []}
            finally:
                try:
                    bridge.unbind()
                except Exception:  # noqa: BLE001
                    pass
            saved_a_file = any(r.get("file") for d in controller.details.values() for r in d.get("requests", []))
            if result["status"] == "finished" and not saved_a_file:      # an export is made again each time: its file is not "remembered"
                self._cache[key] = {"at": time.time(), "tab": tab["id"], "steps": json.loads(json.dumps(controller.steps)),
                                    "details": json.loads(json.dumps(controller.details)), "result": dict(result)}
            elif "đăng nhập" in str(result.get("message")):
                self._cache_clear(tab["id"])      # the session of this tab has ended: what it gave is not kept
            state["result"] = result
            if result.get("contract_changed"):
                self._mark_contract(flow["title"], list(result["contract_changed"]))
            self._audit(state, result)        # step ids and states only: no request, no answer

        state["thread"] = threading.Thread(target=work, name="ie-simulate", daemon=True)
        self._run = state
        state["thread"].start()
        return {"started": True}

    # ---- task 8.7: the session cache of look-ups (memory only) ---------------------------------------------------------------

    def _cache_key(self, flow: dict[str, Any], tab: dict[str, Any], inputs: dict[str, str]) -> str:
        import getpass

        return json.dumps([getpass.getuser(), tab["id"], str(tab.get("host") or ""), flow["title"], flow.get("learned_at"),
                           sorted(inputs.items())], ensure_ascii=False)

    def _cache_seconds(self) -> int:
        try:
            return max(0, int(self.store.get("cache_seconds", DEFAULT_CACHE_SECONDS)))
        except (TypeError, ValueError):
            return DEFAULT_CACHE_SECONDS

    def _cache_prune(self, bridge: Any) -> None:
        """Expired entries go; so do those of an IE tab that is not open any more (its sign-in has ended with it)."""
        limit = time.time() - self._cache_seconds()
        try:
            open_tabs = {t["id"] for t in bridge.tabs()}
        except Exception:  # noqa: BLE001  tabs unknown: only the age counts
            open_tabs = None
        for key in list(self._cache):
            entry = self._cache[key]
            if entry["at"] <= limit or (open_tabs is not None and entry["tab"] not in open_tabs):
                del self._cache[key]

    def _cache_clear(self, tab_id: Any = None) -> int:
        gone = [k for k, v in self._cache.items() if tab_id is None or v["tab"] == tab_id]
        for key in gone:
            del self._cache[key]
        return len(gone)

    # ---- files that a call answered (a report as PDF): saved on this PC only --------------------------------------------------

    def _download_dir(self) -> Path:
        """`%USERPROFILE%\\Downloads\\Rookie`, or the folder set in the agent's settings (`download_folder`, an absolute path)."""
        return files.downloads_dir(str(self.store.get("download_folder") or "") or None)

    def _open_path(self, path: Path) -> None:
        import os

        os.startfile(str(path))  # type: ignore[attr-defined]  Windows only: the program the teller's PC uses for this kind of file

    def _print_path(self, path: Path) -> bool:
        """Send a saved file to the printer with the program this PC uses for it. False when there is none for printing (the caller opens it instead)."""
        import os

        try:
            os.startfile(str(path), "print")  # type: ignore[attr-defined]  Windows only
            return True
        except OSError:
            return False

    def file_open(self, body: dict[str, Any]) -> dict[str, Any]:
        """«Mở file» / «Mở thư mục» of a saved file. Only a path inside the Rookie folder is opened, and only a kind of file that a person reads
        (never a program or a page); anything else is refused. Local only: nothing is sent."""
        target = Path(str(body.get("path") or ""))
        folder = self._download_dir()
        if not str(body.get("path") or "") or not files.inside(folder, target):
            raise UserError("Chỉ mở được file đã lưu trong thư mục Rookie của máy này.")
        if body.get("folder"):
            self._open_path(target.parent if target.parent != target else folder)
            return {"opened": "folder"}
        if not target.is_file():
            raise UserError("Không còn file này (đã bị xoá hoặc dời đi).")
        if target.suffix.lstrip(".").lower() not in files.OPENABLE and not files.is_report(target):      # a report this agent made is the one page it opens
            raise UserError("Không mở loại file này từ đây. Mở thư mục để xem.")
        if body.get("print"):             # «In»: the same file inside the Rookie folder, sent to the printer; opened for the teller when it cannot be
            if self._print_path(target):
                return {"opened": "file", "printed": True}
            self._open_path(target)
            return {"opened": "file", "printed": False}
        self._open_path(target)
        return {"opened": "file"}

    def cache_clear(self, _: dict[str, Any]) -> dict[str, Any]:
        """«Xoá bộ nhớ phiên»: every kept look-up is forgotten now."""
        return {"cleared": self._cache_clear()}

    def cache_state(self, _: dict[str, Any]) -> dict[str, Any]:
        """How many look-ups are kept and for how long: counts only, never what they hold."""
        return {"kept": len(self._cache), "seconds": self._cache_seconds()}

    def _save_repair(self, title: str, repairs: list[dict[str, Any]]) -> None:
        """Task 6.3: the elements the teller pointed at make a new version of the agent that changes only those steps' selectors
        (risk and mode as they were). It waits for an approval; until then only its read-only part runs, on this PC."""
        flows = self.store.get("flows", [])
        flow = next((f for f in flows if f.get("title") == title), None)
        if flow is None or not flow.get("workflow"):
            return
        base = (flow.get("repair") or {}).get("workflow") or flow["workflow"]
        fixed = json.loads(json.dumps(base))
        changed = {r["step_id"]: r["selectors"] for r in repairs}
        for step in fixed["steps"]:
            if step["id"] in changed and changed[step["id"]]:
                step["target"] = {**(step.get("target") or {}), "selectors": list(changed[step["id"]])}
        fixed["version"] = int(flow["workflow"].get("version") or 1) + 1
        fixed["status"] = "draft"
        steps = sorted(set((flow.get("repair") or {}).get("steps", [])) | set(changed))
        flow["repair"] = {"workflow": fixed, "steps": steps, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
        self.store.put("flows", flows)
        self._audit_line({"time": flow["repair"]["time"], "title": title, "mode": "repair", "status": "waiting_approval",
                          "version": fixed["version"], "steps": [{"id": s, "status": "selectors_changed", "detail": ""} for s in sorted(changed)],
                          # task 12.3: found again by the agent (strong evidence, checked after) or pointed at by the teller
                          "by": "agent" if all(r.get("auto") for r in repairs) else "teller"})

    def _mark_contract(self, title: str, node_ids: list[str]) -> None:
        """Task 12.4: the calls whose answer came in another form are marked «cần xác minh» on the flow; a run by request then stops
        before sending anything (`replay.run_api`) until the flow is learned again or someone checks the call on the admin page."""
        flows = self.store.get("flows", [])
        for flow in flows:
            if flow.get("title") == title:
                for node in flow.get("api") or []:
                    if node.get("id") in node_ids:
                        node["needs_check"] = True
        self.store.put("flows", flows)

    def _keep_fingerprint(self, title: str, lines: list[str]) -> None:
        flows = self.store.get("flows", [])
        for flow in flows:
            if flow.get("title") == title:
                flow["fingerprint"] = lines
        self.store.put("flows", flows)

    def _audit_line(self, line: dict[str, Any]) -> None:
        try:
            with (self.store.home / "audit.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, ensure_ascii=False) + chr(10))
        except OSError:
            pass

    def _audit(self, state: dict[str, Any], result: dict[str, Any]) -> None:
        """One line per run in `audit.jsonl`: what ran, how it ended, who decided what. Never a value that was typed or read."""
        controller = state["controller"]
        line = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "title": state["title"], "mode": state["mode"], "status": result["status"],
                "seconds": round(time.time() - state["started"], 1), "decisions": list(controller.decisions),
                "steps": [{"id": s["id"], "status": s["status"], "detail": s["detail"]} for s in controller.steps]}
        if state.get("via"):
            line["via"], line["input_names"] = state["via"], state.get("input_names", [])
        if result.get("decisions"):      # task 12.2: the adaptation log (what was seen, how sorted, what done, how it ended): names only
            line["adaptations"] = list(result["decisions"])
        flow = next((f for f in self.store.get("flows", []) if f.get("title") == state["title"]), None)
        workflow = state.get("workflow_ref") or (flow or {}).get("workflow") or {}
        if workflow.get("id"):           # task 10.5: which flow and version ran, so the server can show the run under it
            line["run_id"], line["workflow_id"], line["version"] = uuid.uuid4().hex, workflow["id"], workflow.get("version")
        try:
            with (self.store.home / "audit.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, ensure_ascii=False) + chr(10))
        except OSError:
            pass  # a log that cannot be written must not hide the result from the person
        self._send_runs()

    _SENT = "runs_sent"          # how many lines of audit.jsonl were already sent up (or were not runs of a flow on the server)

    def _send_runs(self) -> None:
        """Task 10.5: send up the runs not sent yet: names and states only (never the detail text of a step, it could hold a value).
        A failure keeps them for the next time; nothing here may stop or hide a run."""
        try:
            lines = (self.store.home / "audit.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        done = int(self.store.get(self._SENT, 0) or 0)
        if done > len(lines):
            done = 0                     # the log was cleared
        word = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
        runs = []
        for raw in lines[done:done + 200]:
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if not line.get("run_id") or not line.get("workflow_id"):
                continue
            adaptations = []
            for row in line.get("adaptations") or []:   # task 12.8: the decision only (where it was can hold a value, so it stays on this PC)
                saw, action, outcome = (str(row.get(k) or "") for k in ("saw", "action", "outcome"))
                change, risk = row.get("change"), row.get("risk")
                step_id = str(row.get("step_id") or "")[:80]
                if not step_id or change not in ("technical", "business", "unknown") or action not in ("reresolve", "ask"):
                    continue
                if not all(word.match(part) for part in (saw, action, outcome)) or re.search(r"\d{4,}", step_id + saw + outcome):
                    continue
                adaptations.append({"step_id": step_id, "saw": saw, "change": change, "action": action, "outcome": outcome,
                                    **({"risk": risk} if risk in ("read", "write", "money") else {})})
            runs.append({
                "run_id": line["run_id"], "time": line["time"], "workflow_id": line["workflow_id"], "version": line.get("version"),
                "title": str(line.get("title") or "")[:80], "mode": str(line.get("mode") or "run"),
                "status": str(line.get("status") or "unknown"), "seconds": float(line.get("seconds") or 0),
                "steps": [{"id": str(s.get("id"))[:80], "status": s["status"] if word.match(str(s.get("status"))) else "other"}
                          for s in line.get("steps") or []],
                "decisions": [{k: d.get(k) for k in ("step_id", "kind", "risk", "approved")} for d in line.get("decisions") or []],
                **({"via": line["via"]} if line.get("via") else {}), "input_names": list(line.get("input_names") or []),
                **({"adaptations": adaptations} if adaptations else {}),
            })
        consumed = min(len(lines), done + 200)
        if not runs:
            self.store.put(self._SENT, consumed)
            return
        try:
            client = self._server()
            post = getattr(client, "post_runs", None)
            if post is None:
                return
            post(runs)
        except Exception:  # noqa: BLE001  the server is away: they go with the next run
            return
        self.store.put(self._SENT, consumed)

    # ---- the Assistant (Gate 5): a sentence in, a card out, a click to run ---------------------

    def _assistant(self) -> Any:
        from rookie_agent.assistant import habits
        from rookie_agent.assistant.planner import Planner

        if getattr(self, "_planner", None) is None:
            def runs() -> dict[str, int]:
                stats = self._habits()
                return {t: v["runs"] for t, v in (stats or {}).get("workflows", {}).items()}

            self._planner = Planner(lambda payload: self._server().plan_request(payload), lambda: self.store.get("flows", []), runs)
        return self._planner

    def _habits(self) -> dict[str, Any] | None:
        from rookie_agent.assistant import habits

        titles = {f.get("title") for f in self.store.get("flows", []) if (f.get("workflow") or {}).get("status") == "approved"}
        stats = habits.build_habits(self.store.home / "audit.jsonl", titles, habits.load_habits(self.store.home))
        habits.save_habits(self.store.home, stats)
        return stats

    def assistant_plan(self, body: dict[str, Any]) -> dict[str, Any]:
        if self._run is not None and self._run["thread"].is_alive():
            return {"plan_id": None, "state": "blocked", "message": "Đang chạy một luồng. Đợi xong hoặc bấm Dừng khẩn.", "candidates": [], "inputs": [], "questions": [], "workflow": None}
        if self._ie_session is not None:
            return {"plan_id": None, "state": "blocked", "message": "Đang ghi. Bấm Dừng ghi trước.", "candidates": [], "inputs": [], "questions": [], "workflow": None}
        return self._assistant().plan(str(body.get("text") or ""))

    def assistant_answer(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._assistant().answer(str(body.get("plan_id") or ""), body.get("choice"), body.get("inputs") or {}, body.get("text"))

    def assistant_run(self, body: dict[str, Any]) -> dict[str, Any]:
        """The person clicked Chạy on a ready card. The run goes through the same door as the flows tab: approval of the agent,
        required inputs and every step's own rule are checked there; this only hands over the title and the inputs."""
        taken = self._assistant().take(str(body.get("plan_id") or ""))
        if taken is None:
            raise UserError("Thẻ này không còn dùng được (đã hết hạn, đã chạy hoặc còn thiếu thông tin). Hãy hỏi lại.")
        title, inputs = taken
        flow = self._flow(title)
        # a look-up the agent learned as API calls only (every step read-only, or confirmed by the teller as «chỉ xem») runs by its calls,
        # with the session cache (task 8.7); anything that writes or moves money goes on the screen, with its approvals
        mode = "simulate" if self._runs_by_request(flow) else "run"
        start = {"title": title, "inputs": inputs, "window": body.get("window"), "mode": mode}
        if body.get("refresh"):
            start["refresh"] = True
        return self.run_start(start, via="assistant")

    def _runs_by_request(self, flow: dict[str, Any]) -> bool:
        """True when every step of the learned calls is a read, or a write only because no rule named it that the teller confirmed as
        «chỉ xem» (kept in `read_confirmed`). A step that writes or moves money for real is never among them."""
        from rookie_agent.ie import read_rules, replay

        api = flow.get("api") or []
        if not api:
            return False
        steps = {s["id"]: s for s in (flow.get("workflow") or {}).get("steps", []) if "id" in s}
        rules, confirmed = read_rules.load(), flow.get("read_confirmed") or {}
        return all(g["risk"] == "read" or (g["step_id"] in confirmed and replay._by_default(g, steps, rules)) for g in replay.groups_of(api))

    # ---- Kho luồng: the agents that are approved and have finished a real run, as cards (local to this PC) ----

    def library(self, _: dict[str, Any]) -> dict[str, Any]:
        from rookie_agent.assistant import library

        finished = library.finished_runs(self.store.home / "audit.jsonl")
        raw = {f.get("title"): f for f in self.store.get("flows", [])}
        cards = []
        for flow in self.flows({})["flows"]:
            if flow["title"] in finished and library.eligible(raw[flow["title"]]):
                cards.append({**flow, **library.card(raw[flow["title"]], flow, finished[flow["title"]])})
        cards.sort(key=lambda c: c["last_run"], reverse=True)
        return {"flows": cards}

    def library_n8n(self, body: dict[str, Any]) -> dict[str, Any]:
        """The n8n file of one card: its single stage, templates only (docs/design.md 6.4); the page saves it on this PC."""
        title = str(body.get("title") or "")
        return self.twin_export({"name": title, "stages": [{"flow_id": title, "role": "maker", "label": title}]})

    def assistant_habits(self, _: dict[str, Any]) -> dict[str, Any]:
        from rookie_agent.assistant import habits

        stats = self._habits()
        return {"frequent": habits.frequent(stats)}

    def run_status(self, _: dict[str, Any]) -> dict[str, Any]:
        state = self._run
        if state is None:
            return {"state": "idle", "steps": [], "ask": None, "result": None}
        controller = state["controller"]
        result = state["result"]
        if result is not None:
            current = result["status"]
        elif controller.ask is not None:
            current = {"approve": "waiting_approval", "pick": "waiting_pick"}.get(controller.ask["kind"], "waiting_review")
        else:
            current = "running"
        return {"state": current, "mode": state["mode"], "title": state["title"], "steps": list(controller.steps),
                "ask": dict(controller.ask) if controller.ask else None, "result": result,
                "details": dict(getattr(controller, "details", {})),
                **({"twin": True, "banner": "BẢN SAO – không gửi hệ thống thật", "stages": state.get("stages", [])} if state.get("twin") else {})}   # task 7.5: what each step sent and got back, in memory only

    def run_decide(self, body: dict[str, Any]) -> dict[str, Any]:
        state = self._run
        choice = body.get("choice")
        if state is None or not state["controller"].decide(str(body.get("ask_id") or ""), bool(body.get("approve")),
                                                          choice if isinstance(choice, int) and not isinstance(choice, bool) else None):
            raise UserError("Câu hỏi này không còn mở (hoặc không đúng câu hỏi). Xem lại màn hình.")
        return {"answered": True}

    def mcp_audit(self, body: dict[str, Any]) -> dict[str, Any]:
        """Task 11.9: one line of audit.jsonl per MCP tool call, in the same file; names and states only (the fields are a fixed list)."""
        word = re.compile(r"^[A-Za-z0-9_.:-]{0,80}$")
        line = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": "mcp", "tool": str(body.get("tool") or "")[:40],
                "title": str(body.get("title") or "")[:80], "status": str(body.get("status") or "")[:40],
                "seconds": float(body.get("seconds") or 0),
                "input_names": [str(n) for n in body.get("input_names") or [] if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", str(n))][:30],
                "idempotency_key": str(body.get("idempotency_key") or "") if word.match(str(body.get("idempotency_key") or "")) else ""}
        self._audit_line(line)
        return {"ok": True}

    def run_stop(self, _: dict[str, Any]) -> dict[str, Any]:
        """Dừng khẩn: wins over every answer, also over an open question."""
        if self._run is not None:
            self._run["stop"].set()
        return {"stopped": True}

    # ---- connection to Codie and the log of calls ------------------------------------------------

    def _call_log(self) -> Any:
        from rookie_agent.codie import CallLog

        if not hasattr(self, "_calls"):
            self._calls = CallLog(self.store.home)
        return self._calls

    def codie_status(self, _: dict[str, Any]) -> dict[str, Any]:
        from rookie_agent import codie

        command = str(self.store.get("codie_command", codie.DEFAULT_COMMAND))
        mode = str(self.store.get("codie_mode", "rookie-design"))
        found = codie.find_command(command)
        return {"command": command, "mode": mode, "found": found,
                "message": f"Tìm thấy lệnh Codie: {found}" if found else f"Chưa thấy lệnh «{command}» trên máy này. Cài Genie Codie CLI hoặc nhập đường dẫn đầy đủ."}

    def codie_test(self, body: dict[str, Any]) -> dict[str, Any]:
        """One real call to Codie with a prompt that holds no data, to see that the whole way works. It is logged like any call."""
        from rookie_agent import codie

        command = str(body.get("command") or codie.DEFAULT_COMMAND).strip()
        mode = str(body.get("mode") or "rookie-design").strip()
        self.store.put("codie_command", command)
        self.store.put("codie_mode", mode)
        run = codie.call(mode, codie.TEST_PROMPT, timeout_s=120, command=command, keep_tail=True)
        ok = run.ok and isinstance(run.result, dict) and run.result.get("pong") is True
        reason = "" if ok else (run.reason or "Codie trả lời nhưng không đúng nội dung thử.")
        self._call_log().add("codie", mode, ok, run.seconds, prompt_chars=len(codie.TEST_PROMPT),
                             note="Thử kết nối: Codie trả lời đúng." if ok else "Thử kết nối: " + reason)
        message = f"Gọi được Codie (mode {mode}) trong {run.seconds:.1f} giây." if ok else reason
        if not ok and "không có khối kết quả" in reason:
            message += " Kiểm tra mode «" + mode + "» đã được thêm vào cấu hình Codie chưa (config/codie-modes.json)."
        return {"ok": ok, "message": message, "seconds": round(run.seconds, 1), "tail": "" if ok else run.tail}

    def ie_inspect(self, body: dict[str, Any]) -> dict[str, Any]:
        """What the open Internet Explorer screen holds, in plain words, and a file with the detail (no values, no text of the page)."""
        title = str(body.get("window") or "")
        if not (title.startswith(IE_PREFIX) or title.startswith("ie-tab:")):
            raise UserError("Chọn một trang Internet Explorer ở mục «Màn hình cần ghi» (tab Ghi và Học) rồi mở đúng màn cần soi.")
        tab = self._find_ie_tab(title)
        if tab is None:
            raise UserError("Không thấy trang này trong Internet Explorer. Bấm Tải lại, chọn lại màn hình rồi thử lại.")
        try:
            info = self._ie_bridge.probe(tab["id"])
        except Exception as error:
            raise UserError(f"Chưa soi được trang: {error}") from error
        frames, unreadable = info.get("frames") or [], info.get("unreadable") or []
        total: dict[str, int] = {}
        for frame in frames:
            for key, count in (frame.get("counts") or {}).items():
                total[key] = total.get(key, 0) + int(count)
        lines = [f"Đọc được {len(frames)} khung của trang." + (f" Có {len(unreadable)} khung KHÔNG đọc được." if unreadable else "")]
        lines.append("Trong các khung đọc được: " + ", ".join(f"{total.get(k, 0)} {label}" for k, label in
                     (("select", "ô chọn"), ("input", "ô nhập/nút"), ("button", "nút"), ("a", "liên kết"), ("iframe", "khung nhúng"),
                      ("object", "object/ActiveX"), ("embed", "embed"), ("applet", "applet"))) + ".")
        for frame in frames:  # where the fields are, and whether the teller can see them
            controls = frame.get("controls") or []
            if controls:
                shown = sum(1 for c in controls if c.get("visible"))
                lines.append(f"Khung «{frame.get('name') or '(trang chính)'}» có {len(controls)} ô/nút "
                             f"({shown} đang hiện trên màn hình, {len(controls) - shown} bị ẩn); kích thước khung {frame.get('size') or '?'}.")
        dialogs = info.get("dialogs") or []
        if dialogs:       # a dialog of IE is a window of its own: what it holds is told apart from the page
            lines.append(f"Đang có {len(dialogs)} hộp thoại mở.")
            for number, dialog in enumerate(dialogs, 1):
                inside = dialog.get("frames") or []
                if not dialog.get("readable") or not inside:
                    lines.append(f"Hộp thoại {number}: không đọc được nội dung (thường là plugin đang hiện file, ví dụ PDF); bộ ghi trang không thấy gì bên trong. "
                                 "Việc lấy file phải dựa vào địa chỉ mà trang mở hộp thoại hoặc request của trang chính.")
                    continue
                count: dict[str, int] = {}
                for frame in inside:
                    for key, value in (frame.get("counts") or {}).items():
                        count[key] = count.get(key, 0) + int(value)
                lines.append(f"Hộp thoại {number}: {len(inside)} khung, " + ", ".join(f"{count.get(k, 0)} {label}" for k, label in
                             (("input", "ô nhập/nút"), ("a", "liên kết"), ("iframe", "khung nhúng"), ("object", "object/ActiveX"), ("embed", "embed"), ("applet", "applet"))) + ".")
        if unreadable:
            lines.append("Khung không đọc được thường là trang khác tên miền hoặc bị chặn: bộ ghi không thấy gì bên trong khung đó, "
                         "và màn đang xem có thể nằm ở đó.")
        if total.get("object", 0) + total.get("embed", 0) + total.get("applet", 0) and not total.get("select", 0) + total.get("input", 0):
            lines.append("Màn này không có ô nhập HTML nhưng có object/ActiveX/applet: nội dung có thể được vẽ bởi một plugin, bộ ghi trang không thấy được.")
        elif not total.get("select", 0) + total.get("input", 0) + total.get("button", 0) and not unreadable:
            lines.append("Không thấy ô nhập hay nút nào: màn này có thể chưa tải xong hoặc không phải HTML.")
        path = self.store.home / "soi-man-hinh.json"
        path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"summary": lines, "path": str(path)}

    def last_trace(self, _: dict[str, Any]) -> dict[str, Any]:
        """What the recorder heard in the latest recording, one line per action, to read on screen. Already masked."""
        files = sorted((self.store.home / "traces").glob("*.trace.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            raise UserError("Chưa có bản ghi nào. Ghi một lần (Bắt đầu ghi, thao tác, Dừng ghi) rồi quay lại đây.")
        trace = json.loads(files[0].read_text(encoding="utf-8"))
        elements = trace["elements"]
        lines = []
        per_frame: dict[str, int] = {}
        for session in trace["sessions"]:
            lines.append(f"Phiên {session['session_id']}: {len(session['events'])} hành động nghe được.")
            for event in session["events"]:
                element = elements.get(event["el_id"] or "", {})
                frame = element.get("frame", "-")
                per_frame[frame] = per_frame.get(frame, 0) + 1
                name = element.get("label") or (element.get("selectors") or ["-"])[0]
                extra = f" [{event['value_class']}]" if event.get("value_class") else (f" = {event['value']}" if event.get("value") else "")
                key = f" ({event['key_class']})" if event.get("key_class") else ""
                lines.append(f"{event['seq']:>3}  {event['kind']:<9} {frame} › {name}{key}{extra}")
        masking = trace["masking"]
        head = [f"Bỏ hẳn {masking['dropped_count']} hành động ở ô mật khẩu/OTP.",
                "Số hành động theo khung: " + (", ".join(f"{k}: {v}" for k, v in sorted(per_frame.items())) or "không có")]
        reach_file = files[0].with_name(files[0].name.replace(".trace.json", ".reach.txt"))
        reach = reach_file.read_text(encoding="utf-8").splitlines() if reach_file.is_file() else []
        reach_lines = ["", "Bộ ghi đã gắn vào các khung (mỗi dòng là một lần thay đổi; «listen» là cách gắn, «inject_error» là lỗi khi gắn):"]
        for note in reach[-6:]:
            reach_lines += ["  " + part.strip() for part in note.split(" | ")]
        return {"lines": head + lines[:300] + (reach_lines if reach else []), "path": str(files[0])}

    def screen(self, _: dict[str, Any]) -> dict[str, Any]:
        """The screen as data the steps can call: an object (frames, fields, tables of row objects), the key-values, the rows, each with the
        name to call it by. For the teller's eyes and for the flow; in memory only."""
        from rookie_agent.ie import read

        session = self._ie_session
        snaps = session.seen if session is not None else self._last_seen
        if not snaps:
            return {"model": {"frames": {}, "messages": []}, "list": []}
        data = read.model(snaps[-1]["frames"])
        return {"model": data, "list": read.listing(data)}

    def live(self, _: dict[str, Any]) -> dict[str, Any]:
        """The steps the teller has done so far (while recording or previewing), in plain words, for the panel."""
        session = self._ie_session
        if session is None:
            return {"recording": False, "preview": False, "count": 0, "steps": []}
        summary = summarize_events(session.recorder.current())
        hint = ""
        failed = [n for n in session.notes if "tự tắt" in n or "Lỗi bộ ghi" in n or "Lỗi JavaScript" in n or "Đã nhớ trang" in n or " Ghi yêu cầu: " in n or "Chẩn đoán lỗi trang" in n]
        if failed:
            hint = "Bộ ghi báo: " + " | ".join(n[:300] for n in failed[-3:])
        elif not summary["events"] and session.notes:      # nothing yet: say what the recorder reached, so a silent page is not a mystery
            hint = "Bộ ghi báo: " + session.notes[-1][:400]
        return {"recording": True, "preview": bool(getattr(session, "preview", False)), "count": summary["events"], "steps": summary["steps"][-40:], "hint": hint}

    def requests(self, _: dict[str, Any]) -> dict[str, Any]:
        """The requests the page made, with what was sent and what came back, for the teller's own eyes on this PC. In memory only."""
        session = self._ie_session
        found = session.requests if session is not None else self._last_requests
        return {"recording": session is not None, "requests": list(found[-100:])}

    def seen(self, _: dict[str, Any]) -> dict[str, Any]:
        """What the agent saw on the screen after the teller's actions (tables, label-value pairs, messages), full values, for the
        teller's own eyes on this PC. Kept in memory only; it is never written to disk or sent anywhere."""
        session = self._ie_session
        snaps = session.seen if session is not None else self._last_seen
        if not snaps:
            return {"recording": session is not None, "count": 0, "last": None, "history": []}
        last = snaps[-1]
        return {
            "recording": session is not None, "count": len(snaps),
            "last": {k: last[k] for k in ("after", "summary", "region", "frames", "changed")},
            "history": [{"after": s["after"], "summary": s["summary"], "region": s["region"]} for s in snaps[-10:]],
        }

    def calls(self, _: dict[str, Any]) -> dict[str, Any]:
        return {"calls": self._call_log().recent(100)}

    # ---- a file to send back to the developers -----------------------------------------------

    def diagnostics(self, _: dict[str, Any]) -> dict[str, Any]:
        report = self.check({})
        content = {"version": __version__, "bits": self._own_bits, "check": report,
                   "recordings": [{k: r[k] for k in ("steps", "events", "typed_fields", "typed_values_kept")} for r in self.store.listing()]}
        path = self.store.home / "chan-doan.json"
        path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"path": str(path)}

    # ---- Gate 9: the process twin (docs/design.md; plan Gate 9) ----------------------------------------------------------------

    def _role(self) -> str:
        role = self.store.get("role", "maker")
        return role if role in ROLE_NAMES else "maker"

    def _unit_key(self) -> str:
        key = self.store.get("unit_key")
        if not key:
            key = secrets.token_hex(16)        # made once; the unit shares it so that every PC hashes a case id the same way
            self.store.put("unit_key", key)
        return str(key)

    def _case_regex(self) -> str:
        return str(self.store.get("case_regex") or DEFAULT_CASE_REGEX)

    def _case_key(self, texts: list[str]) -> str | None:
        """The first case id found in the texts, as HMAC-SHA256(unit key, id) cut to 32 hex chars. The id itself goes nowhere."""
        try:
            pattern = re.compile(self._case_regex())
        except re.error:
            return None
        for text in texts:
            found = pattern.search(text)
            if found:
                return hmac.new(self._unit_key().encode("utf-8"), found.group(0).encode("utf-8"), hashlib.sha256).hexdigest()[:32]
        return None

    def _process_fields(self, document: dict[str, Any]) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        role = document.get("role") or self.store.get("role")
        if role in ROLE_NAMES:
            extra["role"] = role
        if document.get("case_key"):
            extra["case_key"] = document["case_key"]
        return extra

    @staticmethod
    def _path_template(url: str) -> str:
        """The path of a request as a template: no query, no host, long numbers and ids as {n} and {id} (a case id in a path)."""
        path = urllib.parse.urlsplit(url).path or "/"
        def one(segment: str) -> str:
            if re.search(r"\d", segment) and re.search(r"[A-Za-z]", segment) and len(segment) >= 6:
                return "{id}"
            return "{n}" if re.fullmatch(r"\d{4,}", segment) else segment

        return "/".join(one(part) for part in path.split("/"))[:200]

    def _events_for_server(self, document: dict[str, Any]) -> list[dict[str, Any]]:
        """The events of an ie recording, each with the calls the page made after it: method, path template, status, milliseconds."""
        events = document["events"]
        if document.get("engine") != "ie":
            return events
        calls: dict[int, list[dict[str, Any]]] = {}
        for request in document.get("requests") or []:
            seq, status = request.get("after_seq"), int(request.get("status") or 0)
            if seq is None or status < 100:
                continue
            calls.setdefault(int(seq), []).append({"method": str(request.get("method") or "GET").upper(), "path": self._path_template(str(request.get("url") or "")),
                                                   "status": status, "ms": max(0, int(request.get("ms") or 0))})
        # Every event of the session carries the session's schema_version (3: api_calls with timings are allowed for ie; 4: some events
        # say what the screen showed after them, task 12.1).
        version = 4 if any("shows" in e for e in events) else 3
        return [{**e, "schema_version": version, **({"api_calls": calls[int(e["seq"])][:20]} if int(e.get("seq", -1)) in calls else {})} for e in events]

    def twin_settings(self, _: dict[str, Any]) -> dict[str, Any]:
        return {"role": self._role(), "unit_key": self._unit_key(), "case_regex": self._case_regex(),
                "roles": [{"id": "maker", "label": "Giao dịch viên (GDV)"}, {"id": "checker", "label": "Kiểm soát viên"}]}

    def twin_settings_save(self, body: dict[str, Any]) -> dict[str, Any]:
        if "role" in body:
            if body["role"] not in ROLE_NAMES:
                raise UserError("Vai trò chỉ có thể là Giao dịch viên hoặc Kiểm soát viên.")
            self.store.put("role", body["role"])
        if body.get("unit_key"):
            key = str(body["unit_key"]).strip()
            if len(key) < 16:
                raise UserError("Khoá của đơn vị cần dài ít nhất 16 ký tự.")
            self.store.put("unit_key", key)
        if body.get("case_regex"):
            try:
                re.compile(str(body["case_regex"]))
            except re.error:
                raise UserError("Mẫu nhận mã lệnh không hợp lệ.") from None
            self.store.put("case_regex", str(body["case_regex"]))
        return self.twin_settings({})

    def _twin_call(self, name: str, *args: Any) -> dict[str, Any]:
        client = self._server()
        try:
            return getattr(client, name)(*args)
        except ServerError as error:
            raise UserError(str(error)) from error

    def twin_processes(self, _: dict[str, Any]) -> dict[str, Any]:
        return self._twin_call("twin_processes")

    def twin_process_save(self, body: dict[str, Any]) -> dict[str, Any]:
        if not str(body.get("name") or "").strip() or not body.get("stages"):
            raise UserError("Đặt tên quy trình và chọn ít nhất một chặng.")
        return self._twin_call("twin_save", {k: body[k] for k in ("name", "stages", "handoffs") if k in body})

    def twin_discover(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._twin_call("twin_discover", str(body.get("process_id") or ""))

    def twin_suggest(self, _: dict[str, Any]) -> dict[str, Any]:
        return self._twin_call("twin_suggest")

    def twin_metrics(self, body: dict[str, Any]) -> dict[str, Any]:
        if not body.get("process_id"):
            raise UserError("Chọn quy trình trước.")
        return self._twin_call("twin_metrics", str(body["process_id"]))

    def twin_simulate(self, body: dict[str, Any]) -> dict[str, Any]:
        if not body.get("process_id"):
            raise UserError("Chọn quy trình trước.")
        return self._twin_call("twin_simulate", str(body["process_id"]), {k: v for k, v in body.items() if k != "process_id"})

    def _twin_flow(self, flow_id: str) -> dict[str, Any]:
        flow = next((f for f in self.store.get("flows", []) if (f.get("workflow") or {}).get("id") == flow_id or f.get("title") == flow_id), None)
        if flow is None or not flow.get("workflow"):
            raise UserError("Không thấy luồng đã học cho một chặng của quy trình. Hãy Học lại luồng đó trên máy này.")
        return flow

    def _twin_stages(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        given = body.get("stages")
        if not given and body.get("process_id"):
            process = self._twin_call("twin_process", str(body["process_id"]))
            given = [{"flow_id": s.get("workflow_id"), "role": s.get("role"), "label": s.get("label")} for s in process.get("stages", [])]
        if not given:
            raise UserError("Chọn quy trình hoặc ít nhất một chặng để chạy thử.")
        out = []
        for stage in given:
            flow = self._twin_flow(str(stage.get("flow_id") or stage.get("workflow_id") or ""))
            out.append({"flow": flow, "role": stage.get("role") if stage.get("role") in ROLE_NAMES else "maker", "label": str(stage.get("label") or flow["title"])})
        return out

    def twin_run(self, body: dict[str, Any], stages: list[dict[str, Any]] | None = None,
                 on_done: Callable[[dict[str, Any]], None] | None = None, ref: dict[str, Any] | None = None) -> dict[str, Any]:
        """Chạy thử trên bản sao: the stages in order (maker, queue, checker), answered from the skeletons kept with each flow. Nothing is
        sent to IE or the network. A node that writes or moves money, and a checker's stage, wait for a person's Duyệt."""
        from rookie_agent.ie import replay, twin
        from rookie_agent.webui.run import WebController

        if self._run is not None and self._run["thread"].is_alive():
            raise UserError("Đang chạy một luồng. Đợi xong hoặc bấm Dừng khẩn.")
        if self._ie_session is not None:
            raise UserError("Đang ghi. Bấm Dừng ghi trước khi chạy.")
        stages = stages or self._twin_stages(body)
        plan = []

        def describe(step: dict[str, Any]) -> str:
            return friendly_step(step["action"], (step.get("target") or {}).get("label"))

        for index, stage in enumerate(stages):
            flow, workflow = stage["flow"], stage["flow"]["workflow"]
            api = flow.get("api") or []
            if api and not twin.has_twin(api):
                raise UserError(twin.NO_TWIN)
            raw = api or twin.screen_nodes(workflow, describe)
            prefix = f"c{index + 1}."
            plan.append({"workflow": workflow, "nodes": twin.prefixed(raw, prefix, stage["label"]), "role": stage["role"], "label": stage["label"]})
        inputs = {str(k): str(v) for k, v in (body.get("inputs") or {}).items() if str(v) != ""}
        stop = threading.Event()
        controller = WebController(stop, dict(inputs), lambda: replay.TWIN_BANNER)
        title = str(body.get("name") or " → ".join(p["label"] for p in plan))
        state: dict[str, Any] = {"mode": "twin", "title": title, "controller": controller, "stop": stop, "result": None, "stops_before": None,
                                 "started": time.time(), "via": None, "input_names": sorted(inputs), "twin": True,
                                 "stages": [{"label": p["label"], "role": p["role"], "nodes": [g["id"] for g in replay.groups_of(p["nodes"])]} for p in plan]}
        if ref:
            state["workflow_ref"] = ref      # task 10.7: a version tried before it is taken; the audit names it, not this PC's copy
        send = twin.make_twin_send(inputs, str(body.get("seed") or ""))

        def work() -> None:
            steps: list[dict[str, Any]] = []
            simulated, result = 0, {"status": "finished", "message": "", "steps": []}
            try:
                for index, p in enumerate(plan):
                    if index:
                        queue = f"q{index}"
                        controller.progress(queue, "done", "chuyển sang chặng sau, vào hàng chờ duyệt (mô phỏng)")
                        controller.show(queue, {"action": "Bàn giao / Hàng chờ duyệt", "risk": "read", "requests": [], "inputs": [], "twin": replay.TWIN_BANNER})
                    controller.context = {"twin": True, "banner": replay.TWIN_BANNER, "role": p["role"], "stage": p["label"]}
                    result = replay.run_api(p["workflow"], p["nodes"], inputs, send, controller, stop, twin=True, role=p["role"])
                    steps += result["steps"]
                    simulated += int(result.get("simulated_ms") or 0)
                    if result["status"] != "finished":
                        break
                else:
                    result["message"] = f"Chạy thử xong {len(plan)} chặng trên bản sao. " + replay.TWIN_BANNER + "."
            except Exception as error:  # noqa: BLE001
                result = {"status": "failed", "message": f"Chạy thử bị lỗi: {error}", "steps": steps}
            result = {**result, "steps": steps, "twin": True, "simulated_ms": simulated}
            state["result"] = result
            self._audit(state, result)       # flow names, step ids and states only, mode "twin": no value
            if on_done is not None:
                on_done(result)

        state["thread"] = threading.Thread(target=work, name="twin-run", daemon=True)
        self._run = state
        state["thread"].start()
        return {"started": True, "banner": replay.TWIN_BANNER}

    def twin_export(self, body: dict[str, Any]) -> dict[str, Any]:
        """The process as an n8n-style workflow file (templates only, no header, no value), for the page to offer as a download."""
        from rookie_agent.ie import n8n

        stages = []
        for stage in self._twin_stages(body):
            workflow = stage["flow"]["workflow"]
            from rookie_agent.ie import replay

            nodes = stage["flow"].get("api") or []
            group_of = {c: g for g in replay.groups_of(nodes) for c in g["calls"]}
            api = [{**{k: n[k] for k in ("label", "method", "url", "body", "risk")}, "name": replay.call_name(n),
                    "group": group_of[n["id"]]["id"], "group_label": group_of[n["id"]]["label"]} for n in nodes]
            steps = [{"label": friendly_step(s["action"], (s.get("target") or {}).get("label")), "risk": s.get("risk", "read")} for s in workflow.get("steps", [])]
            stages.append({"label": stage["label"], "role": stage["role"], "api": api, "steps": steps})
        return n8n.export(str(body.get("name") or "Quy trình"), stages)

    ROUTES = {
        "GET /api/state": "state", "GET /api/check": "check", "POST /api/enable-bridge": "enable_bridge",
        "POST /api/switch-bits": "switch_bits", "GET /api/windows": "windows", "POST /api/record/start": "record_start",
        "POST /api/record/stop": "record_stop", "GET /api/recordings": "recordings", "POST /api/recordings/delete": "delete_recording",
        "POST /api/server/check": "server_check", "POST /api/server/start": "server_start",
        "POST /api/server/login": "server_login", "POST /api/server/logout": "server_logout",
        "POST /api/mcp/audit": "mcp_audit", "POST /api/admin/open": "admin_open",
        "GET /api/flows/shared": "flows_shared", "POST /api/flows/import": "flow_import", "POST /api/flows/bind": "flow_bind",
        "GET /api/flows/updates": "flow_updates", "POST /api/flows/update/take": "flow_update_take", "POST /api/flows/update/try": "flow_update_try", "POST /api/learn": "learn",
        "POST /api/diagnostics": "diagnostics", "GET /api/flows": "flows",
        "GET /api/codie": "codie_status", "POST /api/codie/test": "codie_test", "GET /api/calls": "calls", "GET /api/seen": "seen", "GET /api/requests": "requests", "GET /api/live": "live", "GET /api/screen": "screen", "POST /api/ie/inspect": "ie_inspect", "POST /api/flow/approve": "flow_approve", "POST /api/flow/restore": "flow_restore", "POST /api/flow/delete": "flow_delete", "POST /api/teach/start": "teach_start", "POST /api/teach/stop": "teach_stop","POST /api/flow/read-withdraw": "flow_read_withdraw","POST /api/run/start": "run_start", "GET /api/run/status": "run_status", "POST /api/run/decide": "run_decide", "POST /api/run/stop": "run_stop", "POST /api/assistant/plan": "assistant_plan", "POST /api/assistant/answer": "assistant_answer", "POST /api/assistant/run": "assistant_run", "GET /api/assistant/habits": "assistant_habits", "GET /api/library": "library", "POST /api/library/n8n": "library_n8n", "GET /api/trace/last": "last_trace",
        "POST /api/voucher/read": "voucher_read", "POST /api/voucher/confirm": "voucher_confirm", "POST /api/voucher/run": "voucher_run",
        "GET /api/twin/settings": "twin_settings", "POST /api/twin/settings": "twin_settings_save",
        "GET /api/twin/processes": "twin_processes", "POST /api/twin/processes": "twin_process_save",
        "GET /api/twin/discover": "twin_discover", "GET /api/twin/suggest": "twin_suggest", "GET /api/twin/metrics": "twin_metrics",
        "POST /api/twin/simulate": "twin_simulate", "POST /api/twin/run": "twin_run", "GET /api/twin/status": "run_status",
        "POST /api/twin/decide": "run_decide", "POST /api/twin/stop": "run_stop", "POST /api/twin/export": "twin_export",
        "GET /api/server/log": "server_log", "POST /api/cache/clear": "cache_clear", "GET /api/cache": "cache_state", "POST /api/file/open": "file_open",
    }

    def server_log(self, _: dict[str, Any]) -> dict[str, Any]:
        """What this agent sent to the server and got back, newest first; it lives in this process only."""
        from rookie_agent import server_client

        return {"exchanges": server_client.exchanges()}

    # ---- a payment order brought in instead of a sentence (tasks 6.8, 6.9; docs/design.md 6.2) -----------------
    # The picture is read in this process and dropped; the fields stay in memory until the run starts. Nothing of either is written:
    # the audit keeps the names of the fields, their confidence and who confirmed them.

    def voucher_read(self, body: dict[str, Any]) -> dict[str, Any]:
        import base64

        from rookie_agent.voucher import extract
        from rookie_agent.voucher.reader import SampleReader, UnreadableDocument

        try:
            data = base64.b64decode(str(body.get("data") or ""), validate=True)
        except ValueError:
            raise UserError("Không đọc được file ảnh này.") from None
        if not data or len(data) > 10_000_000:
            raise UserError("File ảnh trống hoặc lớn quá 10 MB.")
        try:
            text = (getattr(self, "doc_reader", None) or SampleReader()).read(data)
        except UnreadableDocument as error:
            raise UserError(str(error)) from None
        found = extract.extract(text)
        self._voucher = {"id": uuid.uuid4().hex, "fields": found["fields"], "confirmed": False}
        return {"id": self._voucher["id"], "fields": found["fields"], "ready": found["ready"]}

    def _voucher_open(self, voucher_id: str) -> dict[str, Any]:
        voucher = getattr(self, "_voucher", None)
        if not voucher or voucher["id"] != voucher_id:
            raise UserError("Chứng từ này không còn mở. Đưa ảnh vào lại.")
        return voucher

    def voucher_confirm(self, body: dict[str, Any]) -> dict[str, Any]:
        """The teller checked every field (and corrected some): only then do the fields become the inputs of a flow."""
        from rookie_agent.voucher import extract

        voucher = self._voucher_open(str(body.get("id") or ""))
        typed = {str(f.get("name")): str(f.get("value") or "").strip() for f in body.get("fields") or []}
        fields = [{**f, "value": typed.get(f["name"], f["value"])} for f in voucher["fields"]]
        problems = extract.check_confirmed(fields)
        if problems:
            raise UserError("Chưa xác nhận được: " + "; ".join(problems) + ".")
        import getpass

        corrected = sorted(f["name"] for f, g in zip(voucher["fields"], fields) if f["value"] != g["value"])
        voucher["fields"], voucher["confirmed"] = fields, True
        self._audit_line({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": "voucher", "status": "confirmed", "kind": "uy_nhiem_chi",
                          "fields": [f["name"] for f in fields], "confidence": {f["name"]: f["confidence"] for f in fields},
                          "corrected": corrected, "by": getpass.getuser()})
        return {"confirmed": True, "flows": self._voucher_flows(fields)}

    def _voucher_flows(self, fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The approved IE flows, each input with the field of the voucher that most likely fills it (the teller can change it)."""
        from rookie_agent.voucher.extract import plain

        def guess(name: str, label: str) -> str:
            words = set(plain(name.replace("_", " ") + " " + label).split())
            best, score = "", 0
            for f in fields:
                common = len(words & set(plain(f["name"].replace("_", " ") + " " + f["label"]).split()))
                if f["name"] == name:
                    common += 10
                if common > score:
                    best, score = f["name"], common
            return best

        out = []
        for flow in self.store.get("flows", []):
            workflow = flow.get("workflow") or {}
            if workflow.get("engine") != "ie" or workflow.get("status") != "approved":
                continue
            inputs = [{"name": i["name"], "label": i.get("label") or i["name"], "field": guess(i["name"], i.get("label") or "")} for i in workflow.get("inputs", [])]
            out.append({"title": flow["title"], "inputs": inputs, "matched": sum(1 for i in inputs if i["field"])})
        return sorted(out, key=lambda f: -f["matched"])

    def voucher_run(self, body: dict[str, Any]) -> dict[str, Any]:
        """Run the chosen approved flow with the confirmed fields; the same door as any run (approvals, money waits for a checker)."""
        voucher = self._voucher_open(str(body.get("id") or ""))
        if not voucher["confirmed"]:
            raise UserError("Bạn chưa xác nhận các trường của chứng từ.")
        values = {f["name"]: f["value"] for f in voucher["fields"]}
        mapping = {str(k): str(v) for k, v in (body.get("mapping") or {}).items() if str(v) in values}
        inputs = {name: values[field] for name, field in mapping.items()}
        reply = self.run_start({"title": body.get("title"), "inputs": inputs, "window": body.get("window"), "mode": "run"}, via="voucher")
        self._voucher = None                     # the values now live only in the run, in memory
        return reply

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
