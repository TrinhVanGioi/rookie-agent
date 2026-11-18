"""The driver of the runner for a page in Internet Explorer (tasks 4.39 and 4.40).

It plugs into the same loop as the Java driver (`runner.run_workflow`): that loop enforces the risk rules, the approvals, the stop and
the questions. This module only turns the answers of the bridge into what the loop understands, and checks that what was typed or
chosen is really in the page. It never guesses: a missing element is `ElementNotFound`; anything else it must not decide
(two elements alike, a locked field, an entry that is not in the list, a value the page did not keep) is `NeedsHelp`, and the run stops
to ask the teller. Messages say what is wrong, never the value that was typed.
"""

from __future__ import annotations

import re
from typing import Any

from rookie_agent.ie.bridge import IeBridge
from rookie_agent.runner import MOCK_WINDOW_MARKERS, ElementNotFound, NeedsHelp

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})   # the mock sites run here; a bank host is never one of them

PLAIN_WORDS = {
    "ambiguous": "Có nhiều phần tử giống nhau trên màn hình; agent không đoán nên chọn cái nào.",
    "low_confidence": "Màn hình có vẻ đã đổi: agent chưa chắc đây là đúng ô hoặc nút đã học, nên dừng lại hỏi bạn.",
    "disabled": "Ô hoặc nút đang bị khoá. Agent không mở khoá.",
    "readonly": "Ô chỉ cho đọc, không nhập được.",
    "secret": "Đây là ô mật khẩu: bạn tự nhập, agent không bao giờ gõ vào ô này.",
    "no_option": "Giá trị cần chọn không có trong danh sách của ô này.",
    "not_select": "Phần tử này không phải ô chọn.",
    "no_form": "Ô này không nằm trong biểu mẫu nên không gửi được bằng Enter.",
}


def _squash(text: str) -> str:
    return re.sub(r"[\s.,]", "", text or "")


def any_frame(selectors: list[str]) -> list[str]:
    """The same selectors for every frame (`frame=*|...`): used only when the frame of the recording does not have the element."""
    out: list[str] = []
    for selector in selectors:
        if selector.startswith("frame=") and "|" in selector and "|src=" not in selector:
            wild = "frame=*|" + selector.split("|", 1)[1]
            if wild not in out:
                out.append(wild)
    return out


class IeDriver:
    def __init__(self, bridge: IeBridge, tab_id: int) -> None:
        self._bridge = bridge
        self._tab = tab_id
        bridge.bind(tab_id)

    # ---- who we are talking to -----------------------------------------------------
    # (any_frame below: the same selectors asked of every frame)

    def window_title(self) -> str:
        """The title of the page; a page on this PC (the mock sites) is marked as a mock so a `money` step may run on it."""
        for tab in self._bridge.tabs():
            if tab["id"] == self._tab:
                local = str(tab.get("host") or "").lower() in LOCAL_HOSTS
                return (MOCK_WINDOW_MARKERS[0] + " - " if local else "") + str(tab.get("title") or "")
        return ""

    # ---- what the runner asks -------------------------------------------------------

    def _target(self, selectors: list[str], want: str, risk: str) -> list[str]:
        """Task 6.1: every selector is looked up and weighed (`locate.choose`); the action goes to that one element only. The step's
        risk is not known here: an action is weighed as `write` (the stricter threshold), a read as `read`."""
        if not hasattr(self._bridge, "locate") or (len(selectors) == 1 and "|src=" in selectors[0]):
            return selectors      # (an element the teller has just pointed at: acted on as it is)
        from rookie_agent.ie import locate

        frame, _ = locate.group_selectors(selectors)
        mine = [f for f in self._bridge.locate(selectors) if f.get("frame") == frame]
        if len(mine) > 1:
            raise NeedsHelp("ambiguous", PLAIN_WORDS["ambiguous"])
        if mine:
            result = self._weigh(mine[0], want, risk)
            if result.state != "not_found":
                return self._chosen(frame, result)
        # The frame of the recording is not there, or the element is not in it: TouchPoint may name or order its frames differently
        # from one sign-in to the next. The same selectors are asked of every frame; exactly one frame with one element, or nothing.
        anywhere = [(str(f.get("frame")), self._weigh(f, want, risk)) for f in self._bridge.locate(any_frame(selectors)) if f.get("frame") != frame]
        hits = [(name, result) for name, result in anywhere if result.state != "not_found"]
        if not hits:
            raise ElementNotFound()
        if len(hits) > 1:
            raise NeedsHelp("ambiguous", PLAIN_WORDS["ambiguous"] + " (ở nhiều khung của trang)")
        return self._chosen(*hits[0])

    @staticmethod
    def _weigh(found: dict[str, Any], want: str, risk: str) -> Any:
        from rookie_agent.ie import locate

        elements = {int(n): {"field": bool(f), "press": True} for n, f in (found.get("fields") or {}).items()}
        # A label also names the row and the cell around its field: for typing or choosing only the fields themselves count.
        keep = (lambda n: elements.get(n, {}).get("field")) if want == "field" else (lambda n: True)
        probes = [locate.Probe(str(p.get("kind")), [int(n) for n in p.get("m") or [] if keep(int(n))]) for p in found.get("probes") or []]
        return locate.choose(probes, elements, want, risk)

    @staticmethod
    def _chosen(frame: str, result: Any) -> list[str]:
        if result.state == "ambiguous":
            raise NeedsHelp("ambiguous", PLAIN_WORDS["ambiguous"])
        if result.state == "low_confidence":
            raise NeedsHelp("low_confidence", PLAIN_WORDS["low_confidence"] + f" (độ tin cậy {result.score:.2f})")
        return [f"frame={frame}|src={result.uid}"]

    def _act(self, op: str, selectors: list[str], value: str = "") -> dict[str, Any]:
        want = "field" if op in ("fill", "select", "submit") else "press" if op == "click" else "any"
        selectors = self._target(selectors, want, "read" if op in ("read", "exists") else "write")
        answer = self._bridge.act(op, selectors, value)
        if answer.get("ok"):
            return answer
        error = str(answer.get("error") or "no_answer")
        if error == "not_found":
            raise ElementNotFound()
        if error == "no_option":
            options = ", ".join(str(o) for o in answer.get("options") or [])[:300]
            raise NeedsHelp("no_option", PLAIN_WORDS["no_option"] + (f" Danh sách có: {options}." if options else ""))
        if error in PLAIN_WORDS:
            raise NeedsHelp(error, PLAIN_WORDS[error] + (f" ({answer['count']} phần tử)" if answer.get("count") else ""))
        raise NeedsHelp(error, f"Trang trả lỗi «{error}» khi thao tác.")

    # ---- task 6.2: the teller points at the element ------------------------------------

    def suggest(self, selectors: list[str], want: str) -> list[dict[str, Any]]:
        """Up to 3 look-alikes in the step's frame: {src, tag, label, selectors}. Nothing is done to the page."""
        from rookie_agent.ie import locate

        if not hasattr(self._bridge, "frame_op"):
            return []
        frame, _ = locate.group_selectors(selectors)
        for answer in self._bridge.frame_op("suggest", selectors, want):
            if answer.get("frame") == frame and answer.get("candidates"):
                return list(answer.get("candidates") or [])[:3]
        # the frame of the recording is gone or has nothing alike: the look-alikes of every frame, the best first
        found = [c for answer in self._bridge.frame_op("suggest", any_frame(selectors), want) for c in answer.get("candidates") or []]
        return found[:3]

    def fingerprint(self) -> list[str]:
        """Task 6.4: the screen as `frame|tag:type|label` lines, sorted (no value)."""
        if not hasattr(self._bridge, "frame_op"):
            return []
        return sorted(f"{a.get('frame')}|{item}" for a in self._bridge.frame_op("fingerprint", []) for item in a.get("items") or [])

    def mark(self, candidates: list[dict[str, Any]]) -> None:
        self._bridge.frame_op("mark", [c["src"] for c in candidates])

    def unmark(self) -> None:
        try:
            self._bridge.frame_op("unmark", [])
        except Exception:  # noqa: BLE001  a page that has gone keeps no colour to take off
            pass

    def exists(self, selectors: list[str]) -> bool:
        try:
            self._act("exists", selectors)
            return True
        except ElementNotFound:
            return False

    def click(self, selectors: list[str]) -> None:
        self._act("click", selectors)

    def fill(self, selectors: list[str], value: str) -> None:
        answer = self._act("fill", selectors, value)
        kept = str(answer.get("value") if answer.get("value") is not None else "")
        # A page may reformat what was typed (the thousands in an amount, the case): the digits and letters must be the same.
        if kept.strip() != value.strip() and _squash(kept).lower() != _squash(value).lower():
            raise NeedsHelp("value_not_set", "Trang không giữ giá trị vừa nhập vào ô này (ô tự xoá hoặc đổi nội dung). Bạn xem lại màn hình.")

    def select(self, selectors: list[str], value: str) -> None:
        answer = self._act("select", selectors, value)
        if str(answer.get("value")) != value and str(answer.get("text")).strip() != value.strip():
            raise NeedsHelp("value_not_set", "Danh sách không dừng ở lựa chọn cần chọn. Bạn xem lại màn hình.")

    def submit(self, selectors: list[str]) -> None:
        self._act("submit", selectors)

    def read_screen(self) -> dict[str, str]:
        """The whole screen as data: every value by its path (see `read.paths`). Nothing of it is written anywhere."""
        from rookie_agent.ie import read

        return read.paths(read.model(read.parse(self._bridge.read())))

    def read_value(self, selectors: list[str]) -> str:
        return str(self._act("read", selectors).get("value") or "")
