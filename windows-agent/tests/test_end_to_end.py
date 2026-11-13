"""Gate 1 and Gate 2 acceptance for the Java path, on the real Swing mock and a real server.

record 3 times  ->  upload  ->  learn  ->  sandbox  ->  tested  ->  approved  ->  run with a customer never recorded

The mock is driven through Java Access Bridge. The bridge does not report a press made
through its own API, so button presses are reported to the recorder by hand here (`press`).
That the bridge reports real presses is checked by `test_real_mouse_clicks_are_recorded`,
which moves the real mouse and therefore only runs with ROOKIE_REAL_INPUT=1.
"""

import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Java Access Bridge chỉ có trên Windows")
sys.path.insert(0, str(REPO / "server"))

SECRETS_TYPED: list[str] = []  # filled while recording; none of them may reach the server


@pytest.fixture(scope="module")
def bridge():
    from rookie_agent import sandbox
    from rookie_agent.jab import bridge as jab
    from rookie_agent.jab.session import JabSession

    try:
        sandbox.find_mock()
    except jab.BridgeError as error:
        pytest.skip(str(error))
    session = JabSession().open()
    yield session
    session.close()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import uvicorn

    from app.main import create_app
    from rookie_agent.server_client import ServerClient

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = uvicorn.Config(
        create_app(tmp_path_factory.mktemp("db") / "e2e.db"), host="127.0.0.1", port=port, log_level="warning"
    )
    instance = uvicorn.Server(config)
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not instance.started and time.monotonic() < deadline:
        time.sleep(0.05)
    client = ServerClient(f"http://127.0.0.1:{port}")
    assert client.health()["status"] == "ok"
    yield client
    instance.should_exit = True
    thread.join(timeout=5)


def mock_customers() -> list[dict]:
    """The mock's synthetic customers (same seed, same data on every start)."""
    from rookie_agent import sandbox

    java, _ = sandbox.find_mock()
    dump = subprocess.run(
        [str(java), "-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8", "-cp", str(REPO / "mock-java" / "out"), "mocktpss.Main", "--dump"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    customers = []
    for line in dump.splitlines():
        cif, name, id_number, phone, *accounts = line.split("|")
        customers.append({"cif": cif, "name": name, "id": id_number, "accounts": [a.split(":")[0] for a in accounts]})
    return customers


def wait_until_no_java_window(session) -> None:
    deadline = time.monotonic() + 15
    while session.windows() and time.monotonic() < deadline:
        time.sleep(0.2)


def open_tab(session, hwnd: int, index: int) -> None:
    session.with_element(hwnd, ["role=page tab list[name='Chức năng']"], lambda b, vm, c: b.select_child(vm, c, index))
    time.sleep(0.8)


def pending_transfers(session, hwnd: int) -> list[list[str]]:
    """Rows of the approval queue of the mock, read through the bridge."""
    open_tab(session, hwnd, 2)

    def read(bridge, vm, table):
        info = bridge.table_info(vm, table)
        rows = []
        for r in range(info.rowCount):
            row = []
            for c in range(info.columnCount):
                cell = bridge.table_cell(vm, info.accessibleTable, r, c)
                row.append(bridge.info(vm, cell.accessibleContext).name)
            rows.append(row)
        return rows

    return session.with_element(hwnd, ["role=table[name='Hàng chờ phê duyệt']"], read)


def record_one(session, hwnd: int, customer: dict, target_account: str, amount: str) -> dict:
    from rookie_agent.jab.driver import JabDriver
    from rookie_agent.jab.session import JabSession
    from rookie_agent.recorder import Recorder

    driver = JabDriver(session, hwnd)
    recorder = Recorder()
    session.attach(recorder)

    def settle():
        time.sleep(0.35)

    def type_into(name, value):
        driver.fill([f"role=text[name='{name}']"], value)
        # the user leaves the field: focus moves to another control
        other = "Tra cứu CIF" if name == "Số CIF hoặc CCCD" else None
        selector = "role=push button[name='Tra cứu CIF']" if other else "role=text[name='Nội dung']"
        session.with_element(hwnd, [selector], lambda b, vm, c: b.request_focus(vm, c))
        settle()

    def press(label):
        selector = f"role=push button[name='{label}']"
        element = session.with_element(hwnd, [selector], lambda b, vm, c: JabSession._element(b, vm, c))
        # a real mouse click gives the button the focus before it acts
        session.with_element(hwnd, [selector], lambda b, vm, c: b.request_focus(vm, c))
        time.sleep(0.2)
        driver.click([selector])
        settle()
        recorder.clicked(element)  # what the bridge reports for a real press

    SECRETS_TYPED.extend([customer["cif"], customer["accounts"][0], target_account, amount])
    type_into("Số CIF hoặc CCCD", customer["cif"])
    press("Tra cứu CIF")
    open_tab(session, hwnd, 1)
    type_into("Tài khoản chuyển", customer["accounts"][0])
    type_into("Tài khoản nhận", target_account)
    type_into("Số tiền", amount)
    driver.select(["role=combo box[name='Loại tiền']"], "USD")
    settle()
    press("Gửi duyệt")
    events = recorder.stop()
    session.detach()
    open_tab(session, hwnd, 0)  # back to the first screen for the next recording
    return {"session_id": recorder.session_id, "engine": "java", "events": events}


def test_record_learn_test_approve_run(bridge, server):
    from rookie_agent import sandbox
    from rookie_agent.controllers import RemoteController
    from rookie_agent.jab.driver import JabDriver
    from rookie_agent.runner import run_workflow
    from rookie_agent.server_client import ServerError

    customers = mock_customers()

    # 1. three recordings on one mock, three different customers
    process = sandbox.start_mock()
    try:
        hwnd, _ = bridge.wait_for_window("Mock TPSS", timeout=30)
        sandbox.login(bridge, hwnd, "maker")
        time.sleep(0.8)
        session_ids = []
        for i in range(3):
            recorded = record_one(bridge, hwnd, customers[i], customers[i + 10]["accounts"][0], str(1000 * (i + 1)))
            reply = server.post_session(recorded["session_id"], "java", recorded["events"])
            assert reply["event_count"] == len(recorded["events"]) == 8
            session_ids.append(recorded["session_id"])
    finally:
        process.kill()
        process.wait(timeout=10)
    wait_until_no_java_window(bridge)

    # nothing typed reached the server
    for session_id in session_ids:
        stored = json.dumps(server._call("GET", f"/sessions/{session_id}"), ensure_ascii=False)
        for secret in SECRETS_TYPED:
            assert secret not in stored, f"giá trị nhạy cảm lọt lên server: {secret}"

    # 2. learn
    learned = server.learn("chuyen-tien-cif", session_ids)
    workflow = learned["workflow"]
    assert learned["warnings"] == []
    assert [i["name"] for i in workflow["inputs"]] == ["so_cif_hoac_cccd", "tai_khoan_chuyen", "tai_khoan_nhan", "so_tien"]
    labels = [s["target"]["label"] for s in workflow["steps"]]
    assert labels == ["Số CIF hoặc CCCD", "Tra cứu CIF", "Chuyển tiền", "Tài khoản chuyển", "Tài khoản nhận", "Số tiền", "Loại tiền", "Gửi duyệt"]
    by_label = {s["target"]["label"]: s for s in workflow["steps"]}
    assert by_label["Gửi duyệt"]["risk"] == "money" and by_label["Gửi duyệt"]["mode"] == "approve"
    assert by_label["Loại tiền"]["value"] == "USD"

    # 3. a customer nobody recorded
    new = customers[5]
    inputs = {
        "so_cif_hoac_cccd": new["cif"],
        "tai_khoan_chuyen": new["accounts"][0],
        "tai_khoan_nhan": customers[15]["accounts"][0],
        "so_tien": "7000",
    }

    # 4. sandbox: a draft is not served, a pass allows `tested`, only then `approved`
    with pytest.raises(ServerError):
        server.approved_workflow("chuyen-tien-cif")
    with pytest.raises(ServerError):
        server.set_status("chuyen-tien-cif", 1, "tested")  # no passed run yet
    result = sandbox.sandbox_and_report(server, "chuyen-tien-cif", 1, inputs, session=bridge)
    assert result["status"] == "finished", result
    wait_until_no_java_window(bridge)
    server.set_status("chuyen-tien-cif", 1, "tested")
    server.set_status("chuyen-tien-cif", 1, "approved")
    approved = server.approved_workflow("chuyen-tien-cif")
    assert approved["workflow"]["status"] == "approved"

    # 5. run the approved workflow on a fresh mock; the money step waits for the GDV
    process = sandbox.start_mock()
    try:
        hwnd, _ = bridge.wait_for_window("Mock TPSS", timeout=30)
        sandbox.login(bridge, hwnd, "maker")
        time.sleep(0.8)
        events: list[dict] = []
        stop = threading.Event()
        controller = RemoteController(events.append, stop)
        outcome: dict = {}
        runner = threading.Thread(
            target=lambda: outcome.update(run_workflow(approved["workflow"], inputs, JabDriver(bridge, hwnd), controller, stop)),
            daemon=True,
        )
        runner.start()
        deadline = time.monotonic() + 30
        while controller.pending != "approve" and time.monotonic() < deadline:
            time.sleep(0.1)
        assert controller.pending == "approve"
        waiting = next(e for e in events if e["event"] == "waiting")
        assert (waiting["label"], waiting["risk"]) == ("Gửi duyệt", "money")

        assert controller.decide(True)
        runner.join(timeout=30)
        assert outcome["status"] == "finished", outcome
        rows = pending_transfers(bridge, hwnd)
        assert len(rows) == 1
        assert rows[0][1:4] == [inputs["tai_khoan_chuyen"], inputs["tai_khoan_nhan"], inputs["so_tien"]]
        assert inputs["so_tien"] not in json.dumps(events)  # values never go to the side panel
    finally:
        process.kill()
        process.wait(timeout=10)


@pytest.mark.skipif(not os.environ.get("ROOKIE_REAL_INPUT"), reason="di chuyển chuột thật; đặt ROOKIE_REAL_INPUT=1 để chạy")
def test_real_mouse_clicks_are_recorded(bridge):
    from ctypes import wintypes

    from rookie_agent import sandbox
    from rookie_agent.jab.driver import JabDriver
    from rookie_agent.recorder import Recorder

    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    process = sandbox.start_mock()
    try:
        hwnd, _ = bridge.wait_for_window("Mock TPSS", timeout=30)
        recorder = Recorder()
        bridge.attach(recorder)
        driver = JabDriver(bridge, hwnd)
        driver.fill(["role=text[name='Tên đăng nhập']"], "gdv01")
        driver.fill(["role=password text[name='Mật khẩu']"], "demo-only-1234")

        def real_click(selector):
            x, y = bridge.with_element(
                hwnd, [selector], lambda b, vm, c: (lambda i: (i.x + i.width // 2, i.y + i.height // 2))(b.info(vm, c))
            )
            old = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(old))
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.25)
            user32.SetCursorPos(x, y)
            time.sleep(0.15)
            user32.mouse_event(2, 0, 0, 0, 0)
            time.sleep(0.1)
            user32.mouse_event(4, 0, 0, 0, 0)
            time.sleep(0.2)
            user32.SetCursorPos(old.x, old.y)
            time.sleep(1.2)

        real_click("role=push button[name='Đăng nhập']")
        real_click("role=push button[name='Tra cứu CIF']")
        real_click("role=push button[name='Tra cứu CIF']")
        labels = [e["target"]["label"] for e in recorder.stop() if e["type"] == "click"]
        assert labels == ["Đăng nhập", "Tra cứu CIF", "Tra cứu CIF"]
    finally:
        bridge.detach()
        process.kill()
        process.wait(timeout=10)
