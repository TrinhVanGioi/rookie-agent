"""The thread that owns Java Access Bridge.

The bridge needs one thread that starts it, pumps Windows messages and makes
every call. `JabSession` is that thread. Other threads use `call()` to run a
function on it, and attach a `Recorder` to receive what the user does.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, TypeVar

from rookie_agent.jab import bridge as jab
from rookie_agent.recorder import CLICK_ROLES, COMBO_ROLE, TABLE_ROLE, TAB_ROLE, TEXT_ROLES, TOGGLE_ROLES, Recorder
from rookie_agent.selectors import Element, Step, parse_path_selector, parse_role_selector

T = TypeVar("T")
MAX_DEPTH = 64


@dataclass
class Node:
    """A snapshot of one component, for tree dumps and diagnostics."""

    role: str
    name: str
    states: str
    description: str = ""
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    children: list["Node"] = field(default_factory=list)


class JabSession(threading.Thread):
    def __init__(self) -> None:
        super().__init__(name="jab-session", daemon=True)
        self._tasks: queue.Queue[tuple[Callable[[jab.Bridge], Any], Future]] = queue.Queue()
        self._ready = threading.Event()
        self._stop_requested = threading.Event()
        self._startup_error: Exception | None = None
        self._bridge: jab.Bridge | None = None
        self._recorder: Recorder | None = None
        self._lock = threading.Lock()

    # ---- lifecycle ----------------------------------------------------------------

    def open(self, timeout: float = 10.0) -> "JabSession":
        """Start the thread and wait until the bridge is running."""
        self.start()
        if not self._ready.wait(timeout):
            raise jab.BridgeError("Java Access Bridge không khởi động kịp.")
        if self._startup_error is not None:
            raise self._startup_error
        return self

    def close(self) -> None:
        self._stop_requested.set()
        if self.is_alive():
            self.join(timeout=5)

    def run(self) -> None:
        try:
            self._bridge = jab.Bridge()
            self._bridge.start()
            self._register_callbacks(self._bridge)
        except Exception as error:  # reported to the thread that called open()
            self._startup_error = error
            self._ready.set()
            return
        self._ready.set()
        while not self._stop_requested.is_set():
            jab.pump_messages()
            self._run_tasks()
            time.sleep(0.005)

    def _run_tasks(self) -> None:
        while True:
            try:
                task, future = self._tasks.get_nowait()
            except queue.Empty:
                return
            try:
                future.set_result(task(self._bridge))
            except Exception as error:
                future.set_exception(error)

    def call(self, task: Callable[[jab.Bridge], T], timeout: float = 15.0) -> T:
        """Run `task(bridge)` on the bridge thread and return its result."""
        if threading.current_thread() is self:
            return task(self._bridge)
        future: Future = Future()
        self._tasks.put((task, future))
        return future.result(timeout)

    # ---- recording ------------------------------------------------------------------

    def attach(self, recorder: Recorder) -> None:
        with self._lock:
            self._recorder = recorder

    def detach(self) -> Recorder | None:
        with self._lock:
            recorder, self._recorder = self._recorder, None
        return recorder

    def _register_callbacks(self, bridge: jab.Bridge) -> None:
        def guarded(handler):
            """Run a handler only while recording; always release the Java objects."""

            def callback(vm, event, source, *extra):
                try:
                    recorder = self._recorder
                    if recorder is not None:
                        handler(recorder, vm, source, *extra)
                except Exception:
                    pass  # an error in one event must not kill the bridge thread
                finally:
                    bridge.release(vm, event)
                    bridge.release(vm, source)

            return callback

        def on_text(recorder: Recorder, vm: int, source: int) -> None:
            info = bridge.info(vm, source)
            if info is None or info.role_en_US not in TEXT_ROLES:
                return  # password fields stop here: their text is never read
            element = self._element(bridge, vm, source)
            if element is not None:
                focused = "focused" in info.states_en_US.split(",")
                recorder.text_changed(element, bridge.text(vm, source), focused)

        def on_focus_lost(recorder: Recorder, vm: int, source: int) -> None:
            element = self._element(bridge, vm, source)
            if element is not None:
                recorder.focus_lost(element)

        def on_click(recorder: Recorder, vm: int, source: int) -> None:
            element = self._element(bridge, vm, source)
            if element is not None:
                recorder.clicked(element)

        def on_focus_gained(recorder: Recorder, vm: int, source: int) -> None:
            # The first time the bridge sees a button, a press arrives as "focus gained" with the
            # button already pressed; later presses arrive as a state change (below).
            info = bridge.info(vm, source)
            if info is None or info.role_en_US not in CLICK_ROLES:
                return
            if "pressed" in info.states_en_US.split(","):
                element = self._element(bridge, vm, source)
                if element is not None:
                    recorder.clicked(element)

        def on_state(recorder: Recorder, vm: int, source: int, old: str | None, new: str | None) -> None:
            info = bridge.info(vm, source)
            if info is None:
                return
            if info.role_en_US in CLICK_ROLES and new == "pressed":
                element = self._element(bridge, vm, source)
                if element is not None:
                    recorder.clicked(element)
            elif info.role_en_US == TAB_ROLE and new == "selected":
                element = self._element(bridge, vm, source)
                if element is not None:
                    recorder.tab_selected(element)
            elif info.role_en_US in TOGGLE_ROLES and "checked" in (old, new):
                element = self._element(bridge, vm, source)
                if element is not None:
                    recorder.toggled(element)

        def on_selection(recorder: Recorder, vm: int, source: int) -> None:
            info = bridge.info(vm, source)
            if info is None:
                return
            if info.role_en_US == TABLE_ROLE:
                element = self._element(bridge, vm, source)
                rows = bridge.selected_rows(vm, source)
                if element is not None and rows:
                    recorder.row_selected(element, rows[0])
            elif info.role_en_US == "list":
                on_combo_list(recorder, vm, source)

        def on_combo_list(recorder: Recorder, vm: int, source: int) -> None:
            """The option list of a combo box changed: report the combo box it belongs to."""
            owned: list[int] = []
            try:
                current = source
                for _ in range(6):
                    current = bridge.parent(vm, current)
                    if not current:
                        return
                    owned.append(current)
                    info = bridge.info(vm, current)
                    if info is None:
                        return
                    if info.role_en_US == COMBO_ROLE:
                        element = self._element(bridge, vm, current)
                        chosen = bridge.selection(vm, current)
                        owned.extend(chosen)
                        option = bridge.info(vm, chosen[0]) if chosen and chosen[0] else None
                        if element is not None and option is not None:
                            focused = "focused" in info.states_en_US.split(",")
                            recorder.option_selected(element, option.name, focused)
                        return
            finally:
                for java_object in owned:
                    bridge.release(vm, java_object)

        bridge.on("text_change", guarded(on_text))
        bridge.on("focus_lost", guarded(on_focus_lost))
        bridge.on("mouse_clicked", guarded(on_click))  # not delivered by the JREs tried so far; harmless
        bridge.on("focus_gained", guarded(on_focus_gained))
        bridge.on("state_change", guarded(on_state))
        bridge.on("selection_change", guarded(on_selection))

    @staticmethod
    def _element(bridge: jab.Bridge, vm: int, context: int) -> Element | None:
        """Describe a component by its role, name and place in the tree."""
        steps: list[Step] = []
        owned: list[int] = []
        role = name = window = ""
        current = context
        try:
            for depth in range(MAX_DEPTH):
                info = bridge.info(vm, current)
                if info is None:
                    return None
                if depth == 0:
                    role, name = info.role_en_US, info.name
                steps.append(Step(info.role_en_US, info.indexInParent))
                window = info.name
                parent = bridge.parent(vm, current)
                if not parent:
                    break
                owned.append(parent)
                current = parent
        finally:
            for java_object in owned:
                bridge.release(vm, java_object)
        steps.reverse()
        steps[0] = Step(steps[0].role, -1)
        return Element(role, name, tuple(steps), window)

    # ---- windows, tree and actions (used by the CLI, tests and later the runner) -------

    def windows(self) -> list[tuple[int, str]]:
        """Visible Java windows as (handle, title)."""

        def task(bridge: jab.Bridge) -> list[tuple[int, str]]:
            result = []
            for hwnd in jab.java_windows(bridge):
                found = bridge.context_from_hwnd(hwnd)
                if found is None:
                    continue
                vm, root = found
                info = bridge.info(vm, root)
                bridge.release(vm, root)
                name = info.name if info else ""
                # An applet's own name is often empty or generic; the browser's title says which screen it is.
                result.append((hwnd, name or jab.host_title(hwnd)))
            return result

        return self.call(task)

    def wait_for_window(self, title_part: str = "", timeout: float = 20.0) -> tuple[int, str]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for hwnd, title in self.windows():
                if title_part in title:
                    return hwnd, title
            time.sleep(0.2)
        raise jab.BridgeError(
            "Không thấy cửa sổ Java nào. Kiểm tra đã chạy `jabswitch -enable` và mở lại ứng dụng Java chưa."
        )

    def tree(self, hwnd: int, max_nodes: int = 5000) -> Node:
        """Snapshot of the whole component tree of a window."""

        def task(bridge: jab.Bridge) -> Node:
            found = bridge.context_from_hwnd(hwnd)
            if found is None:
                raise jab.BridgeError("Cửa sổ này không phải cửa sổ Java.")
            vm, root = found
            budget = [max_nodes]

            def snapshot(context: int) -> Node:
                info = bridge.info(vm, context)
                if info is None:
                    return Node("?", "", "")
                node = Node(info.role_en_US, info.name, info.states_en_US, info.description, info.x, info.y, info.width, info.height)
                for index in range(info.childrenCount):
                    if budget[0] <= 0:
                        break
                    budget[0] -= 1
                    child = bridge.child(vm, context, index)
                    if child:
                        node.children.append(snapshot(child))
                        bridge.release(vm, child)
                return node

            try:
                return snapshot(root)
            finally:
                bridge.release(vm, root)

        return self.call(task, timeout=60)

    def with_element(self, hwnd: int, selectors: list[str], action: Callable[[jab.Bridge, int, int], T]) -> T:
        """Find the first component matching any selector, in order, and run `action(bridge, vm, context)`."""

        def task(bridge: jab.Bridge) -> T:
            found = bridge.context_from_hwnd(hwnd)
            if found is None:
                raise jab.BridgeError("Cửa sổ này không phải cửa sổ Java.")
            vm, root = found
            owned = [root]
            try:
                for selector in selectors:
                    context = _find(bridge, vm, root, selector, owned)
                    if context:
                        return action(bridge, vm, context)
                raise LookupError(f"Không tìm thấy phần tử: {selectors}")
            finally:
                for java_object in owned:
                    bridge.release(vm, java_object)

        return self.call(task, timeout=60)


def _find(bridge: jab.Bridge, vm: int, root: int, selector: str, owned: list[int]) -> int:
    """Resolve one selector to a component context, or 0. Visited objects go into `owned`."""
    path = parse_path_selector(selector)
    if path is not None:
        current = root
        for step in path[1:]:
            current = bridge.child(vm, current, step.index)
            if not current:
                return 0
            owned.append(current)
            info = bridge.info(vm, current)
            if info is None or info.role_en_US != step.role:
                return 0
        return current

    wanted = parse_role_selector(selector)
    if wanted is None:
        return 0
    matches: list[int] = []

    def search(context: int, depth: int) -> None:
        info = bridge.info(vm, context)
        if info is None or depth > MAX_DEPTH:
            return
        if (info.role_en_US, info.name) == wanted:
            matches.append(context)
        for index in range(info.childrenCount):
            child = bridge.child(vm, context, index)
            if child:
                owned.append(child)
                search(child, depth + 1)

    search(root, 0)
    # An ambiguous name is not a match: the caller falls back to the next selector.
    return matches[0] if len(matches) == 1 else 0
