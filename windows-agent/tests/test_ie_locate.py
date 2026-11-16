"""How the runner decides which element of an IE page a step means (docs/runner-ie-design.md 7).

Pure functions: selectors in, an evidence score out. No LLM, no page.
"""

import pytest

from rookie_agent.ie import locate
from rookie_agent.ie.locate import Probe, choose, group_selectors, parse_selector

FRAME = "desktopFrame/rtop/main/fraProfileArea"
FIELD = {"field": 1, "press": 0}
PRESS = {"field": 0, "press": 1}


def els(*uids, **kind):
    return {uid: kind or FIELD for uid in uids}


# ---- selectors -----------------------------------------------------------------------------------------------

def test_the_four_selector_kinds_the_recorder_writes_are_understood():
    assert parse_selector(f"frame={FRAME}|id=txtCustomerId") == ("id", FRAME, "txtCustomerId", None)
    assert parse_selector(f"frame={FRAME}|name=txtPartyID") == ("name", FRAME, "txtPartyID", None)
    assert parse_selector(f"frame={FRAME}|label=Mã khách hàng") == ("label", FRAME, "Mã khách hàng", None)
    assert parse_selector(f"frame={FRAME}|input[3]") == ("pos", FRAME, "input", 3)


def test_a_selector_without_a_frame_and_a_broken_one():
    assert parse_selector("label=THÊM") == ("label", None, "THÊM", None)
    for broken in ("", "x", "frame=a", "frame=a|", "frame=a|input[x]", "frame=a|id="):
        assert parse_selector(broken) is None


def test_selectors_of_one_step_are_grouped_into_the_frame_of_the_first_one():
    frame, tests = group_selectors([
        f"frame={FRAME}|id=txtCustomerId", "label=Mã khách hàng", "frame=top|id=other", "broken", f"frame={FRAME}|input[2]"])
    assert frame == FRAME
    assert tests == [("id", "txtCustomerId", None), ("label", "Mã khách hàng", None), ("pos", "input", 2)]


def test_with_no_frame_anywhere_the_top_window_is_used():
    assert group_selectors(["label=THÊM"]) == ("top", [("label", "THÊM", None)])
    assert group_selectors(["broken"]) == ("top", [])


# ---- the score ------------------------------------------------------------------------------------------------

def result(tests, elements, want="field", risk="read"):
    return choose(tests, elements, want, risk)


def test_a_unique_id_with_name_and_label_agreeing_scores_one():
    r = result([Probe("id", [41]), Probe("name", [41]), Probe("label", [41])], els(41))
    assert (r.state, r.uid, r.how) == ("ok", 41, "id") and r.score == 1.0 and r.counts == [1, 1, 1]


def test_a_name_alone_is_point_nine_and_a_label_agreeing_adds_a_tenth():
    assert result([Probe("id", []), Probe("name", [41])], els(41)).score == 0.9
    assert result([Probe("id", []), Probe("name", [41]), Probe("label", [41])], els(41)).score == 1.0


def test_a_label_and_a_position_agreeing_are_enough_for_a_write_step():
    r = result([Probe("label", [41]), Probe("pos", [41])], els(41, **PRESS), want="press", risk="write")
    assert r.state == "ok" and r.score == pytest.approx(0.9)


def test_a_duplicate_id_is_resolved_by_the_intersection_with_the_position():
    r = result([Probe("id", [41, 57]), Probe("pos", [41])], els(41, 57))
    assert (r.state, r.uid, r.how) == ("ok", 41, "intersect") and r.score == 0.8
    # point eight is enough to read, not enough to write
    assert result([Probe("id", [41, 57]), Probe("pos", [41])], els(41, 57), risk="write").state == "low_confidence"


def test_only_the_position_is_never_enough():
    r = result([Probe("id", []), Probe("label", []), Probe("pos", [41])], els(41))
    assert r.state == "low_confidence" and r.score == 0.5


def test_a_label_that_points_elsewhere_than_the_position_costs_two_tenths():
    r = result([Probe("label", [41]), Probe("pos", [57])], els(41, 57))
    assert r.state == "low_confidence" and r.score == pytest.approx(0.6)


def test_the_wrong_kind_of_element_scores_zero():
    assert result([Probe("id", [41])], els(41, **PRESS), want="field").score == 0
    assert result([Probe("id", [41])], els(41, **FIELD), want="press").score == 0
    assert result([Probe("id", [41])], els(41, **FIELD), want="field").state == "ok"
    assert result([Probe("id", [41])], els(41, **FIELD), want="any").state == "ok"


def test_nothing_found_is_not_found_and_several_equal_candidates_are_ambiguous():
    assert result([Probe("id", []), Probe("label", [])], {}).state == "not_found"
    assert result([Probe("label", [41, 57])], els(41, 57)).state == "ambiguous"
    assert result([Probe("id", [41, 57]), Probe("name", [41, 57])], els(41, 57)).state == "ambiguous"


def test_the_thresholds_follow_the_risk_of_the_step():
    assert locate.THRESHOLD == {"read": 0.8, "write": 0.9, "money": 0.9}
    tests = [Probe("name", [41])]  # 0.9
    assert result(tests, els(41), risk="read").state == "ok"
    assert result(tests, els(41), risk="write").state == "ok"
    assert result([Probe("label", [41])], els(41), risk="write").state == "low_confidence"  # 0.8 only
    assert result([Probe("label", [41])], els(41), risk="money").state == "low_confidence"
    assert result([Probe("label", [41])], els(41), risk="read").state == "ok"
