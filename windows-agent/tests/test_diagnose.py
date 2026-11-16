import struct
from pathlib import Path

from rookie_agent import diagnose
from rookie_agent.diagnose import JavaInstall, JavaUser


def fake_exe(path: Path, machine: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    head = bytearray(64)
    head[:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, 64)
    path.write_bytes(bytes(head) + b"PE\0\0" + struct.pack("<H", machine) + b"\0" * 20)
    return path


def test_pe_bits_reads_the_header(tmp_path):
    assert diagnose.pe_bits(fake_exe(tmp_path / "a.exe", 0x14C)) == 32
    assert diagnose.pe_bits(fake_exe(tmp_path / "b.exe", 0x8664)) == 64
    (tmp_path / "c.txt").write_text("not a program")
    assert diagnose.pe_bits(tmp_path / "c.txt") is None
    assert diagnose.pe_bits(tmp_path / "missing.exe") is None


def test_find_java_installs_reads_bitness_and_jabswitch(tmp_path):
    root64, root32 = tmp_path / "pf", tmp_path / "pf86"
    fake_exe(root64 / "jdk-21" / "bin" / "java.exe", 0x8664)
    fake_exe(root32 / "jre1.8.0_91" / "bin" / "java.exe", 0x14C)
    fake_exe(root32 / "jre1.8.0_91" / "bin" / "jabswitch.exe", 0x14C)
    installs = diagnose.find_java_installs([root64, root32, tmp_path / "none"])
    by_name = {i.name: i for i in installs}
    assert by_name["jdk-21"].bits == 64 and by_name["jdk-21"].jabswitch is None
    assert by_name["jre1.8.0_91"].bits == 32 and by_name["jre1.8.0_91"].jabswitch is not None
    assert by_name["jre1.8.0_91"].major == "8" and by_name["jdk-21"].major == "21"


def test_parse_tasklist_ignores_the_info_line():
    assert diagnose.parse_tasklist("INFO: No tasks are running which match the specified criteria.\n") == []
    text = '"iexplore.exe","5372","jvm.dll"\n"javaw.exe","77","jvm.dll"\n'
    assert diagnose.parse_tasklist(text) == [("iexplore.exe", 5372), ("javaw.exe", 77)]


def test_java_users_asks_the_bitness_of_each_process():
    users = diagnose.java_users(lambda: '"iexplore.exe","5372","jvm.dll"\n', lambda pid: 32)
    assert users == [JavaUser(5372, "iexplore.exe", 32)]


def test_wanted_bits_prefers_the_java_that_is_running_then_java_8():
    installs = [JavaInstall(Path("a"), "jdk-21", 64, None), JavaInstall(Path("b"), "jre1.8.0_91", 32, None)]
    assert diagnose.wanted_bits([JavaUser(1, "x", 64)], installs, 32) == 64
    assert diagnose.wanted_bits([], installs, 64) == 32
    assert diagnose.wanted_bits([], [], 64) == 64


def test_check_tells_the_teller_when_bitness_differs():
    installs = [JavaInstall(Path("b"), "jre1.8.0_91", 32, Path("j"))]
    report = diagnose.check(64, None, "Không tìm thấy", [], installs, [JavaUser(1, "iexplore.exe", 32)], False)
    assert report["summary"] == "bad" and report["wanted_bits"] == 32
    titles = [entry["title"] for entry in report["items"]]
    assert any("64-bit nhưng Java là 32-bit" in title for title in titles)
    assert any(entry["action"] == "switch_bits" for entry in report["items"])


def test_check_is_all_clear_when_everything_matches():
    installs = [JavaInstall(Path("b"), "jre1.8.0_91", 32, Path("j"))]
    report = diagnose.check(32, "C:/x/WindowsAccessBridge-32.dll", None, ["Mock"], installs, [JavaUser(1, "iexplore.exe", 32)], True)
    assert report["summary"] == "ok"


def test_check_offers_to_turn_the_bridge_on():
    report = diagnose.check(32, "dll", None, [], [], [JavaUser(1, "iexplore.exe", 32)], False)
    assert any(entry["action"] == "enable_bridge" for entry in report["items"])


def test_bridge_switched_on_reads_the_user_file(tmp_path):
    assert not diagnose.bridge_switched_on(tmp_path)
    (tmp_path / ".accessibility.properties").write_text("assistive_technologies=com.sun.java.accessibility.AccessBridge")
    assert diagnose.bridge_switched_on(tmp_path)


def test_the_browser_counts_before_an_editor_that_also_loads_java():
    users = [JavaUser(1, "nbcode64.exe", 64), JavaUser(2, "iexplore.exe", 32)]
    assert diagnose.wanted_bits(users, [], 64) == 32


def test_a_window_that_is_visible_proves_the_bridge_works():
    report = diagnose.check(32, "dll", None, ["Mock"], [], [JavaUser(1, "iexplore.exe", 32)], False)
    assert not any(entry["action"] == "enable_bridge" for entry in report["items"])


# ---- pages in Internet Explorer ------------------------------------------------------------------------------

def ie_info(frames=5, inputs=40, buttons=6, objects=0):
    return {"frames": [{"name": f"f{i}", "mode": 5, "inputs": 0} for i in range(frames)], "inputs": inputs, "buttons": buttons, "objects": objects}


def java_report():
    return diagnose.check(64, "dll", None, [], [], [], False)


def test_a_readable_ie_page_is_reported_in_plain_words():
    items = diagnose.ie_items([{"id": 1, "title": "TouchPoint"}], {1: ie_info()}, None)
    assert items[0]["level"] == "ok"
    assert "TouchPoint" in items[0]["title"] + items[0]["detail"] and "5 khung" in items[0]["detail"] and "40 ô nhập" in items[0]["detail"]


def test_a_page_with_no_input_field_asks_to_open_the_right_screen():
    items = diagnose.ie_items([{"id": 1, "title": "TouchPoint"}], {1: ie_info(inputs=0)}, None)
    assert items[0]["level"] == "warn" and "ô nhập" in items[0]["detail"]


def test_activex_or_applet_in_the_page_is_called_out():
    items = diagnose.ie_items([{"id": 1, "title": "T"}], {1: ie_info(objects=2)}, None)
    assert any("ActiveX" in entry["title"] or "applet" in entry["title"] for entry in items)


def test_no_ie_page_or_a_bridge_error_is_a_warning_not_a_crash():
    assert diagnose.ie_items([], {}, None)[0]["level"] == "warn"
    assert diagnose.ie_items([], {}, "PowerShell bị chặn")[0]["detail"].endswith("PowerShell bị chặn")


def test_when_the_ie_page_is_readable_and_there_is_no_java_the_java_findings_are_left_out():
    report = diagnose.with_ie(java_report(), diagnose.ie_items([{"id": 1, "title": "TouchPoint"}], {1: ie_info()}, None), readable=True)
    assert report["summary"] == "ok" and report["wanted_bits"] == 64
    assert all("Java" not in entry["title"] for entry in report["items"])


def test_java_findings_stay_when_java_is_in_use():
    users = [JavaUser(1, "iexplore.exe", 64)]
    java = diagnose.check(64, "dll", None, ["Mock"], [], users, True)
    report = diagnose.with_ie(java, diagnose.ie_items([{"id": 1, "title": "T"}], {1: ie_info()}, None), readable=True)
    assert any("Java" in entry["title"] for entry in report["items"]) and report["items"][-1]["title"].startswith("Đọc được")
