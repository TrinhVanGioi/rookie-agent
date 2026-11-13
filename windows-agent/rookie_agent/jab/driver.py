"""Drive a Java window through Java Access Bridge for the runner."""

from __future__ import annotations

from rookie_agent.jab import bridge as jab
from rookie_agent.jab.session import JabSession
from rookie_agent.recorder import COMBO_ROLE, TABLE_ROLE, TAB_ROLE
from rookie_agent.runner import ElementNotFound


class DriverError(RuntimeError):
    """The component was found but the action could not be carried out. Never contains a value."""


def _describe(info: jab.AccessibleContextInfo) -> str:
    return f"{info.role_en_US} [{info.name}]"


class JabDriver:
    def __init__(self, session: JabSession, hwnd: int) -> None:
        self._session = session
        self._hwnd = hwnd

    def _with(self, selectors: list[str], action):
        try:
            return self._session.with_element(self._hwnd, selectors, action)
        except LookupError as error:
            raise ElementNotFound(str(error)) from error

    def window_title(self) -> str:
        for hwnd, title in self._session.windows():
            if hwnd == self._hwnd:
                return title
        return ""

    def exists(self, selectors: list[str]) -> bool:
        try:
            self._with(selectors, lambda bridge, vm, context: True)
            return True
        except ElementNotFound:
            return False

    def click(self, selectors: list[str]) -> None:
        def act(bridge: jab.Bridge, vm: int, context: int) -> None:
            info = bridge.info(vm, context)
            if info is None:
                raise DriverError("Không đọc được phần tử.")
            if "enabled" not in info.states_en_US.split(","):
                raise DriverError(f"{_describe(info)} đang bị khoá.")
            if info.role_en_US == TAB_ROLE:
                # A tab has no click action: select it in the tab list that owns it.
                parent = bridge.parent(vm, context)
                if not parent:
                    raise DriverError(f"{_describe(info)} không thuộc danh sách tab nào.")
                try:
                    bridge.select_child(vm, parent, info.indexInParent)
                finally:
                    bridge.release(vm, parent)
                return
            if "click" not in bridge.actions(vm, context) or not bridge.do_action(vm, context, "click"):
                raise DriverError(f"{_describe(info)} không bấm được.")

        self._with(selectors, act)

    def fill(self, selectors: list[str], value: str) -> None:
        def act(bridge: jab.Bridge, vm: int, context: int) -> None:
            info = bridge.info(vm, context)
            if info is None:
                raise DriverError("Không đọc được phần tử.")
            if "editable" not in info.states_en_US.split(","):
                raise DriverError(f"{_describe(info)} không cho nhập.")
            bridge.request_focus(vm, context)
            if not bridge.set_text(vm, context, value):
                raise DriverError(f"{_describe(info)} không điền được.")
            # Password fields echo bullets, so only plain text can be checked.
            if info.role_en_US == "text" and bridge.text(vm, context) != value:
                raise DriverError(f"{_describe(info)} không nhận đúng giá trị đã điền.")

        self._with(selectors, act)

    def select(self, selectors: list[str], value: str) -> None:
        def act(bridge: jab.Bridge, vm: int, context: int) -> None:
            info = bridge.info(vm, context)
            if info is None:
                raise DriverError("Không đọc được phần tử.")
            if info.role_en_US == TABLE_ROLE:
                table = bridge.table_info(vm, context)
                row = int(value) if value.isdigit() else -1
                if table is None or not 0 <= row < table.rowCount:
                    raise DriverError(f"{_describe(info)} không có dòng được chọn lúc ghi.")
                bridge.select_child(vm, context, row * table.columnCount)
            elif info.role_en_US == COMBO_ROLE:
                index = _option_index(bridge, vm, context, value)
                if index < 0:
                    raise DriverError(f"{_describe(info)} không có lựa chọn cần chọn.")
                bridge.request_focus(vm, context)
                bridge.select_child(vm, context, index)
            else:
                raise DriverError(f"{_describe(info)} không phải bảng hay combo box.")

        self._with(selectors, act)

    def read_value(self, selectors: list[str]) -> str:
        def act(bridge: jab.Bridge, vm: int, context: int) -> str:
            info = bridge.info(vm, context)
            if info is None or info.role_en_US == "password text":
                raise DriverError("Không được đọc phần tử này.")
            text = bridge.text(vm, context)
            if text is None:
                raise DriverError(f"{_describe(info)} không có nội dung để đọc.")
            return text

        return self._with(selectors, act)


def _option_index(bridge: jab.Bridge, vm: int, combo: int, wanted: str) -> int:
    """Index of the option named `wanted` in a combo box, or -1."""
    owned: list[int] = []
    try:
        found = _find_list(bridge, vm, combo, owned, depth=0)
        if not found:
            return -1
        info = bridge.info(vm, found)
        for index in range(info.childrenCount if info else 0):
            option = bridge.child(vm, found, index)
            if not option:
                continue
            owned.append(option)
            option_info = bridge.info(vm, option)
            if option_info is not None and option_info.name == wanted:
                return index
        return -1
    finally:
        for java_object in owned:
            bridge.release(vm, java_object)


def _find_list(bridge: jab.Bridge, vm: int, context: int, owned: list[int], depth: int) -> int:
    info = bridge.info(vm, context)
    if info is None or depth > 6:
        return 0
    if info.role_en_US == "list":
        return context
    for index in range(info.childrenCount):
        child = bridge.child(vm, context, index)
        if not child:
            continue
        owned.append(child)
        found = _find_list(bridge, vm, child, owned, depth + 1)
        if found:
            return found
    return 0
