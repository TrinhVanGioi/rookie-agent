"""Call Genie Codie (the in-house agent) from the server on the teller's PC, one call at a time, with no interaction.

The way of calling follows what VSDP already does on real machines: `codie --mode M --cwd W --no-color --timeout N -p PROMPT`; the answer
is ONE JSON between the lines <<<MV_RESULT and MV_RESULT>>>. Codie reads the files in the working directory `W`: the masked trace, and
the design of the first stage; the prompt only says which. A failure never raises past `call`: it comes back as `ok=False` with the
reason in plain words, and `transient` when trying again may help.

Environment:
    ROOKIE_CODIE_ENABLED   0 to turn the model off (the rule-based learner is used); default on when the command exists
    ROOKIE_CODIE_COMMAND   the command (default `codie`)
    ROOKIE_CODIE_MODE_DESIGN, ROOKIE_CODIE_MODE_WORKFLOW   the two custom modes (default rookie-design, rookie-workflow)
    ROOKIE_CODIE_TIMEOUT   seconds per call (default 600)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OPEN = "<<<MV_RESULT"
CLOSE = "MV_RESULT>>>"
DEFAULT_ARGS = ["--mode", "{mode}", "--cwd", "{workspace}", "--no-color", "--timeout", "{timeout}", "-p", "{prompt}"]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TASK_LINE = re.compile(r"^\s*\[task\]\s+active\b.*$", re.MULTILINE)
NPM_SHIM_JS = re.compile(r'"%~?dp0%?[\\/]?([^"%]+?\.(?:js|mjs|cjs))"', re.IGNORECASE)
PROVIDER_ERROR = re.compile(r"UPSTREAM_ERROR|Stream failed|\b5\d\d\b.*error|rate.?limit|ECONNREFUSED|ETIMEDOUT", re.IGNORECASE)


@dataclass
class Settings:
    command: str = "codie"
    mode_design: str = "rookie-design"
    mode_workflow: str = "rookie-workflow"
    timeout: int = 600
    enabled: bool = True
    argv0: list[str] | None = None     # tests: a fake Codie (a Python script) instead of the real command

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        return cls(
            command=env.get("ROOKIE_CODIE_COMMAND", "codie").strip() or "codie",
            mode_design=env.get("ROOKIE_CODIE_MODE_DESIGN", "rookie-design").strip(),
            mode_workflow=env.get("ROOKIE_CODIE_MODE_WORKFLOW", "rookie-workflow").strip(),
            timeout=int(env.get("ROOKIE_CODIE_TIMEOUT", "600") or 600),
            enabled=env.get("ROOKIE_CODIE_ENABLED", "1").strip() != "0",
        )


@dataclass
class Outcome:
    ok: bool
    result: Any = None
    reason: str = ""
    transient: bool = False
    seconds: float = 0.0
    prompt_chars: int = 0


@dataclass
class CallRecord:
    mode: str
    ok: bool
    seconds: float
    prompt_chars: int
    note: str
    extra: dict[str, Any] = field(default_factory=dict)


def find_command(name: str) -> str | None:
    direct = Path(name)
    if direct.is_absolute() and direct.is_file():
        return str(direct)
    if os.name == "nt" and "." not in direct.name:
        for ext in (".cmd", ".exe", ".bat"):
            found = shutil.which(name + ext)
            if found:
                return found
    return shutil.which(name)


def available(settings: Settings) -> bool:
    return settings.enabled and (settings.argv0 is not None or find_command(settings.command) is not None)


def _launcher(exe: str) -> tuple[list[str], bool]:
    if not exe.lower().endswith((".cmd", ".bat")):
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


def _answer_part(text: str) -> str:
    match = TASK_LINE.search(text)
    return text[match.end():] if match else text


def extract(text: str) -> tuple[Any, str]:
    blocks = re.findall(re.escape(OPEN) + r"(.*?)" + re.escape(CLOSE), _answer_part(text), re.DOTALL)
    if not blocks:
        return None, "Codie trả lời nhưng không có khối kết quả (thiếu dòng đánh dấu)."
    if len(blocks) > 1:
        return None, "Codie trả nhiều khối kết quả, không biết lấy khối nào."
    try:
        return json.loads(blocks[0].strip()), ""
    except ValueError:
        return None, "Khối kết quả của Codie không phải JSON hợp lệ."


def call(settings: Settings, mode: str, prompt: str, workspace: Path) -> Outcome:
    """One call. `workspace` holds the files Codie reads. Never raises."""
    started = time.monotonic()
    if settings.argv0 is not None:
        argv0, via_cmd = list(settings.argv0), False
    else:
        exe = find_command(settings.command)
        if exe is None:
            return Outcome(False, reason=f"Không tìm thấy lệnh «{settings.command}» trên máy này.", transient=False)
        argv0, via_cmd = _launcher(exe)
    arg_prompt = prompt
    if via_cmd or len(prompt) > 28000:
        file = workspace / "prompt.md"
        file.write_text(prompt, encoding="utf-8")
        arg_prompt = "Read the file prompt.md in the current workspace and follow ALL of its instructions exactly, including the required output format at the end."
    values = {"mode": mode, "workspace": str(workspace), "prompt": arg_prompt, "timeout": str(max(30, settings.timeout - 20))}
    argv = list(argv0)
    for template in DEFAULT_ARGS:
        text = template
        for key, value in values.items():
            text = text.replace("{" + key + "}", value)
        argv.append(text)
    env = {**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0", "CI": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        done = subprocess.run(argv, cwd=workspace, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=settings.timeout, env=env, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return Outcome(False, reason=f"Codie không trả lời sau {settings.timeout} giây.", transient=True, seconds=time.monotonic() - started, prompt_chars=len(prompt))
    except OSError as error:
        return Outcome(False, reason=f"Không chạy được Codie: {error}", seconds=time.monotonic() - started, prompt_chars=len(prompt))
    raw = (done.stdout or "") + (done.stderr or "")
    seconds = time.monotonic() - started
    result, problem = extract(raw)
    if result is not None:
        return Outcome(True, result=result, seconds=seconds, prompt_chars=len(prompt))
    if PROVIDER_ERROR.search(_answer_part(raw)):
        return Outcome(False, reason="Codie báo lỗi từ mô hình phía sau (tạm thời).", transient=True, seconds=seconds, prompt_chars=len(prompt))
    reason = f"Codie thoát với mã {done.returncode}." if done.returncode != 0 else problem
    return Outcome(False, reason=reason, transient=False, seconds=seconds, prompt_chars=len(prompt))
