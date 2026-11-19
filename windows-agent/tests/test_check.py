"""Task 11.3: a recording checks itself after «Dừng ghi» and says, in plain words, what to record again."""

from __future__ import annotations

from rookie_agent.ie import check


def ev(seq, kind, label):
    return {"seq": seq, "type": kind, "target": {"selectors": [f"label={label}"], "label": label}}   # one button: one selector


def call(seq, index, url="http://tp/tp/TPClassLoader", status=200, complete=True, **extra):
    return {"index": index, "after_seq": seq, "status": status, "method": "POST", "url": url, "kind": "xhr", "complete": complete,
            "body": "7|0|5|b|s|com.fis.tp.client.AcctService|find|⟦e0⟧|", **extra}


def levels(found):
    return [f["level"] for f in found]


def test_a_good_recording_says_so_and_what_to_do_next():
    found = check.check({"events": [ev(0, "input", "Số tài khoản"), ev(1, "click", "TRA CỨU")], "requests": [call(1, 0)]})
    assert levels(found) == ["ok"] and "2 thao tác, 1 lời gọi" in found[0]["text"]


def test_a_failed_call_and_a_token_without_source_ask_to_record_again_and_say_where():
    doc = {"events": [ev(0, "click", "TRA CỨU"), ev(1, "click", "XEM")],
           "requests": [call(0, 0, status=500), call(1, 1, complete=False)]}
    found = check.check(doc)
    assert levels(found) == ["redo", "redo"]
    assert "«TRA CỨU»" in found[0]["text"] and "«XEM»" in found[1]["text"] and "mở màn hình" in found[1]["hint"]


def test_a_message_box_a_mistaken_press_and_a_guessed_file_are_notes():
    doc = {"events": [ev(0, "click", "XEM"), ev(1, "click", "XEM"), ev(2, "click", "IN")],
           "requests": [call(0, 0, url="http://tp/tp/utilities/dlgMessageBox.jsp?msg=x"), call(1, 1),
                        call(2, 2, url="http://tp/tp/exportPdf", file={"guess": True})]}
    found = check.check(doc)
    assert levels(found) == ["note", "note", "note", "ok"], found
    assert "hộp thông báo" in found[0]["text"] and "file" in found[1]["text"] and "bấm nhầm" in found[2]["text"]


def test_without_requests_it_says_only_the_screen_can_be_used():
    found = check.check({"events": [ev(0, "click", "TRA CỨU")], "requests": []}, requests_on=False)
    assert levels(found) == ["note"] and "Ghi yêu cầu" in found[0]["text"]


def test_after_learning_it_says_how_many_steps_run_by_request_and_why_the_others_do_not():
    api = [{"id": "a1", "group": "g1", "group_label": "Tra cứu", "step_id": "s1", "risk": "read", "complete": True, "unresolved": [], "method": "POST", "url": "/x"},
           {"id": "a2", "group": "g2", "group_label": "Xem lịch sử", "step_id": "s2", "risk": "read", "complete": True, "unresolved": ["l9"], "method": "POST", "url": "/y"},
           {"id": "a3", "group": "g3", "group_label": "In", "step_id": "s3", "risk": "read", "complete": True, "unresolved": [], "kind": "file", "method": "POST", "url": "/z"},
           {"id": "a4", "group": "g4", "group_label": "Gửi duyệt", "step_id": "s4", "risk": "money", "complete": True, "unresolved": [], "method": "POST", "url": "/m"}]
    report = check.learned(api, {"steps": []})
    assert (report["ready"], report["total"]) == (2, 4)
    assert report["lines"][0] == "Chạy lại được bằng yêu cầu: 2/3 bước chỉ xem. Có 1 bước trả về file (lưu vào thư mục Rookie, có nút In)."
    assert any("«Xem lịch sử»" in line and "l9" in line for line in report["lines"]) and any("«Gửi duyệt»" in line and "Duyệt" in line for line in report["lines"])


def test_a_part_of_the_page_the_recorder_cannot_read_asks_for_a_diagnosis():
    found = check.check({"events": [ev(0, "click", "A")], "requests": [call(0, 0)]}, notes=["window 2 frame='x' không với tới"])
    assert "redo" in levels(found) and "Gửi chẩn đoán" in found[-1]["hint"]
