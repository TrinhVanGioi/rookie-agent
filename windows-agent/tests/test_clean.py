"""Task 11.4: the rules that clean the recordings of one task before learning (rookie_agent/ie/clean.py)."""

from __future__ import annotations

from rookie_agent.ie import clean


def ev(seq, kind, sel, label, value=None):
    return {"seq": seq, "type": kind, "target": {"selectors": [sel], "label": label, "tag": "input"}, "value": value}


def gwt(seq, service, method):
    return {"after_seq": seq, "status": 200, "method": "POST", "url": "http://tp/tp/TPClassLoader",
            "body": f"7|0|5|http://tp/tp/|ABC|com.fis.tp.client.{service}|{method}|⟦e{seq}⟧|"}


def token(seq):
    return {"after_seq": seq, "status": 200, "method": "POST", "url": "http://tp/tp/postAuthentication.fisglobal?method=getToken&claims=x", "body": ""}


BUTTON = {"events": [ev(0, "input", "#txtAcct", "Số tài khoản", "1"), ev(1, "click", "#btnFind", "TRA CỨU")],
          "requests": [token(1), gwt(1, "AcctService", "find")]}
ENTER = {"events": [ev(0, "input", "#txtAcct", "Số tài khoản", "2"), ev(1, "submit", "#txtAcct", "Số tài khoản")],
         "requests": [token(1), gwt(1, "AcctService", "find")]}


def test_an_enter_that_does_what_the_button_does_in_another_recording_becomes_that_button():
    button, enter = clean.unify_triggers([BUTTON, ENTER])
    assert button == BUTTON["events"]
    assert enter[1]["type"] == "click" and enter[1]["target"]["selectors"] == ["#btnFind"] and enter[1]["seq"] == 1
    assert ENTER["events"][1]["type"] == "submit"           # the recording itself is not changed


def test_an_enter_with_another_effect_stays_an_enter():
    other = {**ENTER, "requests": [token(1), gwt(1, "HistoryService", "list")]}
    assert clean.unify_triggers([BUTTON, other])[1][1]["type"] == "submit"


def test_when_every_recording_pressed_enter_nothing_changes():
    assert [e["type"] for e in clean.unify_triggers([ENTER, ENTER])[0]] == ["input", "submit"]


def keepalive(seq, index, t):
    return {"index": index, "after_seq": seq, "status": 200, "method": "GET", "url": f"http://tp/tp/keepalive?t={t}", "body": ""}


def test_a_keep_alive_with_a_time_in_it_is_the_page_asking_by_itself_and_is_in_no_effect():
    requests = [{**r, "index": i} for i, r in enumerate(BUTTON["requests"])] + [keepalive(1, 2 + k, 1732000000000 + 4000 * k) for k in range(3)]
    assert clean.polling(requests) == {2, 3, 4}
    assert clean.effect({"requests": requests}, 1) == clean.effect(BUTTON, 1)


def test_a_call_repeated_whose_answer_a_later_call_needs_is_not_polling():
    requests = [{**token(1), "index": i} for i in range(3)] + [{**gwt(1, "AcctService", "find"), "index": 3, "links": {"l1": {"from": 2}}}]
    assert clean.polling(requests) == {0, 1}


def test_a_press_that_only_opened_the_message_box_and_was_made_again_is_left_out_with_the_box():
    doc = {"events": [ev(0, "input", "#txtFrom", "Từ ngày", "02-11-2026"), ev(1, "click", "#btnHistory", "XEM LỊCH SỬ"),
                      {**ev(2, "click", "#btnOK", "ĐỒNG Ý"), "url": "http://tp/tp/utilities/dlgMessageBox.jsp?msg=x"},
                      ev(3, "input", "#txtFrom", "Từ ngày", "02/11/2026"), ev(4, "click", "#btnHistory", "XEM LỊCH SỬ")],
           "requests": [{"index": 0, "after_seq": 1, "status": 200, "method": "GET", "url": "http://tp/tp/utilities/dlgMessageBox.jsp?msg=Sai", "body": ""},
                        {**token(4), "index": 1}, {**gwt(4, "HistoryService", "list"), "index": 2, "body": "7|0|7|b|s|com.fis.tp.client.HistoryService|list|⟦e3⟧|"}]}
    (out,) = clean.clean([doc])
    assert [(e["seq"], e["type"], e["target"]["label"]) for e in out["events"]] == [(0, "input", "Từ ngày"), (1, "input", "Từ ngày"), (2, "click", "XEM LỊCH SỬ")]
    assert [r["after_seq"] for r in out["requests"]] == [2, 2]
    assert out["requests"][1]["body"].endswith("|⟦e1⟧|")            # the mark follows its event's new number
    assert doc["events"][1]["seq"] == 1 and len(doc["requests"]) == 3     # the recording itself is not changed


def test_a_press_without_a_service_call_that_is_not_made_again_stays():
    doc = {"events": [ev(0, "click", "#tabInfo", "Thông tin")], "requests": []}
    assert len(clean.clean([doc])[0]["events"]) == 1


def test_the_effect_names_what_a_call_does_never_a_value():
    assert clean.effect(BUTTON, 1) == ("POST /tp/postAuthentication.fisglobal getToken", "POST /tp/TPClassLoader AcctService.find")
    failed = {"requests": [{**gwt(1, "AcctService", "find"), "status": 500}]}
    assert clean.effect(failed, 1) == ()
