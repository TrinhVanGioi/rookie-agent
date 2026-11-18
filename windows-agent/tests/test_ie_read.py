"""Tasks 4.31 and 4.32: what the screen shows after an action, and which part of it changed.

The page recorder reads each frame (tables, label-value pairs, messages). The full values stay in memory on the teller's PC; this
module only parses, compares and finds the region that changed, leaving out what changes by itself (a clock).
"""

import json

import pytest

from rookie_agent.ie import read


def frame(name="top", tables=None, fields=None, messages=None, title="Main"):
    return json.dumps({"frame": name, "title": title, "tables": tables or [], "fields": fields or [], "messages": messages or []})


def table(rows, headers=("So TK", "Loai", "So du"), table_id="grid"):
    return {"id": table_id, "headers": list(headers), "rows": rows, "row_count": len(rows)}


def test_raw_frames_are_parsed_and_a_broken_one_is_skipped():
    frames = read.parse([frame("top", fields=[{"label": "Ten", "value": "A"}]), "{not json", "", frame("main")])
    assert [f["frame"] for f in frames] == ["top", "main"]
    assert frames[0]["fields"] == [{"label": "Ten", "value": "A"}]


def test_a_new_table_and_a_new_message_are_the_changed_region():
    before = read.parse([frame("main"), frame("rtop", fields=[{"label": "Ngay", "value": "16/11"}])])
    after = read.parse([frame("main", tables=[table([["001", "DDA", "5"]])], messages=[{"level": "error", "text": "Khong tim thay"}]),
                        frame("rtop", fields=[{"label": "Ngay", "value": "16/11"}])])
    changed = read.changed(before, after)
    assert {(c["frame"], c["kind"]) for c in changed} == {("main", "table"), ("main", "message")}
    assert read.region(changed) == ["main"]


def test_nothing_changed_means_an_empty_region():
    a = read.parse([frame("main", tables=[table([["001", "DDA", "5"]])])])
    assert read.changed(a, read.parse([frame("main", tables=[table([["001", "DDA", "5"]])])])) == []


def test_a_changed_cell_is_a_change_of_that_table():
    a = read.parse([frame("main", tables=[table([["001", "DDA", "5"]])])])
    b = read.parse([frame("main", tables=[table([["001", "DDA", "6"]])])])
    assert [(c["kind"], c["frame"]) for c in read.changed(a, b)] == [("table", "main")]


def test_what_changes_by_itself_is_left_out_of_the_region():
    """Two reads of the screen at rest: a clock differs between them, so it is volatile and never counts as the result."""
    first = read.parse([frame("rtop", fields=[{"label": "Gio", "value": "09:00:01"}]), frame("main")])
    second = read.parse([frame("rtop", fields=[{"label": "Gio", "value": "09:00:02"}]), frame("main")])
    volatile = read.volatile(first, second)
    assert volatile == {("rtop", "field", "Gio")}
    after = read.parse([frame("rtop", fields=[{"label": "Gio", "value": "09:00:09"}]), frame("main", tables=[table([["9", "x", "1"]])])])
    changed = read.changed(second, after, volatile)
    assert [(c["frame"], c["kind"]) for c in changed] == [("main", "table")]


def test_a_frame_that_reloaded_completely_is_its_own_region():
    before = read.parse([frame("main", tables=[table([["1", "a", "b"]])])])
    after = read.parse([frame("main", tables=[table([["2", "c", "d"]], table_id="other")], fields=[{"label": "X", "value": "1"}])])
    assert read.region(read.changed(before, after)) == ["main"]


def test_the_summary_says_what_the_agent_saw_in_plain_words():
    frames = read.parse([frame("main", tables=[table([["001", "DDA", "5"], ["002", "SAV", "7"]])], messages=[{"level": "error", "text": "Loi X"}])])
    text = read.describe(frames)
    assert "2 dòng" in text and "Loi X" in text and "lỗi" in text


def test_a_message_that_is_a_clock_is_volatile_but_a_new_error_message_is_not():
    """The text of a message is its identity, so a ticking clock written as a message looks like a new message each second."""
    one = read.parse([frame("rtop", messages=[{"level": "info", "text": "time 100"}]), frame("main")])
    two = read.parse([frame("rtop", messages=[{"level": "info", "text": "time 250"}]), frame("main")])
    leave_out = read.volatile(one, two)
    now = read.parse([frame("rtop", messages=[{"level": "info", "text": "time 400"}]),
                      frame("main", messages=[{"level": "error", "text": "Khong tim thay"}])])
    changes = read.changed(two, now, leave_out)
    assert [(c["frame"], c["kind"]) for c in changes] == [("main", "message")]


# ---- what the screen shows as data the agent can call: an object, key-value pairs, a list of rows ----

def customer_screen():
    return read.parse([
        frame("rtop", fields=[{"label": "Ngày làm việc", "value": "16/11/2026"}]),
        frame("main",
              fields=[{"label": "Số tài khoản:", "value": "0123456789"}, {"label": "Tên khách hàng", "value": "NGUYEN VAN A"}],
              tables=[table([["0123456789", "DDA", "5.000.000"], ["9876543210", "SAV", "7.000"]], headers=("Số TK", "Loại", "Số dư"))],
              messages=[{"level": "info", "text": "Tìm thấy 2 tài khoản"}]),
    ])


def test_the_screen_is_an_object_of_frames_with_key_value_fields_and_tables_of_row_objects():
    model = read.model(customer_screen())
    main = model["frames"]["main"]
    assert main["fields"] == {"so_tai_khoan": "0123456789", "ten_khach_hang": "NGUYEN VAN A"}          # key-value
    grid = main["tables"]["grid"]
    assert grid["columns"] == ["so_tk", "loai", "so_du"] and grid["row_count"] == 2
    assert grid["rows"][1] == {"so_tk": "9876543210", "loai": "SAV", "so_du": "7.000"}                  # a list of objects
    assert model["messages"] == [{"frame": "main", "level": "info", "text": "Tìm thấy 2 tài khoản"}]


def test_every_value_has_a_path_and_a_short_name_when_it_is_unique():
    paths = read.paths(read.model(customer_screen()))
    assert paths["main.fields.so_tai_khoan"] == "0123456789"
    assert paths["so_tai_khoan"] == "0123456789"                          # unique: the short name works
    assert paths["grid.0.so_tk"] == "0123456789" and paths["grid.1.loai"] == "SAV"
    assert paths["main.tables.grid.rows.1.so_du"] == "7.000"
    assert paths["message.0"] == "Tìm thấy 2 tài khoản" and paths["message.0.level"] == "info"


def test_a_name_that_two_places_share_is_not_given_a_short_form_and_is_never_guessed():
    frames = read.parse([frame("a", fields=[{"label": "Ten", "value": "1"}]), frame("b", fields=[{"label": "Ten", "value": "2"}])])
    paths = read.paths(read.model(frames))
    assert "ten" not in paths and paths["a.fields.ten"] == "1" and paths["b.fields.ten"] == "2"
    with pytest.raises(read.NoSuchData):
        read.lookup(paths, "ten")
    assert read.lookup(paths, "b.fields.ten") == "2"
    with pytest.raises(read.NoSuchData):
        read.lookup(paths, "khong.co")


def test_a_one_row_table_is_also_an_object():
    paths = read.paths(read.model(read.parse([frame("main", tables=[table([["1", "DDA", "5"]], table_id="kq")])])))
    assert paths["kq.so_tk"] == "1" and paths["kq.0.so_tk"] == "1"        # a single result needs no row number


def test_the_data_is_listed_for_the_panel_with_the_name_to_call_it_by():
    listed = read.listing(read.model(customer_screen()))
    assert {"kind": "field", "path": "so_tai_khoan", "value": "0123456789", "placeholder": "{ten_bien.so_tai_khoan}"} in listed
    assert any(item["kind"] == "cell" and item["path"] == "grid.0.so_tk" for item in listed)
