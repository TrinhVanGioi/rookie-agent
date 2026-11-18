"""Task 4.2: the masked trace built on the teller's PC from the raw lines of several sessions (schemas/trace.schema.json).

Everything is kept except what is sensitive: no password or OTP, no typed character, no long number, no customer's name.
"""

import json
from pathlib import Path

import pytest

from rookie_agent.ie.trace import TraceBuilder

SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "trace.schema.json").read_text(encoding="utf-8"))


def line(t, kind, **fields):
    base = {"t": t, "kind": kind, "frame": "top", "title": "TouchPoint Main", "tag": "input", "type": "text", "id": "", "name": "",
            "label": "", "pos": 0, "value": None, "keyclass": None, "ctl": True}
    base.update(fields)
    return base


def session(customer: str, amount: str = "5000000"):
    return [
        line(1000, "change", id="txtCust", label="Ma khach hang", value=customer),
        line(1500, "key", id="txtCust", label="Ma khach hang", keyclass="enter"),
        line(2000, "change", id="pw", type="password", label="Mat khau", value="TOPSECRET"),
        line(2500, "change", id="txtAmt", label="So tien", value=amount),
        line(3000, "click", tag="button", type="button", id="btnOk", label="OK", value=None),
        line(3500, "click", tag="td", type="", id="", label=f"Nguyen Van {customer[-1]} 0123456789", pos=4, ctl=False),
    ]


def build(*sessions, app="TouchPoint"):
    builder = TraceBuilder(app_title=app, trace_id="t-1")
    for index, lines in enumerate(sessions, start=1):
        builder.add_session(f"s-{index}", lines)
    return builder.build()


def text_of(trace) -> str:
    return json.dumps(trace, ensure_ascii=False)


def test_the_trace_conforms_to_its_schema():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(build(session("CUST001"), session("CUST002")), SCHEMA)


def test_a_password_is_dropped_and_counted_and_never_appears():
    trace = build(session("CUST001"), session("CUST002"))
    assert "TOPSECRET" not in text_of(trace) and "pw" not in trace["elements"]
    assert trace["masking"]["dropped_count"] == 2


def test_no_typed_character_and_no_long_number_survive():
    lines = session("CUST001") + [line(4000, "key", id="txtCust", label="Ma khach hang", keyclass="char", key="x", value="x")]
    trace = build(lines, session("CUST002"))
    kinds = [(e["kind"], e["key_class"]) for e in trace["sessions"][0]["events"] if e["kind"] == "key"]
    assert ("key", "char") in kinds and all(e["value"] is None for s in trace["sessions"] for e in s["events"] if e["kind"] == "key")
    assert "0123456789" not in text_of(trace)


def test_sensitive_field_keeps_its_class_and_not_its_value():
    trace = build(session("CUST001"), session("CUST002"))
    changes = [e for e in trace["sessions"][0]["events"] if e["kind"] == "change"]
    assert all(c["value"] is None and c["value_class"] for c in changes)  # unclassified is sensitive: only the class is kept


def test_text_of_a_non_control_that_differs_between_sessions_becomes_hash():
    trace = build(session("CUST001"), session("CUST002"))
    row = next(v for v in trace["elements"].values() if v["tag"] == "td")
    assert row["label"] == "#" and not row["is_control"]
    assert "Nguyen Van" not in text_of(trace)


def test_text_of_a_non_control_with_one_session_is_hash():
    trace = build(session("CUST001"))
    assert next(v for v in trace["elements"].values() if v["tag"] == "td")["label"] == "#"


def test_a_control_keeps_its_label_and_the_same_element_has_one_id_across_sessions():
    trace = build(session("CUST001"), session("CUST002"))
    ok = [k for k, v in trace["elements"].items() if v["label"] == "OK"]
    assert len(ok) == 1
    clicks = [e["el_id"] for s in trace["sessions"] for e in s["events"] if e["kind"] == "click" and e["el_id"] == ok[0]]
    assert len(clicks) == 2


def test_event_ids_are_stable_and_ordered_in_time():
    shuffled = list(reversed(session("CUST001")))
    first = build(shuffled)
    second = build(session("CUST001"))
    assert [e["eid"] for e in first["sessions"][0]["events"]] == [e["eid"] for e in second["sessions"][0]["events"]]
    assert [e["seq"] for e in first["sessions"][0]["events"]] == sorted(e["seq"] for e in first["sessions"][0]["events"])
    assert first["sessions"][0]["events"][0]["t_rel_ms"] == 0


def test_a_hidden_field_and_an_otp_field_are_dropped():
    lines = [line(1, "change", id="x", type="hidden", label="", value="abc"), line(2, "change", id="otpCode", label="Ma OTP", value="123456"),
             line(3, "click", tag="button", type="button", id="b", label="OK")]
    trace = build(lines)
    assert trace["masking"]["dropped_count"] == 2 and "123456" not in text_of(trace)
    assert len(trace["sessions"][0]["events"]) == 1


def test_old_page_lines_input_and_select_are_read_as_change():
    lines = [line(1, "input", id="a", label="Ghi chu", value="x"), line(2, "select", tag="select", type="select-one", id="s", label="Vai tro", value="GDV")]
    trace = build(lines)
    assert [e["kind"] for e in trace["sessions"][0]["events"]] == ["change", "change"]


# ---- task 4.14: the first value of a choice list, its options, and the value before a change ----

def snap(t, el_id, text, optv, options, label=None):
    return line(t, "snap", tag="select", type="select-one", id=el_id, label=label or el_id, value=text, optv=optv,
                opts=[{"v": v, "t": x} for v, x in options])


ROLES = [("gdv", "GDV"), ("ksv", "KSV")]


def test_a_choice_list_the_teller_never_touched_still_has_its_first_value_and_its_options():
    jsonschema = pytest.importorskip("jsonschema")
    trace = build([snap(1000, "currentRole", "KSV", "ksv", ROLES), line(3000, "click", tag="button", type="button", id="btnOk", label="OK")])
    jsonschema.validate(trace, SCHEMA)
    [(el_id, element)] = [(k, v) for k, v in trace["elements"].items() if v["tag"] == "select"]
    assert trace["sessions"][0]["initial"] == {el_id: {"value": "ksv", "text": "KSV"}}
    assert element["options"] == [{"value": "gdv", "text": "GDV"}, {"value": "ksv", "text": "KSV"}]
    assert [e["kind"] for e in trace["sessions"][0]["events"]] == ["click"]  # a snapshot is not an action


def test_the_first_value_is_the_last_one_seen_before_the_teller_touched_the_list():
    """A page script may set the default after onload: the first snapshot is not the value the teller saw."""
    touch = line(3000, "change", tag="select", type="select-one", id="currentRole", label="currentRole", value="GDV", before="KSV", optv="gdv")
    trace = build([snap(1000, "currentRole", "GDV", "gdv", ROLES), snap(2000, "currentRole", "KSV", "ksv", ROLES), touch])
    initial = next(iter(trace["sessions"][0]["initial"].values()))
    assert initial == {"value": "ksv", "text": "KSV"}
    change = next(e for e in trace["sessions"][0]["events"] if e["kind"] == "change")
    assert (change["value"], change["value_before"], change["option_value"]) == ("GDV", "KSV", "gdv")


def test_each_session_has_its_own_first_value():
    ok = line(3000, "click", tag="button", type="button", id="btnOk", label="OK")
    trace = build([snap(1000, "currentRole", "GDV", "gdv", ROLES), ok], [snap(1000, "currentRole", "KSV", "ksv", ROLES), ok])
    values = [next(iter(s["initial"].values()))["value"] for s in trace["sessions"]]
    assert values == ["gdv", "ksv"]


def test_a_list_that_is_not_ordinary_data_keeps_no_value_and_no_options():
    ok = line(3000, "click", tag="button", type="button", id="btnOk", label="OK")
    trace = build([snap(1000, "cboXyz", "Nguyen Van A", "nva", [("nva", "Nguyen Van A"), ("ntb", "Nguyen Thi B")], label="Khach Xyz"), ok])
    assert "Nguyen" not in text_of(trace) and "initial" not in trace["sessions"][0]
    assert all("options" not in element for element in trace["elements"].values())


def test_a_password_list_snapshot_is_dropped():
    trace = build([snap(1000, "selPassword", "x", "x", [("x", "x")], label="Mat khau"), line(2000, "click", tag="button", type="button", id="b", label="OK")])
    assert "selPassword" not in text_of(trace)


# ---- task 4.33: what the screen showed after an action goes into the trace as structure only (two versions: full in memory, masked here) ----

def screen_snapshot(t):
    return {"t": t, "after": {"kind": "click", "id": "btnOk", "label": "OK", "t": 3000}, "region": ["main"],
            "changed": [{"frame": "main", "kind": "table", "name": "grid"}, {"frame": "main", "kind": "message", "name": "x"},
                        {"frame": "main", "kind": "field", "name": "Tên khách hàng"}],
            "frames": [{"frame": "main", "title": "T",
                        "tables": [{"id": "grid", "headers": ["Số tài khoản", "Loại", "Số dư"],
                                    "rows": [["0123456789", "DDA", "5.000.000"], ["9876543210", "SAV", "7"]], "row_count": 2}],
                        "fields": [{"label": "Tên khách hàng", "value": "NGUYEN VAN A"}],
                        "messages": [{"level": "error", "text": "Khach hang NGUYEN VAN A khong ton tai"}]}]}


def test_the_trace_keeps_the_structure_of_what_the_screen_showed_and_none_of_its_values():
    jsonschema = pytest.importorskip("jsonschema")
    builder = TraceBuilder(app_title="TouchPoint", trace_id="t-1")
    builder.add_session("s-1", session("CUST001"))
    builder.add_screens("s-1", [screen_snapshot(5000)])
    trace = builder.build()
    jsonschema.validate(trace, SCHEMA)
    [screen] = trace["sessions"][0]["screens"]
    assert screen["region"] == ["main"]
    table = next(i for i in screen["items"] if i["kind"] == "table")
    assert table["headers"] == ["Số tài khoản", "Loại", "Số dư"] and table["row_count"] == 2
    assert table["col_classes"] == ["account_number", "plain", "amount"]
    message = next(i for i in screen["items"] if i["kind"] == "message")
    assert message == {"frame": "main", "kind": "message", "level": "error"}      # the text of a message can hold a name
    field = next(i for i in screen["items"] if i["kind"] == "field")
    assert field["value_class"] == "customer_name" and "value" not in field
    text = text_of(trace)
    for secret in ("0123456789", "9876543210", "5.000.000", "NGUYEN", "VAN A"):
        assert secret not in text


def test_the_screen_is_tied_to_the_action_it_followed():
    builder = TraceBuilder(app_title="TouchPoint", trace_id="t-1")
    builder.add_session("s-1", session("CUST001"))
    builder.add_screens("s-1", [screen_snapshot(5000)])
    trace = builder.build()
    ok = next(e for e in trace["sessions"][0]["events"] if e["kind"] == "click" and trace["elements"][e["el_id"]]["label"] == "OK")
    assert trace["sessions"][0]["screens"][0]["after_eid"] == ok["eid"]


# ---- task 4.36: a value typed after the screen showed it is a link between the two steps (found on this PC, only the link is kept) ----

def link_session():
    return [
        line(1000, "change", id="txtAcct", label="So tai khoan", value="0123456789"),
        line(1500, "click", tag="button", type="button", id="btnFind", label="TIM KIEM"),
        line(5000, "change", id="txtCopy", label="So tai khoan chuyen", value="9876543210"),
        line(5200, "change", id="txtNote", label="Ghi chu", value="ok"),
    ]


def link_screen(t=3000):
    return {"t": t, "after": {"kind": "click", "id": "btnFind", "label": "TIM KIEM", "t": 1500}, "region": ["main"],
            "changed": [{"frame": "main", "kind": "table", "name": "grid"}],
            "frames": [{"frame": "main", "title": "T", "fields": [], "messages": [],
                        "tables": [{"id": "grid", "headers": ["So TK", "Loai"], "rows": [["0123456789", "DDA"], ["9876543210", "SAV"]], "row_count": 2}]}]}


def test_a_value_typed_after_the_screen_showed_it_becomes_a_link_and_the_trace_keeps_no_value():
    jsonschema = pytest.importorskip("jsonschema")
    builder = TraceBuilder(app_title="TouchPoint", trace_id="t-1")
    builder.add_session("s-1", link_session())
    builder.add_screens("s-1", [link_screen()])
    trace = builder.build()
    jsonschema.validate(trace, SCHEMA)
    [link] = trace["sessions"][0]["links"]
    copy = next(e for e in trace["sessions"][0]["events"] if trace["elements"][e["el_id"]]["label"] == "So tai khoan chuyen")
    find = next(e for e in trace["sessions"][0]["events"] if e["kind"] == "click")
    assert link == {"eid": copy["eid"], "from_eid": find["eid"], "path": "grid.1.so_tk", "ambiguous": False}
    assert "9876543210" not in text_of(trace) and "0123456789" not in text_of(trace)


def test_a_short_value_or_a_value_not_on_the_screen_is_no_link():
    builder = TraceBuilder(app_title="TouchPoint", trace_id="t-1")
    builder.add_session("s-1", link_session())
    builder.add_screens("s-1", [link_screen()])
    links = builder.build()["sessions"][0]["links"]
    assert len(links) == 1                                   # "ok" is too short to mean anything; it is not on the screen anyway


def test_a_value_typed_before_the_screen_showed_it_is_no_link():
    builder = TraceBuilder(app_title="TouchPoint", trace_id="t-1")
    builder.add_session("s-1", link_session())
    builder.add_screens("s-1", [link_screen(t=9000)])        # the screen was read after the typing
    assert "links" not in builder.build()["sessions"][0]


def test_a_value_that_two_places_show_is_a_link_marked_ambiguous():
    builder = TraceBuilder(app_title="TouchPoint", trace_id="t-1")
    builder.add_session("s-1", link_session())
    twice = link_screen()
    twice["frames"][0]["tables"][0]["rows"].append(["9876543210", "DDA"])
    twice["frames"][0]["tables"][0]["row_count"] = 3
    builder.add_screens("s-1", [twice])
    [link] = builder.build()["sessions"][0]["links"]
    assert link["ambiguous"] is True
