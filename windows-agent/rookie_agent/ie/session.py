"""One recording of an Internet Explorer tab: the bridge is asked for new actions while the teller works."""

from __future__ import annotations

import re
import threading
import time
from typing import Any

from rookie_agent.ie import read
from rookie_agent.ie.bridge import IeBridge, IeBridgeError
from rookie_agent.ie.clean import is_address
from rookie_agent.ie.recorder import IeRecorder


ACTION_KINDS = frozenset({"click", "dblclick", "submit", "input", "select", "key"})
MAX_SEEN = 30
MAX_REQUESTS = 500
QUIET_SECONDS = 4.0     # a form sent or a window opened that no new document answered within this time: its answer was a file


def _path_of(url: Any) -> str:
    """A url without scheme, host, query: what tells a window.open from the document it opened."""
    text = re.sub(r"^[A-Za-z][A-Za-z0-9+.\-]*://[^/]*", "", str(url or "")).split("?", 1)[0].split("#", 1)[0]
    return text.rsplit("/", 1)[-1] if text else ""


class IeSession:
    def __init__(self, bridge: IeBridge, tab_id: int, app_title: str, poll_seconds: float = 0.15, settle_seconds: float = 0.6, requests: bool = False, diag: str = "") -> None:
        self._bridge = bridge
        self._diag = diag                      # to find what upsets a page: "noread", "nolisten" or "none" (see Core.record_start); "" is the normal recording
        self._requests = requests              # hook the requests of the page too (off by default: it is what can upset a page)
        self._tab_id = tab_id
        self._poll_seconds = poll_seconds
        self._settle = settle_seconds           # how long the screen must be quiet after an action before it is read
        self._look_at: float | None = None      # when to read the screen next
        self._last_action: dict[str, Any] | None = None
        self._volatile: set[read.Key] = set()   # what changes by itself on the screen (a clock)
        self._hook_stepped_back = False
        self.js_errors: list[dict[str, Any]] = []  # script errors of the page itself (message, file:line): in memory, for the panel
        self.on_hook_failed = None                # called with the host when the recorder took its stand-ins back: the caller remembers the site
        self.requests: list[dict[str, Any]] = []   # the requests the page made, full request and response: in memory only
        self._form: dict[str, Any] | None = None   # the last form the teller sent, until the next document says where it went
        self._form_after: dict[str, Any] | None = None
        self._go_at = -100.0                       # when the page last started to leave after a press
        self._form_at, self._form_go = 0.0, False  # when it was seen, and whether the page then started to leave (an answer that is a download)
        self._opens: list[dict[str, Any]] = []     # window.open calls no document has answered yet
        self.seen: list[dict[str, Any]] = []    # what the screen showed after each action: in memory only, the full values are here
        self.recorder = IeRecorder(app_title=app_title)
        self.app_title = app_title
        self.notes: list[str] = []  # what the recorder reached in each frame, whenever that changed
        self._seen: set[str] = set()
        self.raw: list[dict[str, Any]] = []  # every line the page reported, in memory only; the trace builder masks it before it is written
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: str | None = None
        self.info: dict[str, Any] = {}  # what the bridge said at start: frames reached, frames listening

    @property
    def session_id(self) -> str:
        return self.recorder.session_id

    def start(self) -> dict[str, Any]:
        """Start listening. Returns the bridge's answer (frames reached, frames listening) so the caller can tell the teller
        when the recorder could not be put into the page."""
        info = (self._bridge.start_recording(self._tab_id, requests=self._requests, diag=self._diag) if self._diag
                else self._bridge.start_recording(self._tab_id, requests=self._requests)) or {}
        self.info = info
        self._look_at = time.monotonic() + self._settle
        self._thread = threading.Thread(target=self._loop, name="ie-feed", daemon=True)
        self._thread.start()
        return info

    def _loop(self) -> None:
        while not self._stop.wait(self._poll_seconds):
            try:
                lines = self._bridge.poll()
            except IeBridgeError as error:  # the tab was closed or the bridge stopped: keep what was recorded
                self.error = str(error)
                return
            except Exception as error:  # noqa: BLE001  something unexpected: say so, and keep listening
                self.error = f"Lỗi khi đọc bộ ghi: {error}"
                continue
            if self._take(lines):
                self._look_at = time.monotonic() + self._settle     # an action: look when the screen is quiet
            if self._look_at is not None and time.monotonic() >= self._look_at:
                self._look_at = None
                if self._diag not in ("noread", "none"):     # a diagnosis run does not read the screen
                    self._look()
            note = getattr(self._bridge, "diag", None)
            if note and "recorder_error=" in note:   # the recorder failed inside the page while recording an action: say so in plain words
                found = re.findall(r"recorder_error=([^|]*)", note)
                detail = re.sub(r"\d{6,}", "#", found[-1].strip())[:160]
                self.notes.append(f"{time.strftime('%H:%M:%S')} Lỗi bộ ghi trong trang: thao tác vừa rồi có thể chưa được ghi ({detail}).")
                del self.notes[:-30]
            if note:  # what the recorder could reach changed: keep it for the screen, and in agent.log (host names only, no paths, no values)
                self.notes.append(f"{time.strftime('%H:%M:%S')} {note}")
                del self.notes[:-30]
                try:
                    print(f"[ie-ghi] {time.strftime('%H:%M:%S')} {note}", flush=True)
                except Exception:  # noqa: BLE001  a console that cannot print a character must not end the recording
                    pass

    def _take(self, lines: list[dict[str, Any]]) -> bool:
        """Keep every line. A line the recorder cannot read is skipped; it never ends the recording or hides the lines after it.
        True when one of the lines is an action of the teller (the screen may change after it)."""
        acted = False
        self._flush_quiet()
        for line in lines:
            uid = line.get("uid")
            if uid:  # the same line can arrive twice (taken from the old page and restored by the new one): once is enough
                if uid in self._seen:
                    continue
                self._seen.add(uid)
            self.raw.append(line)
            if line.get("kind") == "ajaxerr":    # the recorder gave the page its own request objects back: say so on the screen, once per frame
                if line.get("stage") == "pageerror":
                    self._hook_stepped_back = True      # it stepped back because of a script error of the page: the next line about that error says so
                if self.on_hook_failed and line.get("host"):
                    try:
                        self.on_hook_failed(str(line["host"]))
                        self.notes.append(f"{time.strftime('%H:%M:%S')} Đã nhớ trang «{str(line['host'])[:60]}»: lần ghi sau sẽ không ghi yêu cầu của trang này.")
                    except Exception:  # noqa: BLE001  remembering the site is a convenience
                        pass
                self.notes.append(f"{time.strftime('%H:%M:%S')} Ghi yêu cầu đã tự tắt trên trang này ({line.get('stage')}: {str(line.get('error'))[:120]}). Trang được để yên.")
                del self.notes[:-30]
            if line.get("kind") == "jserror":    # a script error of the page itself, with its detail, for the panel (IE shows only a yellow icon)
                detail = re.sub(r"\d{6,}", "#", str(line.get("message") or ""))[:200]
                place = f"{str(line.get('file') or '')[:60]}:{int(line.get('line') or 0)}"
                same = next((e for e in self.js_errors if e["message"] == detail and e["at"] == place), None)
                if same is not None:        # the same error again (every screen change may do it): counted, not listed again
                    same["count"] += 1
                    for index, note in enumerate(self.notes):
                        if "Lỗi JavaScript của trang: " + detail in note:
                            self.notes[index] = re.sub(r" \(lặp \d+ lần\)$", "", note) + f" (lặp {same['count']} lần)"
                else:
                    self.js_errors.append({"t": line.get("t"), "frame": line.get("frame"), "message": detail, "at": place, "count": 1})
                    del self.js_errors[:-50]
                    since = int(line.get("since_ms") if isinstance(line.get("since_ms"), (int, float)) else -1)
                    if line.get("hooked") and 0 <= since < 2000:
                        link = " Xảy ra ngay sau một yêu cầu mà bộ ghi đang theo dõi: có thể do bộ ghi."
                    elif self._hook_stepped_back:
                        link = " Bộ ghi yêu cầu đã tự tắt vì chính lỗi này (nó xảy ra ngay sau một yêu cầu): có thể do bộ ghi yêu cầu."
                        self._hook_stepped_back = False
                    elif line.get("hooked"):
                        link = " Bộ ghi yêu cầu đang bật nhưng không có yêu cầu nào ngay trước đó: nhiều khả năng là lỗi của trang."
                    else:
                        link = " Bộ ghi yêu cầu đang tắt: lỗi của trang."
                    after = (self._last_action or {}).get("label") or (self._last_action or {}).get("id") or ""
                    after = f" Ngay sau thao tác «{str(after)[:40]}»." if after else ""
                    self.notes.append(f"{time.strftime('%H:%M:%S')} Lỗi JavaScript của trang: {detail} ({place}).{after}{link}")
                    del self.notes[:-30]
            if line.get("kind") == "ajax":
                # an answer that is a file arrives as its facts only (`file`: type, size, name pattern): the page's recorder never read its bytes
                self.requests.append({**{k: line.get(k) for k in ("t", "frame", "method", "url", "status", "ms", "req", "res", "hdr", "cut", "file")},
                                      "kind": "xhr", "after": self._last_action})
                if line.get("file"):
                    self.requests[-1]["res"] = ""          # whatever the page sent along, no text of a file is kept
                del self.requests[:-MAX_REQUESTS]
            elif line.get("kind") == "form":
                self._form = line           # the form the teller sent: the request is known when the next document says where it went
                self._form_at, self._form_after = time.monotonic(), self._last_action
                self._form_go = self._form_at - self._go_at < 3.0    # the page may have started to leave just before its line was made
                if line.get("by") in ("script", "load"):
                    self._form_go = True       # task 11.2: a form the page's script sent into a frame; that frame already left (or shows the answer)
                self._go_at = -100.0
            elif line.get("kind") == "formgo":
                self._go_at = time.monotonic()
                self._form_go = self._form is not None        # the page started to leave because of it (even when the answer is a download and no document comes)
            elif line.get("kind") == "open":
                self._opens.append({"line": line, "at": time.monotonic(), "after": self._last_action})   # window.open(url): a document, or a file
            if line.get("kind") == "nav":
                self._opens = [o for o in self._opens if _path_of(o["line"].get("url")) != _path_of(line.get("url"))]   # the window showed a page: that is its request
            if line.get("kind") == "nav" and self._last_action is not None:
                # Gate 8: a document that came after a press is a request of its own (a form posted, a frame loaded). The documents
                # already open when the recording started come before any action and are not requests of the teller's.
                form, self._form = self._form, None
                self._form_go = False
                posted = form if form and int(line.get("t") or 0) - int(form.get("t") or 0) < 15000 else None
                if is_address((posted or line).get("url")):      # a frame at `javascript:false;` (a date picker) is no request of the teller's
                    self.requests.append({
                        "t": line.get("t"), "frame": line.get("frame"), "kind": "form" if posted else "page",
                        "method": str((posted or {}).get("method") or "GET").upper(), "url": (posted or line).get("url"),
                        "status": 200, "ms": 0, "req": (posted or {}).get("req") or "", "res": "", "cut": bool((posted or {}).get("cut")),
                        "hdr": "Content-Type:application/x-www-form-urlencoded\n" if posted and str(posted.get("method")).upper() == "POST" else "",
                        "after": self._last_action})
                    del self.requests[:-MAX_REQUESTS]
            if line.get("kind") in ACTION_KINDS:
                acted = True
                self._last_action = {"kind": line.get("kind"), "id": line.get("id") or line.get("name") or "",
                                     "label": line.get("label") or "", "t": line.get("t")}
            try:
                self.recorder.handle(line)
            except Exception as error:  # noqa: BLE001
                self.error = f"Bỏ qua một dòng không đọc được: {error}"
        return acted

    def _flush_quiet(self, force: bool = False) -> None:
        """A form the page left for, or a window.open, that no document answered (QUIET_SECONDS, or the recording ended): the answer was not
        a page, so it is taken as a file (a download shows no document). It is a request whose answer is not known yet (`file.guess`); the run
        decides by what really comes back. A form the page's script stopped (no sign it left) is not a request."""
        now = time.monotonic()
        form = self._form
        if form is not None and self._form_go and (force or now - self._form_at >= QUIET_SECONDS):
            self._form = None
            self._form_go = False
            self._go_at = -100.0
            self._quiet_request(form, "form", self._form_after)
        for item in [o for o in self._opens if force or now - o["at"] >= QUIET_SECONDS]:
            self._opens.remove(item)
            self._quiet_request(item["line"], "open", item["after"])

    def _quiet_request(self, line: dict[str, Any], kind: str, after: dict[str, Any] | None) -> None:
        url = str(line.get("url") or "")
        if not url or url.lower().startswith(("javascript:", "about:", "#")):
            return
        method = str(line.get("method") or "GET").upper()
        self.requests.append({
            "t": line.get("t"), "frame": line.get("frame"), "kind": kind, "method": method, "url": url, "status": 200, "ms": 0,
            "req": str(line.get("req") or ""), "res": "", "cut": bool(line.get("cut")), "target": str(line.get("target") or ""),
            "hdr": "Content-Type:application/x-www-form-urlencoded\n" if method == "POST" else "",
            "file": {"guess": True, "ctype": "", "size": 0, "name": ""}, "after": after})
        del self.requests[:-MAX_REQUESTS]

    def _look(self) -> None:
        """Read the screen three times, a moment apart: what keeps changing (a clock) is never taken for the result of the action.
        What differs from the look before is the region the action changed."""
        reader = getattr(self._bridge, "read", None)
        if reader is None:
            return
        started = int(time.time() * 1000)
        moment = (self._last_action or {}).get("t") or started
        baseline = next((x for x in reversed(self.seen) if x["t0"] <= moment and not x.get("provisional")), None)
        action = self._last_action

        def entry(frames0: list[Any], frames: list[Any], provisional: bool) -> dict[str, Any]:
            # What the action changed is compared with the screen as it was BEFORE the action: a look takes a while, and an action can
            # land while it reads, so the look just before may already show the result.
            changes = read.changed(baseline["frames0"] if baseline else [], frames, self._volatile)
            return {"t": int(time.time() * 1000), "t0": started, "after": action, "frames0": frames0, "frames": frames, "changed": changes,
                    "region": read.region(changes), "summary": read.describe(frames), "provisional": provisional}

        try:
            first = read.parse(reader())
            # The teller sees the first reading at once (marked provisional); the checked one replaces it when the three looks are done.
            self.seen.append(entry(first, first, True))
            time.sleep(min(0.3, self._settle))
            second = read.parse(reader())
            time.sleep(min(0.3, self._settle))
            third = read.parse(reader())
        except IeBridgeError:
            self._drop_provisional(started)
            return          # the page is leaving or the bridge is busy: the next action looks again
        except Exception as error:  # noqa: BLE001
            self._drop_provisional(started)
            self.error = f"Không đọc được màn hình: {error}"
            return
        # A clock keeps changing: it differs in both pairs of looks. The result of an action that landed between two looks differs in
        # one pair only, and is not taken for a clock.
        self._volatile |= read.volatile(first, second) & read.volatile(second, third)
        self._drop_provisional(started)
        self.seen.append(entry(first, third, False))
        del self.seen[:-MAX_SEEN]

    def _drop_provisional(self, started: int) -> None:
        self.seen[:] = [x for x in self.seen if not (x.get("provisional") and x["t0"] == started)]

    def stop(self) -> list[dict[str, Any]]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._look_at is not None:   # an action not yet looked at: the last look, before the bridge stops
            self._look()
            self._look_at = None
        try:
            self._take(self._bridge.stop_recording())
        except IeBridgeError as error:
            self.error = self.error or str(error)
        self._flush_quiet(force=True)
        return self.recorder.stop()
