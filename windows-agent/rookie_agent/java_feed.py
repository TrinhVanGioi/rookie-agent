"""Events from the recording helper that runs inside the Java application (java-agent/).

Java Access Bridge reports nothing when a teller acts with the keyboard (Enter in a field, Space or
Enter on a button, a mnemonic). The helper, loaded into the application's JVM, sees the action
whatever triggered it and appends one JSON line per action to a file in the agent folder. This module
reads those lines and hands them to the Recorder.

Only while recording: `start` creates `recording.flag`, which the helper looks for, and `stop` removes
it. Without the flag the helper does nothing at all. The lines hold the component and the screen,
never a typed character or a value.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from rookie_agent.recorder import Recorder
from rookie_agent.selectors import Element, Step

FLAG_NAME = "recording.flag"
EVENTS_DIR = "java-events"


def agent_home() -> Path:
    """The folder shared with the helper: ROOKIE_AGENT_HOME, else %LOCALAPPDATA%\\RookieAgent."""
    explicit = os.environ.get("ROOKIE_AGENT_HOME", "").strip()
    if explicit:
        return Path(explicit)
    return Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "RookieAgent"


def to_element(record: dict[str, Any]) -> Element | None:
    """The component a line talks about, named the same way the Java Access Bridge recorder names it."""
    try:
        path = tuple(Step(str(role), int(index)) for role, index in record["path"])
        if not path:
            return None
        return Element(str(record["role"]), str(record["name"]), path, str(record["window"]))
    except (KeyError, TypeError, ValueError):
        return None


class JavaFeed:
    def __init__(self, recorder: Recorder, home: Path | None = None, poll_seconds: float = 0.1) -> None:
        self._recorder = recorder
        self._home = home or agent_home()
        self._poll_seconds = poll_seconds
        self._offsets: dict[Path, int] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def flag(self) -> Path:
        return self._home / FLAG_NAME

    @property
    def events_dir(self) -> Path:
        return self._home / EVENTS_DIR

    def start(self, session_id: str) -> None:
        """Tell the helpers to listen, and start reading what they write."""
        self._home.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        # what is already in the files belongs to an earlier recording
        self._offsets = {path: path.stat().st_size for path in self.events_dir.glob("*.jsonl")}
        self._stop.clear()
        self.flag.write_text(session_id, encoding="utf-8")
        self._thread = threading.Thread(target=self._loop, name="java-feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Tell the helpers to stop, then read what is left."""
        try:
            self.flag.unlink()
        except FileNotFoundError:
            pass
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        self.poll()

    def _loop(self) -> None:
        while not self._stop.wait(self._poll_seconds):
            self.poll()

    def poll(self) -> int:
        """Read the new complete lines of every helper's file. Returns how many were handed on."""
        handled = 0
        with self._lock:
            for path in sorted(self.events_dir.glob("*.jsonl")):
                offset = self._offsets.get(path, 0)
                try:
                    with path.open("rb") as handle:
                        handle.seek(offset)
                        data = handle.read()
                except OSError:
                    continue
                end = data.rfind(b"\n")
                if end < 0:
                    continue  # a line is still being written
                self._offsets[path] = offset + end + 1
                for raw in data[: end + 1].splitlines():
                    handled += self._handle(raw)
        return handled

    def _handle(self, raw: bytes) -> int:
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return 0
        if not isinstance(record, dict) or record.get("kind") != "action":
            return 0
        element = to_element(record)
        if element is None:
            return 0
        self._recorder.action(element)
        return 1
