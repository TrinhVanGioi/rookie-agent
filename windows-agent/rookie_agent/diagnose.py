"""Check this PC for what the agent needs, and say in plain words what is wrong and what to do.

Nothing here changes the PC. The checks that touch Windows (running processes, files) are passed in, so
tests can use fakes.
"""

from __future__ import annotations

import csv
import io
import os
import struct
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MACHINE_BITS = {0x014C: 32, 0x8664: 64}
# Programs that load the JVM in their own process or inside the browser.
JVM_MODULE = "jvm.dll"
BROWSER_AND_JAVA = {"iexplore.exe", "msedge.exe", "jp2launcher.exe", "javaw.exe", "java.exe"}


@dataclass(frozen=True)
class JavaInstall:
    home: Path
    name: str
    bits: int
    jabswitch: Path | None

    @property
    def major(self) -> str:
        """`8` for jre1.8.0_91, `6` for jre6, `21` for jdk-21."""
        digits = self.name.lower().removeprefix("jre").removeprefix("jdk").lstrip("-")
        if digits.startswith("1."):
            digits = digits[2:]
        return digits.split(".")[0].split("_")[0]


@dataclass(frozen=True)
class JavaUser:
    pid: int
    name: str
    bits: int | None


def pe_bits(path: Path) -> int | None:
    """32 or 64 for a Windows program or DLL, read from its header (works for any bitness of Python)."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(64)
            if head[:2] != b"MZ":
                return None
            (offset,) = struct.unpack_from("<I", head, 0x3C)
            handle.seek(offset)
            signature = handle.read(6)
        if signature[:4] != b"PE\0\0":
            return None
        return MACHINE_BITS.get(struct.unpack_from("<H", signature, 4)[0])
    except OSError:
        return None


def find_java_installs(roots: list[Path] | None = None) -> list[JavaInstall]:
    if roots is None:
        roots = [Path(os.environ.get(name, "")) / "Java" for name in ("ProgramFiles", "ProgramFiles(x86)") if os.environ.get(name)]
    found: list[JavaInstall] = []
    for root in roots:
        if not root.is_dir():
            continue
        for home in sorted(root.iterdir()):
            for runtime in (home, home / "jre"):
                java = runtime / "bin" / "java.exe"
                if java.is_file():
                    bits = pe_bits(java)
                    if bits:
                        switch = runtime / "bin" / "jabswitch.exe"
                        found.append(JavaInstall(runtime, home.name, bits, switch if switch.is_file() else None))
                    break
    return found


def parse_tasklist(output: str) -> list[tuple[str, int]]:
    """`tasklist /m jvm.dll /fo csv /nh` -> (program, pid). It prints an INFO line when nothing matches."""
    rows = []
    for row in csv.reader(io.StringIO(output)):
        if len(row) >= 2 and row[1].strip().isdigit():
            rows.append((row[0], int(row[1])))
    return rows


def process_bits(pid: int) -> int | None:
    """32 or 64 for a running process; None if it cannot be asked (another user, or not Windows)."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        wow = wintypes.BOOL()
        if not kernel.IsWow64Process(handle, ctypes.byref(wow)):
            return None
        if wow.value:
            return 32
        machine = ctypes.c_uint16()
        native = ctypes.c_uint16()
        try:
            if kernel.IsWow64Process2(handle, ctypes.byref(machine), ctypes.byref(native)) and machine.value == 0:
                return 64 if native.value in (0x8664, 0xAA64) else 32
        except AttributeError:
            pass
        return 64 if struct.calcsize("P") * 8 == 64 or os.environ.get("PROCESSOR_ARCHITECTURE", "").endswith("64") else 32
    finally:
        kernel.CloseHandle(handle)


def run_tasklist() -> str:
    try:
        return subprocess.run(
            ["tasklist", "/m", JVM_MODULE, "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def java_users(tasklist: Callable[[], str] = run_tasklist, bits_of: Callable[[int], int | None] = process_bits) -> list[JavaUser]:
    return [JavaUser(pid, name, bits_of(pid)) for name, pid in parse_tasklist(tasklist())]


def bridge_switched_on(home: Path | None = None) -> bool:
    """`jabswitch -enable` writes this file in the user's folder."""
    base = home or Path(os.environ.get("USERPROFILE") or Path.home())
    try:
        return "AccessBridge" in (base / ".accessibility.properties").read_text(errors="ignore")
    except OSError:
        return False


def wanted_bits(users: list[JavaUser], installs: list[JavaInstall], own_bits: int) -> int:
    """Which Python the agent has to run on: the Java that is open now, else the installed Java 8."""
    likely = [u for u in users if u.name.lower() in BROWSER_AND_JAVA] + [u for u in users if u.name.lower() not in BROWSER_AND_JAVA]
    for user in likely:  # a tool such as an editor may also load Java; the browser and the applet launcher count first
        if user.bits:
            return user.bits
    for install in installs:
        if install.major == "8":
            return install.bits
    return own_bits


def item(level: str, title: str, detail: str = "", action: str | None = None) -> dict[str, Any]:
    return {"level": level, "title": title, "detail": detail, "action": action}


def check(
    own_bits: int,
    dll_path: str | None,
    dll_error: str | None,
    windows: list[str],
    installs: list[JavaInstall],
    users: list[JavaUser],
    switched_on: bool,
) -> dict[str, Any]:
    """The picture of this PC: a list of findings and the Python the agent should run on."""
    items: list[dict[str, Any]] = []
    target = wanted_bits(users, installs, own_bits)

    if not installs:
        items.append(item("warn", "Không thấy Java nào trong thư mục Program Files", "Nếu ứng dụng dùng Java cài ở nơi khác thì bỏ qua dòng này."))
    else:
        text = ", ".join(f"{i.name} ({i.bits}-bit)" for i in installs)
        items.append(item("ok", "Java đã cài trên máy", text))

    if users:
        text = ", ".join(f"{u.name} (pid {u.pid}, {u.bits or '?'}-bit)" for u in users)
        items.append(item("ok", "Có chương trình đang chạy Java", text))
    else:
        items.append(item("warn", "Chưa thấy ứng dụng Java nào đang chạy",
                          "Hãy mở màn hình có applet, chờ đến khi thấy các ô nhập, rồi bấm Kiểm tra lại."))

    if target != own_bits:
        items.append(item("bad", f"Agent đang chạy bản {own_bits}-bit nhưng Java là {target}-bit",
                          f"Hai bên phải cùng {target}-bit. Bấm nút bên dưới để chuyển sang bản {target}-bit.",
                          "switch_bits"))
    else:
        items.append(item("ok", f"Agent và Java cùng {own_bits}-bit"))

    if dll_error:
        items.append(item("bad", "Chưa dùng được Java Access Bridge", dll_error))
    elif not switched_on and not windows:
        items.append(item("warn", "Cầu nối Java chưa được bật cho tài khoản này",
                          "Bấm Bật cầu nối, sau đó đóng hết Edge/IE và mở lại màn hình.", "enable_bridge"))
    else:
        items.append(item("ok", "Cầu nối Java đã bật", dll_path or ""))

    if windows:
        items.append(item("ok", f"Agent thấy {len(windows)} cửa sổ Java", ", ".join(windows)))
    elif users and not dll_error:
        items.append(item("warn", "Java đang chạy nhưng agent chưa thấy cửa sổ nào",
                          "Thường do chưa bật cầu nối hoặc chưa đóng mở lại trình duyệt sau khi bật. Quyền chạy cũng phải giống nhau: "
                          "nếu IE chạy bằng Run as administrator thì agent cũng phải vậy."))

    levels = {entry["level"] for entry in items}
    summary = "bad" if "bad" in levels else "warn" if "warn" in levels else "ok"
    return {"items": items, "summary": summary, "own_bits": own_bits, "wanted_bits": target}


def enable_bridge(installs: list[JavaInstall], bits: int) -> list[str]:
    """Run jabswitch of the Java 8 (or, failing that, any Java) of the wanted bitness. Returns what it did."""
    chosen = [i for i in installs if i.bits == bits and i.jabswitch and i.major == "8"] or [i for i in installs if i.bits == bits and i.jabswitch]
    if not chosen:
        raise RuntimeError(f"Không tìm thấy jabswitch.exe của Java {bits}-bit.")
    done = []
    for install in chosen[:1]:
        result = subprocess.run([str(install.jabswitch), "-enable"], capture_output=True, text=True, timeout=30,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0:
            raise RuntimeError(f"jabswitch báo lỗi: {(result.stdout + result.stderr).strip()}")
        done.append(f"Đã bật cầu nối bằng {install.name} ({install.bits}-bit).")
    return done
