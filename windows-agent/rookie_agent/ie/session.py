"""One recording of an Internet Explorer tab: the bridge is asked for new actions while the teller works."""

from __future__ import annotations

import re
import threading
import time
from typing import Any

from rookie_agent.ie import read
from rookie_agent.ie.bridge import IeBridge, IeBridgeError
from rookie_agent.ie.recorder import IeRecorder


ACTION_KINDS = frozenset({"click", "dblclick", "submit", "input", "select", "key"})
MAX_SEEN = 30
MAX_REQUESTS = 500


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
                self.requests.append({**{k: line.get(k) for k in ("t", "frame", "method", "url", "status", "ms", "req", "res", "hdr", "cut")},
                                      "kind": "xhr", "after": self._last_action})
                del self.requests[:-MAX_REQUESTS]
            elif line.get("kind") == "form":
                self._form = line           # the form the teller sent: the request is known when the next document says where it went
            elif line.get("kind") == "nav" and self._last_action is not None:
                # Gate 8: a document that came after a press is a request of its own (a form posted, a frame loaded). The documents
                # already open when the recording started come before any action and are not requests of the teller's.
                form, self._form = self._form, None
                posted = form if form and int(line.get("t") or 0) - int(form.get("t") or 0) < 15000 else None
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
        return self.recorder.stop()
