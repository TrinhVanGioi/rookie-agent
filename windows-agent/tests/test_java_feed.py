import json

import pytest

from rookie_agent.java_feed import FLAG_NAME, JavaFeed, agent_home, to_element
from rookie_agent.recorder import Recorder

WINDOW = "Mock TPSS - Chuyển tiền"


def record(**changes) -> dict:
    base = {
        "ts": 1,
        "kind": "action",
        "role": "push button",
        "name": "Gửi duyệt",
        "window": WINDOW,
        "secret": False,
        "path": [["frame", -1], ["root pane", 0], ["push button", 9]],
    }
    base.update(changes)
    return base


def line(**changes) -> bytes:
    return (json.dumps(record(**changes), ensure_ascii=False) + "\n").encode("utf-8")


@pytest.fixture
def recorder():
    ticks = iter(step * 0.01 for step in range(100_000))  # a clock that moves 10 ms per look: presses stay "at the same time"
    return Recorder(session_id="s-feed", clock=lambda: "2026-11-12T09:15:03.000Z", monotonic=lambda: next(ticks))


@pytest.fixture
def feed(recorder, tmp_path):
    feed = JavaFeed(recorder, home=tmp_path, poll_seconds=0.02)
    yield feed
    feed.stop()


def write(feed: JavaFeed, pid: str, data: bytes) -> None:
    feed.events_dir.mkdir(parents=True, exist_ok=True)
    with (feed.events_dir / f"{pid}.jsonl").open("ab") as handle:
        handle.write(data)


def test_a_line_names_the_component_the_way_the_bridge_recorder_does():
    element = to_element(record())
    assert (element.role, element.name, element.window) == ("push button", "Gửi duyệt", WINDOW)
    assert [(s.role, s.index) for s in element.path] == [("frame", -1), ("root pane", 0), ("push button", 9)]
    assert element.key == "path=frame/root pane[0]/push button[9]"


@pytest.mark.parametrize("broken", [{"path": []}, {"path": [["frame"]]}, {"path": "x"}, {"role": None, "path": None}])
def test_a_line_that_does_not_describe_a_component_is_dropped(broken):
    assert to_element({**record(), **broken}) is None
    assert to_element({}) is None


def test_the_flag_exists_exactly_while_recording(feed):
    feed.start("s-abc")
    assert (feed.flag.parent / FLAG_NAME).read_text(encoding="utf-8") == "s-abc"
    feed.stop()
    assert not feed.flag.exists()
    feed.stop()  # stopping twice is harmless


def test_actions_become_clicks_and_submits_without_any_value(feed, recorder, assert_valid_events):
    feed.start("s-abc")
    write(feed, "1234", line())
    write(feed, "1234", line(role="password text", name="Mật khẩu", secret=True, path=[["frame", -1], ["password text", 3]]))
    write(feed, "1234", line(role="text", name="Số tiền", path=[["frame", -1], ["text", 5]]))
    feed.stop()
    events = recorder.stop()
    assert_valid_events(events)
    assert [(e["type"], e["target"]["label"], e["target"]["tag"]) for e in events] == [
        ("click", "Gửi duyệt", "push button"),
        ("submit", "Mật khẩu", "password text"),
        ("submit", "Số tiền", "text"),
    ]
    assert all(e["value"] is None and e["value_class"] is None for e in events)
    assert all(e["engine"] == "java" and e["url"] == WINDOW for e in events)


def test_the_same_press_seen_twice_is_one_click(feed, recorder):
    feed.start("s-abc")
    element = to_element(record())
    recorder.clicked(element)  # what Java Access Bridge reported for a mouse press
    write(feed, "1234", line())  # what the helper reported for the same press
    feed.stop()
    assert len(recorder.stop()) == 1


def test_a_text_edit_still_pending_is_written_before_the_submit(feed, recorder):
    from rookie_agent.selectors import Element, Step

    field = Element("text", "Tên đăng nhập", (Step("frame", -1), Step("text", 1)), "Mock TPSS - Đăng nhập")
    recorder.text_changed(field, "gdv01", focused=True)
    feed.start("s-abc")
    write(feed, "1234", line(role="password text", name="Mật khẩu", window="Mock TPSS - Đăng nhập", path=[["frame", -1], ["password text", 3]]))
    feed.stop()
    assert [e["type"] for e in recorder.stop()] == ["input", "submit"]


def test_a_line_still_being_written_waits_for_its_end(feed, recorder):
    feed.start("s-abc")
    full = line()
    write(feed, "1234", full[:25])
    assert feed.poll() == 0
    write(feed, "1234", full[25:])
    assert feed.poll() == 1
    assert feed.poll() == 0  # nothing is read twice


def test_what_was_in_the_files_before_recording_belongs_to_an_earlier_recording(recorder, tmp_path):
    old = JavaFeed(recorder, home=tmp_path)
    write(old, "1234", line(name="Của lần trước"))
    feed = JavaFeed(recorder, home=tmp_path, poll_seconds=0.02)
    feed.start("s-new")
    write(feed, "1234", line(name="Của lần này"))
    feed.stop()
    assert [e["target"]["label"] for e in recorder.stop()] == ["Của lần này"]


def test_junk_and_other_kinds_of_line_are_ignored_and_several_applications_are_read(feed, recorder):
    feed.start("s-abc")
    write(feed, "1111", b"not json at all\n")
    write(feed, "1111", line(kind="focus"))
    write(feed, "1111", b'{"kind": "action"}\n')
    write(feed, "1111", b"\xff\xfe\n")
    write(feed, "2222", line(name="Từ ứng dụng thứ hai"))
    feed.stop()
    assert [e["target"]["label"] for e in recorder.stop()] == ["Từ ứng dụng thứ hai"]


def test_the_folder_comes_from_the_environment_when_it_is_set(monkeypatch, tmp_path):
    monkeypatch.setenv("ROOKIE_AGENT_HOME", str(tmp_path / "home"))
    assert agent_home() == tmp_path / "home"
    monkeypatch.delenv("ROOKIE_AGENT_HOME")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert agent_home() == tmp_path / "local" / "RookieAgent"
