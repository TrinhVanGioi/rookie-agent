"""ctypes binding for the Java Access Bridge DLL (WindowsAccessBridge-32/-64.dll).

Only the calls the agent needs. The DLL must have the same bitness as this
Python process, and that must match the JRE of the Java application: a 32-bit
JRE (usual for applets in IE mode) needs a 32-bit Python.

All calls must happen on the thread that called `Bridge.start()`, and that
thread must pump Windows messages: the bridge finds JVMs and delivers events
through window messages. `rookie_agent.jab.session` owns that thread.
"""

from __future__ import annotations

import ctypes
import os
import struct
import sys
from ctypes import wintypes
from pathlib import Path

BITS = struct.calcsize("P") * 8
DLL_NAME = f"WindowsAccessBridge-{BITS}.dll"

JOBJECT64 = ctypes.c_int64
MAX_STRING = 1024
SHORT_STRING = 256


class BridgeError(RuntimeError):
    """Java Access Bridge is missing, not enabled, or a call failed."""


class AccessibleContextInfo(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_wchar * MAX_STRING),
        ("description", ctypes.c_wchar * MAX_STRING),
        ("role", ctypes.c_wchar * SHORT_STRING),
        ("role_en_US", ctypes.c_wchar * SHORT_STRING),
        ("states", ctypes.c_wchar * SHORT_STRING),
        ("states_en_US", ctypes.c_wchar * SHORT_STRING),
        ("indexInParent", ctypes.c_int32),
        ("childrenCount", ctypes.c_int32),
        ("x", ctypes.c_int32),
        ("y", ctypes.c_int32),
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("accessibleComponent", wintypes.BOOL),
        ("accessibleAction", wintypes.BOOL),
        ("accessibleSelection", wintypes.BOOL),
        ("accessibleText", wintypes.BOOL),
        ("accessibleInterfaces", wintypes.BOOL),
    ]


class AccessibleTextInfo(ctypes.Structure):
    _fields_ = [
        ("charCount", ctypes.c_int32),
        ("caretIndex", ctypes.c_int32),
        ("indexAtPoint", ctypes.c_int32),
    ]


class AccessibleActionInfo(ctypes.Structure):
    _fields_ = [("name", ctypes.c_wchar * SHORT_STRING)]


class AccessibleActions(ctypes.Structure):
    _fields_ = [("actionsCount", ctypes.c_int32), ("actionInfo", AccessibleActionInfo * 256)]


class AccessibleActionsToDo(ctypes.Structure):
    _fields_ = [("actionsCount", ctypes.c_int32), ("actions", AccessibleActionInfo * 32)]


class AccessibleTableInfo(ctypes.Structure):
    _fields_ = [
        ("caption", JOBJECT64),
        ("summary", JOBJECT64),
        ("rowCount", ctypes.c_int32),
        ("columnCount", ctypes.c_int32),
        ("accessibleContext", JOBJECT64),
        ("accessibleTable", JOBJECT64),
    ]


class AccessibleTableCellInfo(ctypes.Structure):
    _fields_ = [
        ("accessibleContext", JOBJECT64),
        ("index", ctypes.c_int32),
        ("row", ctypes.c_int32),
        ("column", ctypes.c_int32),
        ("rowExtent", ctypes.c_int32),
        ("columnExtent", ctypes.c_int32),
        ("isSelected", ctypes.c_bool),
    ]


# void callback(long vmID, JOBJECT64 event, JOBJECT64 source)
EventCallback = ctypes.CFUNCTYPE(None, ctypes.c_long, JOBJECT64, JOBJECT64)
# void callback(long vmID, JOBJECT64 event, JOBJECT64 source, wchar_t *old, wchar_t *new)
PropertyCallback = ctypes.CFUNCTYPE(None, ctypes.c_long, JOBJECT64, JOBJECT64, ctypes.c_wchar_p, ctypes.c_wchar_p)

# name of the event -> (setter exported by the DLL, callback type)
EVENT_SETTERS = {
    "focus_gained": ("setFocusGainedFP", EventCallback),
    "focus_lost": ("setFocusLostFP", EventCallback),
    "mouse_clicked": ("setMouseClickedFP", EventCallback),
    "caret_update": ("setCaretUpdateFP", EventCallback),
    "state_change": ("setPropertyStateChangeFP", PropertyCallback),
    "text_change": ("setPropertyTextChangeFP", EventCallback),
    "selection_change": ("setPropertySelectionChangeFP", EventCallback),
    "value_change": ("setPropertyValueChangeFP", PropertyCallback),
}


def find_dll() -> Path:
    """Locate the bridge DLL: ROOKIE_JAB_DLL, then JAVA_HOME, then PATH, then System32."""
    candidates: list[Path] = []
    explicit = os.environ.get("ROOKIE_JAB_DLL")
    if explicit:
        candidates.append(Path(explicit))
    for variable in ("JAVA_HOME", "JRE_HOME"):
        home = os.environ.get(variable)
        if home:
            candidates += [Path(home) / "bin" / DLL_NAME, Path(home) / "jre" / "bin" / DLL_NAME]
    candidates += [Path(folder) / DLL_NAME for folder in os.environ.get("PATH", "").split(os.pathsep) if folder]
    candidates.append(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / DLL_NAME)
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        java_root = Path(os.environ.get(variable, "")) / "Java"
        if java_root.is_dir():
            for home in sorted(java_root.iterdir(), reverse=True):
                candidates += [home / "bin" / DLL_NAME, home / "jre" / "bin" / DLL_NAME]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise BridgeError(
        f"Không tìm thấy {DLL_NAME}. Đặt biến ROOKIE_JAB_DLL trỏ tới file này "
        f"(nằm trong thư mục bin của JRE/JDK {BITS}-bit)."
    )


class Bridge:
    """Thin, typed wrapper over the DLL. One instance per process."""

    def __init__(self, dll_path: Path | None = None) -> None:
        if sys.platform != "win32":
            raise BridgeError("Java Access Bridge chỉ chạy trên Windows.")
        self.dll_path = dll_path or find_dll()
        try:
            self._dll = ctypes.CDLL(str(self.dll_path))
        except OSError as error:
            raise BridgeError(f"Không nạp được {self.dll_path}: {error}") from error
        self._callbacks: list[object] = []  # keep ctypes callbacks alive
        self._declare()

    def _declare(self) -> None:
        d = self._dll
        vm, obj, jint = ctypes.c_long, JOBJECT64, ctypes.c_int32
        signatures = {
            "Windows_run": ([], None),
            "isJavaWindow": ([wintypes.HWND], wintypes.BOOL),
            "getAccessibleContextFromHWND": (
                [wintypes.HWND, ctypes.POINTER(vm), ctypes.POINTER(obj)], wintypes.BOOL),
            "getAccessibleContextInfo": ([vm, obj, ctypes.POINTER(AccessibleContextInfo)], wintypes.BOOL),
            "getAccessibleChildFromContext": ([vm, obj, jint], obj),
            "getAccessibleParentFromContext": ([vm, obj], obj),
            "releaseJavaObject": ([vm, obj], None),
            "isSameObject": ([vm, obj, obj], wintypes.BOOL),
            "getAccessibleContextWithFocus": (
                [wintypes.HWND, ctypes.POINTER(vm), ctypes.POINTER(obj)], wintypes.BOOL),
            "getAccessibleTextInfo": ([vm, obj, ctypes.POINTER(AccessibleTextInfo), jint, jint], wintypes.BOOL),
            "getAccessibleTextRange": ([vm, obj, jint, jint, ctypes.c_wchar_p, ctypes.c_short], wintypes.BOOL),
            "setTextContents": ([vm, obj, ctypes.c_wchar_p], wintypes.BOOL),
            "getAccessibleActions": ([vm, obj, ctypes.POINTER(AccessibleActions)], wintypes.BOOL),
            "doAccessibleActions": (
                [vm, obj, ctypes.POINTER(AccessibleActionsToDo), ctypes.POINTER(jint)], wintypes.BOOL),
            "requestFocus": ([vm, obj], wintypes.BOOL),
            "getAccessibleSelectionCountFromContext": ([vm, obj], ctypes.c_int),
            "getAccessibleSelectionFromContext": ([vm, obj, ctypes.c_int], obj),
            "addAccessibleSelectionFromContext": ([vm, obj, ctypes.c_int], None),
            "clearAccessibleSelectionFromContext": ([vm, obj], None),
            "getAccessibleTableInfo": ([vm, obj, ctypes.POINTER(AccessibleTableInfo)], wintypes.BOOL),
            "getAccessibleTableCellInfo": (
                [vm, obj, jint, jint, ctypes.POINTER(AccessibleTableCellInfo)], wintypes.BOOL),
            "getAccessibleTableRowSelectionCount": ([vm, obj], jint),
            "getAccessibleTableRowSelections": ([vm, obj, jint, ctypes.POINTER(jint)], wintypes.BOOL),
        }
        for name, (argtypes, restype) in signatures.items():
            function = getattr(d, name)
            function.argtypes = argtypes
            function.restype = restype

    def start(self) -> None:
        """Start the bridge. The calling thread must pump messages afterwards."""
        self._dll.Windows_run()

    # ---- events -------------------------------------------------------------

    def on(self, event: str, handler) -> None:
        """Register `handler` for an event in EVENT_SETTERS. Handlers get raw arguments."""
        setter_name, callback_type = EVENT_SETTERS[event]
        callback = callback_type(handler)
        self._callbacks.append(callback)
        setter = getattr(self._dll, setter_name)
        setter.argtypes = [callback_type]
        setter.restype = None
        setter(callback)

    # ---- windows and tree -----------------------------------------------------

    def is_java_window(self, hwnd: int) -> bool:
        return bool(self._dll.isJavaWindow(hwnd))

    def context_from_hwnd(self, hwnd: int) -> tuple[int, int] | None:
        vm, context = ctypes.c_long(), JOBJECT64()
        if not self._dll.getAccessibleContextFromHWND(hwnd, ctypes.byref(vm), ctypes.byref(context)):
            return None
        return vm.value, context.value

    def info(self, vm: int, context: int) -> AccessibleContextInfo | None:
        info = AccessibleContextInfo()
        if not self._dll.getAccessibleContextInfo(vm, context, ctypes.byref(info)):
            return None
        return info

    def child(self, vm: int, context: int, index: int) -> int:
        return self._dll.getAccessibleChildFromContext(vm, context, index)

    def parent(self, vm: int, context: int) -> int:
        return self._dll.getAccessibleParentFromContext(vm, context)

    def release(self, vm: int, java_object: int) -> None:
        if java_object:
            self._dll.releaseJavaObject(vm, java_object)

    def same(self, vm: int, first: int, second: int) -> bool:
        return bool(self._dll.isSameObject(vm, first, second))

    # ---- text -----------------------------------------------------------------

    def text(self, vm: int, context: int, limit: int = 4096) -> str | None:
        """Full text of a text component, or None when it has no text interface."""
        info = AccessibleTextInfo()
        if not self._dll.getAccessibleTextInfo(vm, context, ctypes.byref(info), 0, 0):
            return None
        count = min(info.charCount, limit)
        if count <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(count + 1)
        if not self._dll.getAccessibleTextRange(vm, context, 0, count - 1, buffer, count + 1):
            return None
        return buffer.value

    def set_text(self, vm: int, context: int, value: str) -> bool:
        return bool(self._dll.setTextContents(vm, context, value))

    # ---- actions --------------------------------------------------------------

    def actions(self, vm: int, context: int) -> list[str]:
        actions = AccessibleActions()
        if not self._dll.getAccessibleActions(vm, context, ctypes.byref(actions)):
            return []
        return [actions.actionInfo[i].name for i in range(actions.actionsCount)]

    def do_action(self, vm: int, context: int, name: str) -> bool:
        todo = AccessibleActionsToDo()
        todo.actionsCount = 1
        todo.actions[0].name = name
        failure = ctypes.c_int32(-1)
        return bool(self._dll.doAccessibleActions(vm, context, ctypes.byref(todo), ctypes.byref(failure)))

    def request_focus(self, vm: int, context: int) -> bool:
        return bool(self._dll.requestFocus(vm, context))

    # ---- selection and tables ---------------------------------------------------

    def selection(self, vm: int, context: int) -> list[int]:
        """Selected children of a list, tab list or combo box. Caller releases them."""
        count = self._dll.getAccessibleSelectionCountFromContext(vm, context)
        return [self._dll.getAccessibleSelectionFromContext(vm, context, i) for i in range(max(count, 0))]

    def select_child(self, vm: int, context: int, index: int) -> None:
        self._dll.clearAccessibleSelectionFromContext(vm, context)
        self._dll.addAccessibleSelectionFromContext(vm, context, index)

    def table_info(self, vm: int, context: int) -> AccessibleTableInfo | None:
        info = AccessibleTableInfo()
        if not self._dll.getAccessibleTableInfo(vm, context, ctypes.byref(info)):
            return None
        return info

    def selected_rows(self, vm: int, context: int) -> list[int]:
        """Indexes of the selected rows of a table component."""
        info = self.table_info(vm, context)
        if info is None:
            return []
        count = self._dll.getAccessibleTableRowSelectionCount(vm, info.accessibleTable)
        if count <= 0:
            return []
        rows = (ctypes.c_int32 * count)()
        if not self._dll.getAccessibleTableRowSelections(vm, info.accessibleTable, count, rows):
            return []
        return list(rows)

    def table_cell(self, vm: int, table: int, row: int, column: int) -> AccessibleTableCellInfo | None:
        info = AccessibleTableCellInfo()
        if not self._dll.getAccessibleTableCellInfo(vm, table, row, column, ctypes.byref(info)):
            return None
        return info


def java_windows(bridge: Bridge) -> list[int]:
    """Handles of the visible windows that belong to a Java application.

    A Swing application is a top-level window. An applet in Internet Explorer (or the IE mode of Edge) is a
    child window inside the browser's window, so the children of every top-level window are searched too.
    A Java window inside another Java window is not listed twice.
    """
    user32 = ctypes.windll.user32
    found: list[int] = []
    top_level: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit_top(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            top_level.append(hwnd)
        return True

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit_child(hwnd, _):
        if user32.IsWindowVisible(hwnd) and bridge.is_java_window(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(visit_top, 0)
    for hwnd in top_level:
        if bridge.is_java_window(hwnd):
            found.append(hwnd)
        else:
            user32.EnumChildWindows(hwnd, visit_child, 0)
    return list(dict.fromkeys(found))


def host_title(hwnd: int) -> str:
    """The text of the top-level window that holds `hwnd` (for an applet: the browser's title)."""
    user32 = ctypes.windll.user32
    root = user32.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT
    length = user32.GetWindowTextLengthW(root)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(root, buffer, length + 1)
    return buffer.value


def pump_messages() -> None:
    """Dispatch every pending window message of the current thread."""
    user32 = ctypes.windll.user32
    message = wintypes.MSG()
    while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):  # PM_REMOVE
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))
