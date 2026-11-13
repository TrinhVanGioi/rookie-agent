from rookie_agent.selectors import (
    Element,
    Step,
    parse_path_selector,
    parse_role_selector,
    path_selector,
    role_selector,
    selectors_for,
)

PATH = (Step("frame", -1), Step("root pane", 0), Step("panel", 1), Step("push button", 9))


def test_named_element_gets_role_then_path_selector():
    element = Element("push button", "Gửi duyệt", PATH, "Mock TPSS - Chuyển tiền")
    assert selectors_for(element) == [
        "role=push button[name='Gửi duyệt']",
        "path=frame/root pane[0]/panel[1]/push button[9]",
    ]


def test_unnamed_element_gets_only_a_path_selector():
    element = Element("push button", "  ", PATH, "Mock TPSS")
    assert selectors_for(element) == ["path=frame/root pane[0]/panel[1]/push button[9]"]


def test_selectors_never_contain_coordinates():
    element = Element("text", "Số tiền", PATH, "Mock TPSS")
    assert all(not part.startswith(("x=", "y=")) for selector in selectors_for(element) for part in selector.split("/"))


def test_role_selector_round_trips_names_with_quotes():
    selector = role_selector("push button", "Khách 'VIP' \\ khác")
    assert parse_role_selector(selector) == ("push button", "Khách 'VIP' \\ khác")
    assert parse_role_selector("path=frame/panel[0]") is None


def test_path_selector_round_trips():
    assert parse_path_selector(path_selector(PATH)) == PATH
    assert parse_path_selector("role=text[name='x']") is None
    assert parse_path_selector("path=frame/panel") is None


def test_key_identifies_the_place_in_the_tree():
    first = Element("text", "Số tiền", PATH, "A")
    second = Element("text", "Số tiền", PATH[:-1] + (Step("text", 5),), "A")
    assert first.key != second.key
