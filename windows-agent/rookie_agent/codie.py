"""Call Genie Codie (the in-house agent) from the teller's PC, and keep a log of every call.

The way of calling follows what VSDP already does on real machines: `codie --mode M --cwd W --no-color --timeout N -p PROMPT`, no
interaction; the answer is ONE JSON between the lines <<<MV_RESULT and MV_RESULT>>>. A long prompt, or a `.cmd` launcher that cannot be
started straight (cmd.exe would re-read the characters & | < > ^ % "), goes in a file in the workspace and Codie is told to read it.

The log keeps only facts about a call (time, mode, size, seconds, result, a short reason): never the prompt and never the answer,
which can hold a trace. The one call that is shown whole is the connection test, whose prompt holds no data.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OPEN = "<<<MV_RESULT"
CLOSE = "MV_RESULT>>>"
DEFAULT_COMMAND = "codie"
DEFAULT_ARGS = ["--mode", "{mode}", "--cwd", "{workspace}", "--no-color", "--timeout", "{timeout}", "-p", "{prompt}"]
ARG_MAX = 28000
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TASK_LINE = re.compile(r"^\s*\[task\]\s+active\b.*$", re.MULTILINE)
NPM_SHIM_JS = re.compile(r'"%~?dp0%?[\\/]?([^"%]+?\.(?:js|mjs|cjs))"', re.IGNORECASE)
PROVIDER_ERROR = re.compile(r"UPSTREAM_ERROR|Stream failed|\b5\d\d\b.*error|rate.?limit|ECONNREFUSED|ETIMEDOUT", re.IGNORECASE)


class CodieError(RuntimeError):
    """Codie could not be started or did not answer. The message is for the teller, in plain words."""


@dataclass
class CodieRun:
    ok: bool
    exit_code: int
    seconds: float
    result: Any = None      # the JSON between the markers, when there is exactly one
    reason: str = ""        # why not ok, in plain words
    tail: str = ""          # the last lines of the answer, for the connection test only


def find_command(name: str) -> str | None:
    """The full path of the Codie command, or None. On Windows the npm launcher .cmd is preferred over the Unix shim."""
    direct = Path(name)
    if direct.is_absolute() and direct.is_file():
        return str(direct)
    if os.name == "nt" and "." not in direct.name:
        for ext in (".cmd", ".exe", ".bat"):
            found = shutil.which(name + ext)
            if found:
                return found
    return shutil.which(name)


def resolve_launcher(exe: str) -> tuple[list[str], bool]:
    """(argv0, via_cmd). A npm `.cmd` shim is replaced by node + its JS file; when that is not possible `via_cmd` is True."""
    low = exe.lower()
    if not low.endswith((".cmd", ".bat")):
        return [exe], False
    path = Path(exe)
    try:
        match = NPM_SHIM_JS.search(path.read_text(encoding="utf-8", errors="replace"))
        if match:
            script = (path.parent / match.group(1).replace("\\", "/")).resolve()
            node = path.parent / "node.exe"
            node_exe = str(node) if node.is_file() else shutil.which("node")
            if script.is_file() and node_exe:
                return [node_exe, str(script)], False
    except OSError:
        pass
    return [exe], True


def answer_part(text: str) -> str:
    """Codie prints the prompt back before `[task] active`; the prompt holds a sample of the markers, so cut it off."""
    match = TASK_LINE.search(text)
    return text[match.end():] if match else text


def extract_result(text: str) -> tuple[Any, str]:
    """(json, problem). Exactly one marked block must hold valid JSON; the problem says what is wrong otherwise."""
    answer = answer_part(text)
    blocks = re.findall(re.escape(OPEN) + r"(.*?)" + re.escape(CLOSE), answer, re.DOTALL)
    if not blocks:
        return None, "Codie trả lời nhưng không có khối kết quả (thiếu dòng đánh dấu)."
    if len(blocks) > 1:
        return None, "Codie trả nhiều khối kết quả, không biết lấy khối nào."
    try:
        return json.loads(blocks[0].strip()), ""
    except ValueError:
        return None, "Khối kết quả của Codie không phải JSON hợp lệ."


def call(mode: str, prompt: str, timeout_s: int = 600, command: str = DEFAULT_COMMAND, args: list[str] | None = None,
         argv0: list[str] | None = None, keep_tail: bool = False) -> CodieRun:
    """One call. Never raises: a failure is a CodieRun with ok=False and a reason."""
    started = time.monotonic()
    if argv0 is None:
        exe = find_command(command)
        if exe is None:
            return CodieRun(False, 127, 0.0, reason=f"Không tìm thấy lệnh «{command}» trên máy này. Cài Genie Codie CLI hoặc nhập đúng đường dẫn lệnh.")
        argv0, via_cmd = resolve_launcher(exe)
    else:
        via_cmd = False
    workspace = Path(tempfile.mkdtemp(prefix="rookie-codie-"))
    prompt_file = None
    try:
        arg_prompt = prompt
        if via_cmd or len(prompt) > ARG_MAX:
            prompt_file = workspace / f"prompt-{uuid.uuid4().hex[:8]}.md"
            prompt_file.write_text(prompt, encoding="utf-8")
            arg_prompt = (f"Read the file {prompt_file.name} in the current workspace and follow ALL of its instructions exactly, "
                          "including the required output format at the end. Do not modify or delete that file.")
        values = {"mode": mode, "workspace": str(workspace), "prompt": arg_prompt, "timeout": str(max(30, timeout_s - 20))}
        argv = list(argv0)
        for template in (args if args is not None else DEFAULT_ARGS):
            text = template
            for key, value in values.items():
                text = text.replace("{" + key + "}", value)
            argv.append(text)
        env = {**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0", "CI": "1", "PYTHONIOENCODING": "utf-8"}
        try:
            done = subprocess.run(argv, cwd=workspace, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=timeout_s, env=env, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            return CodieRun(False, -1, time.monotonic() - started, reason=f"Codie không trả lời sau {timeout_s} giây.")
        except OSError as error:
            return CodieRun(False, 127, time.monotonic() - started, reason=f"Không chạy được Codie: {error}")
        raw = (done.stdout or "") + (done.stderr or "")
        seconds = time.monotonic() - started
        answer = answer_part(raw)
        tail = answer.strip()[-600:] if keep_tail else ""
        result, problem = extract_result(raw)
        if result is not None:
            return CodieRun(True, done.returncode, seconds, result=result, tail=tail)
        if PROVIDER_ERROR.search(answer):
            reason = "Codie báo lỗi từ mô hình phía sau (tạm thời). Thử lại sau ít phút."
        elif done.returncode != 0:
            reason = f"Codie thoát với mã {done.returncode}."
        else:
            reason = problem
        return CodieRun(False, done.returncode, seconds, reason=reason, tail=tail)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


class CallLog:
    """One JSON line per call in `calls.jsonl`. Facts only; never the prompt or the answer."""

    def __init__(self, home: Path, limit: int = 500) -> None:
        self._path = home / "calls.jsonl"
        self._limit = limit
        self._lock = threading.Lock()

    def add(self, target: str, mode: str, ok: bool, seconds: float, prompt_chars: int = 0, note: str = "") -> dict[str, Any]:
        entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "target": target, "mode": mode, "ok": ok,
                 "seconds": round(seconds, 1), "prompt_chars": prompt_chars, "note": note[:300]}
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def recent(self, count: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            try:
                lines = self._path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return []
        if len(lines) > self._limit:  # keep the file small
            lines = lines[-self._limit:]
            with self._lock:
                self._path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        entries = []
        for line in lines[-count:]:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
        return list(reversed(entries))


TEST_PROMPT = ('This is a connection test from Rookie Agent. There is no data and nothing to do. '
               'Reply with exactly one JSON object between the lines ' + OPEN + ' and ' + CLOSE + ', like this:\n'
               + OPEN + '\n{"pong": true}\n' + CLOSE)
