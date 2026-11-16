"""Soi cua so IE/Java: liet ke moi cua so cua trinh duyet va Java, cho biet cau noi Java (JAB) tra loi gi.

Chay (mo IE vao man hinh Java truoc, cho thay du cac o nhap). Dat file nay vao thu muc windows-agent cua goi:
    runtime\\py32\\python.exe windows-agent\\soi-ie.py       (Java 32-bit)   hoac   runtime\\py64\\python.exe ...
Ket qua ghi vao Soi-ie.txt tren man hinh nen. Khong ghi gia tri nao ban da nhap.
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rookie_agent.jab import bridge as jab  # noqa: E402
from rookie_agent.jab.session import JabSession  # noqa: E402

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
OUT = Path(os.environ["USERPROFILE"]) / "Desktop" / "Soi-ie.txt"
lines: list[str] = []


def log(text: str = "") -> None:
    print(text)
    lines.append(text)


def text_of(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def class_of(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def process_of(hwnd: int) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return f"pid {pid.value}"


def pids_by_name() -> dict[int, str]:
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True).stdout
    result = {}
    for row in out.splitlines():
        parts = [p.strip('"') for p in row.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            result[int(parts[1])] = parts[0].strip('"')
    return result


log(f"Python {jab.BITS}-bit. Thoi gian: {time.strftime('%Y-%m-%d %H:%M:%S')}")
try:
    log(f"DLL cau noi: {jab.find_dll()}")
except Exception as error:  # noqa: BLE001
    log(f"Khong thay DLL cau noi: {error}")
names = pids_by_name()
log("Tien trinh lien quan: " + ", ".join(f"{n}({p})" for p, n in sorted(names.items()) if n.lower() in ("iexplore.exe", "msedge.exe", "jp2launcher.exe", "javaw.exe", "java.exe", "ieuser.exe")))
log(f"File .accessibility.properties: {'co' if (Path(os.environ['USERPROFILE']) / '.accessibility.properties').is_file() else 'KHONG CO (chua bat cau noi cho tai khoan nay)'}")
log()

session = JabSession().open()
time.sleep(3)  # let the bridge find the running Java machines


def task(bridge):
    rows = []
    tops: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def top(hwnd, _):
        tops.append(hwnd)
        return True

    user32.EnumWindows(top, 0)
    for root in tops:
        pname = names.get(int(process_of(root).split()[1]), "?")
        if pname.lower() not in ("iexplore.exe", "msedge.exe", "jp2launcher.exe", "javaw.exe", "java.exe", "ieuser.exe") and not bridge.is_java_window(root):
            continue
        rows.append((0, root, pname))
        kids: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def child(hwnd, _):
            kids.append(hwnd)
            return True

        user32.EnumChildWindows(root, child, 0)
        for kid in kids:
            rows.append((1, kid, pname))
    out = []
    for depth, hwnd, pname in rows:
        is_java = bool(bridge.is_java_window(hwnd))
        context = None
        if is_java:
            found = bridge.context_from_hwnd(hwnd)
            context = "co" if found else "KHONG lay duoc"
            if found:
                bridge.release(*found)
        out.append((depth, hwnd, pname, class_of(hwnd), text_of(hwnd)[:50], bool(user32.IsWindowVisible(hwnd)), is_java, context))
    return out


try:
    for depth, hwnd, pname, cls, title, visible, is_java, context in session.call(task):
        if depth == 1 and not is_java and not cls.startswith(("Sun", "Java", "Internet Explorer_Server", "Shell DocObject", "TabWindow", "Frame Tab")):
            continue  # a child that has nothing to do with Java or the browser frame
        mark = "  JAVA" if is_java else ""
        log(f"{'    ' * depth}{pname} hwnd={hwnd} lop={cls} an={'khong' if not visible else 'co'} tieu_de='{title}'{mark}" + (f" context={context}" if context else ""))
finally:
    session.close()

log()
log("Ket luan nhanh: neu khong dong nao co chu JAVA thi cau noi chua thay Java. Thu: (1) Bat cau noi + dong mo lai IE, (2) cung bit voi Java, (3) cung quyen (admin).")
OUT.write_text("﻿" + "\n".join(lines), encoding="utf-8")
print(f"\nDa ghi vao {OUT}. Gui file nay cho nhom phat trien.")
