"""Task 12.3 (SADPT, Plan and Execute): on a read step the agent finds its element again by itself when the evidence is strong, checks
the screen after, and keeps the new selectors as a draft for a person to approve. Write and money steps never do this."""

from __future__ import annotations

import json

from rookie_agent import runner
from rookie_agent.ie import locate

TARGET = {"selectors": ["frame=work|id=btnFind", "frame=work|label=TRA CỨU", "frame=work|button[3]"], "label": "TRA CỨU", "tag": "button"}


def cand(src, label, selectors, tag="button"):
    return {"src": f"frame=work|src={src}", "tag": tag, "label": label, "selectors": selectors}


MOVED = cand(41, "TRA CỨU", ["frame=work|id=btnSearch2", "frame=work|label=TRA CỨU", "frame=work|button[5]"])
OTHER = cand(42, "TRA CỨU LỊCH SỬ", ["frame=work|id=btnHist", "frame=work|label=TRA CỨU LỊCH SỬ", "frame=work|button[6]"])


def test_one_look_alike_with_the_same_label_in_the_same_frame_and_kind_is_picked_and_says_why():
    pick = locate.auto_pick(TARGET, [MOVED, OTHER])
    assert pick is not None and pick["index"] == 0 and set(pick["signals"]) >= {"label", "frame", "kind"}


def test_two_equally_good_look_alikes_or_only_a_shared_word_are_not_enough():
    twin = cand(43, "TRA CỨU", ["frame=work|id=btnX", "frame=work|label=TRA CỨU", "frame=work|button[9]"])
    assert locate.auto_pick(TARGET, [MOVED, twin]) is None                    # never one of two look-alikes
    assert locate.auto_pick(TARGET, [OTHER]) is None                          # a label that only shares words
    elsewhere = cand(44, "TRA CỨU", ["frame=top|id=b", "frame=top|label=TRA CỨU", "frame=top|button[1]"])
    assert locate.auto_pick(TARGET, [elsewhere]) is None                      # the same words in another frame
    bare = {"selectors": ["frame=work|id=btnFind", "frame=work|button[3]"], "label": None, "tag": "button"}
    assert locate.auto_pick(bare, [MOVED]) is None                            # no label or name to go by: frame and kind are not enough


# ---- in the runner ---------------------------------------------------------------------------------------------------------------

class MovedDriver:
    """The learned button is gone (low confidence); the page offers look-alikes; the element by its src works."""

    def __init__(self, candidates, screen_after=None):
        self.candidates, self.done, self.marked = candidates, [], []
        self.after = screen_after or [{"frame": "work", "tables": [{"id": "tblInfo", "headers": ["A"], "rows": [["1"]]}], "fields": [], "messages": []}]

    def window_title(self):
        return "Mock TouchPoint"

    def exists(self, selectors):
        return True

    def click(self, selectors):
        if not selectors[0].startswith("frame=work|src="):
            raise runner.NeedsHelp("low_confidence", "chưa chắc")
        self.done.append(selectors[0])

    def suggest(self, selectors, want):
        return list(self.candidates)

    def mark(self, candidates):
        self.marked.append(candidates)

    def unmark(self):
        pass

    def look(self):
        return self.after if self.done else [{"frame": "work", "tables": [], "fields": [], "messages": []}]


class Teller(runner.AutoController):
    def __init__(self):
        super().__init__()
        self.picks = 0

    def pick(self, step, candidates):
        self.picks += 1
        return None


def flow(risk="read"):
    step = {"id": "s1", "action": "click", "target": TARGET, "risk": risk, "mode": "auto" if risk == "read" else "approve", "intent": "TRA CỨU",
            "expect": {"appears": [{"frame": "work", "kind": "table", "name": "tblInfo"}]}, "adapt": {"reresolve": risk == "read"}}
    return {"schema_version": 4, "engine": "ie", "id": "f", "version": 3, "status": "approved", "inputs": [], "steps": [step]}


def go(workflow, driver, teller):
    return runner.run_workflow(workflow, {}, driver, teller, engine="ie", versions=(2, 3, 4), post_timeout=0.5, sleep=lambda s: None,
                               allow_write_on_real=True)


def test_a_read_step_whose_button_moved_is_found_again_without_asking_checked_after_and_kept_as_a_draft():
    d, teller = MovedDriver([MOVED, OTHER]), Teller()
    result = go(flow(), d, teller)
    assert result["status"] == "finished" and d.done == ["frame=work|src=41"] and teller.picks == 0 and d.marked == []
    assert result["repairs"] == [{"step_id": "s1", "selectors": MOVED["selectors"], "auto": True}]
    (row,) = result["decisions"]
    assert row["saw"] == "low_confidence" and row["change"] == "technical" and row["action"] == "reresolve" and row["outcome"] == "done"
    assert "label" in row["where"]["how"]


def test_when_the_screen_after_is_not_what_was_learned_the_found_element_is_not_trusted():
    d = MovedDriver([MOVED], screen_after=[{"frame": "work", "tables": [], "fields": [], "messages": []}])
    result = go(flow(), d, Teller())
    assert result["status"] == "needs_help" and "repairs" not in result
    assert [r["outcome"] for r in result["decisions"]] == ["postcheck_failed", "stopped"]


def test_not_enough_evidence_goes_back_to_asking_the_teller():
    teller = Teller()
    result = go(flow(), MovedDriver([OTHER]), teller)
    assert teller.picks == 1 and result["status"] == "needs_help" and "repairs" not in result
    (row,) = result["decisions"]
    assert row["change"] == "technical" and row["action"] == "ask" and row["outcome"] == "stopped" and row["risk"] == "read"


def test_a_write_step_never_finds_its_element_by_itself():
    workflow = flow("write")
    teller = Teller()
    result = go(workflow, MovedDriver([MOVED]), teller)
    assert teller.picks == 1 and result["status"] == "needs_help" and "repairs" not in result
    assert result["decisions"] == [{"step_id": "s1", "saw": "low_confidence", "change": "technical", "action": "ask", "outcome": "stopped", "risk": "write"}]
    assert "0123" not in json.dumps(result)
