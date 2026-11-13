import json

from rookie_agent.jab.session import Node
from rookie_agent.wireframe import wireframe

SHOWING = "enabled,visible,showing"


def node(role, name, x, y, w, h, states=SHOWING, children=()):
    return Node(role, name, states, "", x, y, w, h, list(children))


def screen():
    return node("frame", "Mock TPSS - Chuyển tiền", 100, 50, 800, 600, children=[
        node("panel", "", 100, 50, 800, 600, children=[
            node("label", "Khách hàng: Nguyễn Văn An", 110, 60, 200, 20),
            node("text", "Số tiền", 220, 100, 140, 24),
            node("password text", "Mật khẩu", 220, 130, 140, 24),
            node("push button", "Gửi duyệt", 220, 200, 90, 28),
            node("table", "Hàng chờ phê duyệt", 110, 300, 600, 200),
            node("push button", "Ẩn", 0, 0, 10, 10, states="enabled"),      # not showing
            node("push button", "Không kích thước", 5, 5, 0, 0),             # zero size
            node("scroll bar", "", 700, 300, 15, 200),                       # not drawn
        ]),
    ])


def test_boxes_are_relative_to_the_window_and_only_visible_known_controls_are_drawn():
    drawing = wireframe(screen())
    assert (drawing["title"], drawing["width"], drawing["height"]) == ("Mock TPSS - Chuyển tiền", 800, 600)
    assert [(i["kind"], i["name"], i["x"], i["y"], i["w"], i["h"]) for i in drawing["items"]] == [
        ("label", None, 10, 10, 200, 20),
        ("field", "Số tiền", 120, 50, 140, 24),
        ("secret", "Mật khẩu", 120, 80, 140, 24),
        ("button", "Gửi duyệt", 120, 150, 90, 28),
        ("table", "Hàng chờ phê duyệt", 10, 250, 600, 200),
    ]


def test_no_value_or_label_text_is_ever_in_the_drawing():
    dumped = json.dumps(wireframe(screen()), ensure_ascii=False)
    assert "Nguyễn Văn An" not in dumped
    assert "Khách hàng:" not in dumped


def test_a_huge_screen_is_capped():
    many = node("frame", "x", 0, 0, 100, 100, children=[node("push button", f"n{i}", 0, 0, 5, 5) for i in range(1000)])
    assert len(wireframe(many)["items"]) == 400
