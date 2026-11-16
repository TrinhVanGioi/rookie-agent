"""One recording of an Internet Explorer tab: the bridge is asked for new actions while the teller works."""

from __future__ import annotations

import threading
from typing import Any

from rookie_agent.ie.bridge import IeBridge, IeBridgeError
from rookie_agent.ie.recorder import IeRecorder


class IeSession:
    def __init__(self, bridge: IeBridge, tab_id: int, app_title: str, poll_seconds: float = 0.3) -> None:
        self._bridge = bridge
        self._tab_id = tab_id
        self._poll_seconds = poll_seconds
        self.recorder = IeRecorder(app_title=app_title)
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
        info = self._bridge.start_recording(self._tab_id) or {}
        self.info = info
        self._thread = threading.Thread(target=self._loop, name="ie-feed", daemon=True)
        self._thread.start()
        return info

    def _loop(self) -> None:
        while not self._stop.wait(self._poll_seconds):
            try:
                for line in self._bridge.poll():
                    self.recorder.handle(line)
            except IeBridgeError as error:  # the tab was closed or the bridge stopped: keep what was recorded
                self.error = str(error)
                return

    def stop(self) -> list[dict[str, Any]]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        try:
            for line in self._bridge.stop_recording():
                self.recorder.handle(line)
        except IeBridgeError as error:
            self.error = self.error or str(error)
        return self.recorder.stop()
