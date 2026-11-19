"""The Assistant fills the inputs of an agent from the sentence, on this PC: accounts, dates, ranges; asks when it is not sure."""

import json
from datetime import date

import pytest

from rookie_agent.assistant import slots
from rookie_agent.assistant.planner import Planner

TODAY = date(2026, 11, 19)


def extract(text):
    return slots.extract(text, TODAY)


@pytest.mark.parametrize("text, expected", [
    ("ngày 01/11/2026", date(2026, 11, 1)),
    ("ngày 01-11-2026", date(2026, 11, 1)),
    ("ngày 1.11.2026", date(2026, 11, 1)),
    ("ngày 2026-11-01", date(2026, 11, 1)),
    ("ngày 15/11", date(2026, 11, 15)),                 # no year: this year
    ("hôm nay", TODAY),
    ("hôm qua", date(2026, 11, 18)),
])
def test_each_form_of_a_single_date(text, expected):
    assert extract(text)["dates"] == [expected]


def test_a_month_is_a_range():
    assert extract("báo cáo tháng này")["range"] == (date(2026, 11, 1), TODAY)
    assert extract("báo cáo tháng trước")["range"] == (date(2026, 10, 1), date(2026, 10, 31))


def test_from_to_range_with_or_without_the_word_ngay_and_with_relative_words():
    assert extract("từ ngày 01/11/2026 đến ngày 15/11/2026")["range"] == (date(2026, 11, 1), date(2026, 11, 15))
    assert extract("từ 01/11 tới 15/11")["range"] == (date(2026, 11, 1), date(2026, 11, 15))
    assert extract("từ hôm qua đến hôm nay")["range"] == (date(2026, 11, 18), TODAY)
    assert extract("từ 15/11/2026 đến 01/11/2026")["range"] is None and extract("từ 15/11/2026 đến 01/11/2026")["problems"]


def test_one_sided_and_impossible_dates():
    one = extract("từ ngày 01/11/2026")
    assert one["from_date"] == date(2026, 11, 1) and one["to_date"] is None and one["range"] is None
    assert extract("đến 15/11")["to_date"] == date(2026, 11, 15)
    bad = extract("ngày 31/02/2026")
    assert bad["dates"] == [] and "31/02/2026" in bad["problems"][0]


def test_accounts_are_digit_runs_of_6_to_20_with_or_without_a_word_before_them():
    assert extract("stk 0123456789")["accounts"] == [{"value": "0123456789", "kind": "account"}]
    assert extract("số tài khoản 0123456789")["accounts"][0]["kind"] == "account"
    assert extract("TK: 0123456789")["accounts"][0]["kind"] == "account"
    assert extract("0123456789")["accounts"] == [{"value": "0123456789", "kind": ""}]
    assert extract("cif 123456")["accounts"] == [{"value": "123456", "kind": "cif"}]
    assert extract("stk 12345")["accounts"] == []                      # too short
    assert extract("ngày 01/11/2026")["accounts"] == []                # a date is not an account


def test_amounts():
    assert extract("chuyển 5 triệu")["amounts"] == ["5000000"]


@pytest.mark.parametrize("name, label, kind", [
    ("tu_ngay", "Từ ngày", "date_from"), ("den_ngay", "Đến ngày", "date_to"), ("txtFromDate", "", "date_from"), ("todate", "", "date_to"),
    ("start_date", "Ngày bắt đầu", "date_from"), ("end_date", "Ngày kết thúc", "date_to"), ("ngay", "Ngày giao dịch", "date"),
    ("so_tai_khoan", "Số tài khoản", "account"), ("acct", "", "account"), ("stk", "", "account"), ("account_no", "", "account"),
    ("cif", "Số CIF", "cif"), ("so_tien", "Số tiền", "amount"), ("ho_ten", "Họ tên", None),
])
def test_an_input_is_known_by_its_name_or_label(name, label, kind):
    assert slots.input_kind({"name": name, "label": label}) == kind


def test_a_recorded_example_makes_an_input_a_date_and_tells_its_format():
    assert slots.input_kind({"name": "txtFrom", "label": "From", "format": "dd/mm/yyyy"}) == "date_from"
    assert slots.detect_format("31/01/2026") == "dd/mm/yyyy" and slots.detect_format("2026-01-31") == "yyyy-mm-dd"
    assert slots.detect_format("31-01-2026") == "dd-mm-yyyy" and slots.detect_format("1/2/2026") == "d/m/yyyy"
    assert slots.detect_format("31/02/2026") is None and slots.detect_format("abc") is None and slots.detect_format("0123456789") is None


def test_dates_are_written_in_the_recorded_format_else_dd_mm_yyyy():
    value = date(2026, 11, 1)
    assert slots.format_date(value, "yyyy-mm-dd") == "2026-11-01" and slots.format_date(value, "dd-mm-yyyy") == "01-11-2026"
    assert slots.format_date(value, "d/m/yyyy") == "1/11/2026" and slots.format_date(value, "ddmmyyyy") == "01112026"
    assert slots.format_date(value, None) == "01/11/2026"


EXPORT_INPUTS = [{"name": "so_tai_khoan", "label": "Số tài khoản"}, {"name": "tu_ngay", "label": "Từ ngày", "format": "dd-mm-yyyy"},
                 {"name": "den_ngay", "label": "Đến ngày"}]


def fill(text, inputs=EXPORT_INPUTS):
    return slots.fill(extract(text), inputs, TODAY)


def test_the_whole_sentence_fills_account_and_both_dates_each_in_its_own_format():
    done = fill("xuất báo cáo giao dịch của stk 0123456789 từ ngày 01/11/2026 đến ngày 15/11/2026")
    assert done["values"] == {"so_tai_khoan": "0123456789", "tu_ngay": "01-11-2026", "den_ngay": "15/11/2026"} and done["asks"] == {}


def test_a_type_date_input_without_a_format_is_iso_because_that_is_how_it_was_recorded():
    done = slots.fill(extract("từ 01/11/2026 đến 15/11/2026"), [{"name": "a", "label": "Từ ngày", "type": "date"}, {"name": "b", "label": "Đến ngày", "type": "date"}], TODAY)
    assert done["values"] == {"a": "2026-11-01", "b": "2026-11-15"}


def test_missing_values_are_asked_never_guessed():
    done = fill("xuất báo cáo giao dịch của stk 0123456789")
    assert done["values"] == {"so_tai_khoan": "0123456789"} and "tu_ngay" in done["asks"] and done["asks"]["den_ngay"] == ""   # one question for the pair
    two = fill("xuất báo cáo 01/11/2026 15/11/2026 stk 0123456789")
    assert "tu_ngay" not in two["values"] and "den_ngay" not in two["values"] and two["asks"]["tu_ngay"]                       # two bare dates: which is which?
    many = fill("stk 0123456789 và stk 9876543210")
    assert "so_tai_khoan" not in many["values"] and "2 dãy số" in many["asks"]["so_tai_khoan"]
    bad = fill("từ ngày 31/02/2026 đến 15/11/2026")
    assert "tu_ngay" not in bad["values"] and "không có thật" in bad["asks"]["tu_ngay"]


def test_one_sided_dates_fill_only_their_side():
    done = fill("từ ngày 01/11/2026")
    assert done["values"] == {"tu_ngay": "01-11-2026"} and "den_ngay" in done["asks"] and "tu_ngay" not in done["asks"]


def test_a_single_date_fills_the_only_date_input_and_a_month_needs_two():
    one = slots.fill(extract("hôm nay"), [{"name": "ngay", "label": "Ngày giao dịch"}], TODAY)
    assert one["values"] == {"ngay": "19/11/2026"}
    month = slots.fill(extract("tháng này"), [{"name": "ngay", "label": "Ngày giao dịch"}], TODAY)
    assert month["values"] == {} and month["asks"]["ngay"]
    both = fill("báo cáo tháng trước stk 0123456789")
    assert both["values"] == {"so_tai_khoan": "0123456789", "tu_ngay": "01-10-2026", "den_ngay": "31/10/2026"}


def test_an_example_sentence_for_the_card():
    assert slots.example_sentence("Xuất báo cáo giao dịch", EXPORT_INPUTS, TODAY) == \
        "xuất báo cáo giao dịch của stk 0123456789 từ ngày 01/11/2026 đến ngày 19/11/2026"


# ---- through the planner ----------------------------------------------------------------------------------------------------------------

def flow(title="Xuất báo cáo giao dịch"):
    return {"title": title, "input_formats": {"tu_ngay": "dd/mm/yyyy", "den_ngay": "dd/mm/yyyy"},
            "workflow": {"status": "approved", "engine": "ie",
                         "inputs": [{"name": "so_tai_khoan", "label": "Số tài khoản", "type": "string"}, {"name": "tu_ngay", "label": "Từ ngày", "type": "string"},
                                    {"name": "den_ngay", "label": "Đến ngày", "type": "string"}],
                         "steps": [{"action": "fill", "risk": "read", "mode": "auto", "target": {"label": x}} for x in ("Số tài khoản", "Từ ngày", "Đến ngày")] + [
                                   {"action": "click", "risk": "read", "mode": "auto", "target": {"label": "Xuất báo cáo"}}]}}


class Server:
    def __init__(self):
        self.sent = []

    def __call__(self, payload):
        self.sent.append(payload)
        return {"schema_version": 1, "method": "rule", "fallback_reason": None, "chain": [], "candidates": [{"ref": "w1", "confidence": 0.95, "slots": {}}]}


import time

DAY = time.mktime((2026, 11, 19, 10, 0, 0, 0, 0, -1))


def planner(server=None):
    return Planner(server or Server(), lambda: [flow()], None, lambda: DAY)


SENTENCE = "xuất báo cáo giao dịch của stk 0123456789 từ ngày 01/11/2026 đến ngày 15/11/2026"


def test_the_sentence_fills_everything_and_only_the_masked_sentence_leaves_the_pc():
    server = Server()
    shown = planner(server).plan(SENTENCE)
    assert shown["state"] == "ready", shown
    assert {i["name"]: i["value"] for i in shown["inputs"]} == {"so_tai_khoan": "0123456789", "tu_ngay": "01/11/2026", "den_ngay": "15/11/2026"}
    assert all(i["source"] == "lấy từ câu bạn gõ" for i in shown["inputs"])
    sent = json.dumps(server.sent, ensure_ascii=False)
    for secret in ("0123456789", "01/11/2026", "15/11/2026", "stk 0123"):
        assert secret not in sent, secret


def test_a_missing_date_becomes_a_question_and_the_teller_answers_in_the_chat():
    p = planner()
    shown = p.plan("xuất báo cáo giao dịch của stk 0123456789")
    assert shown["state"] == "need_inputs" and len(shown["questions"]) == 1 and "từ" in shown["questions"][0].lower()
    assert [i["value"] for i in shown["inputs"]] == ["0123456789", "", ""]
    shown = p.answer(shown["plan_id"], text="từ 01/11/2026 đến 15/11/2026")
    assert shown["state"] == "ready" and shown["understood"] is True
    assert [i["value"] for i in shown["inputs"]] == ["0123456789", "01/11/2026", "15/11/2026"]


def test_a_line_that_fills_nothing_is_reported_as_not_understood():
    p = planner()
    shown = p.plan("xuất báo cáo giao dịch của stk 0123456789")
    again = p.answer(shown["plan_id"], text="cảm ơn nhé")
    assert again["state"] == "need_inputs" and again["understood"] is False


def test_relative_words_use_the_clock_of_this_pc():
    shown = planner().plan("xuất báo cáo giao dịch stk 0123456789 tháng này")
    assert shown["state"] == "ready" and [i["value"] for i in shown["inputs"]][1:] == ["01/11/2026", "19/11/2026"]


def test_the_values_in_the_card_can_be_edited():
    p = planner()
    shown = p.plan(SENTENCE)
    changed = p.answer(shown["plan_id"], given={"den_ngay": "20/11/2026"})
    assert changed["state"] == "ready" and changed["inputs"][2]["value"] == "20/11/2026" and changed["inputs"][2]["source"] == "bạn nhập"
    assert p.take(shown["plan_id"]) == ("Xuất báo cáo giao dịch", {"so_tai_khoan": "0123456789", "tu_ngay": "01/11/2026", "den_ngay": "20/11/2026"})


def test_the_real_rule_based_server_picks_the_flow_from_the_sentence():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
    from app import assistant as server_side

    other = {"title": "Vấn tin tài khoản", "workflow": {"status": "approved", "engine": "ie", "inputs": [{"name": "so_tai_khoan", "label": "Số tài khoản"}],
                                                        "steps": [{"action": "click", "risk": "read", "mode": "auto", "target": {"label": "Tra cứu"}}]}}
    shown = Planner(server_side.plan, lambda: [other, flow()], None, lambda: DAY).plan(SENTENCE)
    assert shown["state"] == "ready" and shown["workflow"]["title"] == "Xuất báo cáo giao dịch", shown
