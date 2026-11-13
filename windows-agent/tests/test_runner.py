import copy
import json
import threading

import pytest

from rookie_agent.runner import AutoController, ElementNotFound, required_inputs, run_workflow

WORKFLOW = {
    "schema_version": 1,
    "engine": "java",
    "id": "tra-cif-lap-lenh",
    "version": 1,
    "status": "approved",
    "inputs": [
        {"name": "so_cif", "type": "string", "value_class": "cif_number"},
        {"name": "tai_khoan_nhan", "type": "string", "value_class": "account_number"},
        {"name": "so_tien", "type": "string", "value_class": "amount"},
        {"name": "loai_tien", "type": "string", "default": "VND"},
    ],
    "steps": [
        {"id": "s1", "action": "fill", "target": {"selectors": ["role=text[name='Số CIF']"]}, "value": "{so_cif}", "risk": "read", "mode": "auto"},
        {"id": "s2", "action": "click", "target": {"selectors": ["role=push button[name='Tra cứu CIF']"]}, "risk": "read", "mode": "auto"},
        {"id": "s3", "action": "read_value", "target": {"selectors": ["role=text[name='Tài khoản thanh toán']"]}, "save_as": "tai_khoan_chuyen", "risk": "read", "mode": "auto"},
        {"id": "s4", "action": "fill", "target": {"selectors": ["role=text[name='Tài khoản chuyển']"]}, "value": "{tai_khoan_chuyen}", "risk": "read", "mode": "review"},
        {"id": "s5", "action": "fill", "target": {"selectors": ["role=text[name='Tài khoản nhận']"]}, "value": "{tai_khoan_nhan}", "risk": "read", "mode": "auto"},
        {"id": "s6", "action": "fill", "target": {"selectors": ["role=text[name='Số tiền']"]}, "value": "{so_tien}", "risk": "read", "mode": "auto"},
        {"id": "s7", "action": "select", "target": {"selectors": ["role=combo box[name='Loại tiền']"]}, "value": "{loai_tien}", "risk": "read", "mode": "auto"},
        {"id": "s8", "action": "click", "target": {"selectors": ["role=push button[name='Gửi duyệt']"]}, "risk": "money", "mode": "approve"},
    ],
}
INPUTS = {"so_cif": "00103840", "tai_khoan_nhan": "002033605304", "so_tien": "5000000"}


class FakeDriver:
    def __init__(self, title="Mock TPSS - Chuyển tiền", missing=()):
        self.title = title
        self.missing = set(missing)
        self.calls: list[tuple] = []

    def _find(self, selectors):
        if selectors[0] in self.missing:
            raise ElementNotFound()

    def window_title(self):
        return self.title

    def exists(self, selectors):
        return selectors[0] not in self.missing

    def click(self, selectors):
        self._find(selectors)
        self.calls.append(("click", selectors[0]))

    def fill(self, selectors, value):
        self._find(selectors)
        self.calls.append(("fill", selectors[0], value))

    def select(self, selectors, value):
        self._find(selectors)
        self.calls.append(("select", selectors[0], value))

    def read_value(self, selectors):
        self._find(selectors)
        return "001076060577"


class Gdv:
    """A scripted GDV. Records when it was asked, relative to what the driver had done."""

    def __init__(self, driver, approve=True, review=True, on_approve=None):
        self.driver = driver
        self.answers = {"approve": approve, "review": review}
        self.on_approve = on_approve
        self.asked: list[tuple[str, str, int]] = []
        self.progress_log: list[tuple[str, str]] = []

    def approve(self, step, index, total):
        self.asked.append(("approve", step["id"], len(self.driver.calls)))
        if self.on_approve:
            self.on_approve()
        return self.answers["approve"]

    def review(self, step, index, total):
        self.asked.append(("review", step["id"], len(self.driver.calls)))
        return self.answers["review"]

    def progress(self, step_id, status, detail):
        self.progress_log.append((step_id, status))


def run(workflow=WORKFLOW, inputs=INPUTS, driver=None, gdv=None, **options):
    driver = driver or FakeDriver()
    gdv = gdv or Gdv(driver)
    options.setdefault("element_timeout", 0.3)
    options.setdefault("sleep", lambda seconds: None)
    return run_workflow(workflow, inputs, driver, gdv, **options), driver, gdv


def changed(**step_changes):
    workflow = copy.deepcopy(WORKFLOW)
    for step_id, fields in step_changes.items():
        next(step for step in workflow["steps"] if step["id"] == step_id).update(fields)
    return workflow


def test_runs_every_step_with_inputs_defaults_and_read_values():
    result, driver, gdv = run()
    assert result["status"] == "finished"
    assert [step["status"] for step in result["steps"]] == ["done"] * 8
    assert ("fill", "role=text[name='Tài khoản chuyển']", "001076060577") in driver.calls  # from read_value
    assert ("select", "role=combo box[name='Loại tiền']", "VND") in driver.calls  # default
    assert driver.calls[-1] == ("click", "role=push button[name='Gửi duyệt']")


def test_money_step_waits_for_approval_before_it_runs():
    result, driver, gdv = run()
    approvals = [entry for entry in gdv.asked if entry[0] == "approve"]
    assert approvals == [("approve", "s8", 6)]  # six actions done, the money click not yet
    assert ("s8", "waiting_approval") in gdv.progress_log


def test_rejected_approval_stops_before_the_step():
    driver = FakeDriver()
    result, driver, gdv = run(driver=driver, gdv=Gdv(driver, approve=False))
    assert result["status"] == "rejected"
    assert all(call[0] != "click" or "Gửi duyệt" not in call[1] for call in driver.calls)


def test_review_step_pauses_after_it_ran():
    driver = FakeDriver()
    result, driver, gdv = run(driver=driver, gdv=Gdv(driver, review=False))
    assert ("review", "s4", 3) in gdv.asked  # asked after the step was done
    assert result["status"] == "rejected"
    assert len(driver.calls) == 3


def test_emergency_stop_before_start_and_while_waiting_for_approval():
    stop = threading.Event()
    stop.set()
    result, driver, _ = run(stop=stop)
    assert result["status"] == "stopped" and driver.calls == []

    stop = threading.Event()
    driver = FakeDriver()
    result, driver, _ = run(driver=driver, gdv=Gdv(driver, on_approve=stop.set), stop=stop)
    assert result["status"] == "stopped"
    assert ("click", "role=push button[name='Gửi duyệt']") not in driver.calls


def test_missing_element_stops_and_asks_instead_of_guessing():
    driver = FakeDriver(missing={"role=push button[name='Tra cứu CIF']"})
    result, driver, _ = run(driver=driver)
    assert result["status"] == "needs_help"
    assert result["steps"][-1] == {"id": "s2", "status": "needs_help", "detail": "không tìm thấy phần tử"}
    assert len(driver.calls) == 1  # nothing after the missing element


@pytest.mark.parametrize(
    ("workflow", "reason"),
    [
        (changed(s8={"mode": "auto"}), "money"),
        (changed(s8={"mode": "review", "risk": "write"}), "write"),
        (dict(WORKFLOW, status="draft"), "chưa được duyệt"),
        (dict(WORKFLOW, engine="web"), "Java"),
        (changed(s2={"action": "goto"}), "chưa hỗ trợ"),
        (changed(s2={"risk": "danger"}), "không hợp lệ"),
        (dict(WORKFLOW, steps=[]), "không có bước"),
    ],
)
def test_workflows_that_break_a_rule_are_refused_before_any_action(workflow, reason):
    result, driver, _ = run(workflow=workflow)
    assert result["status"] == "refused" and reason in result["message"]
    assert driver.calls == []


def test_missing_inputs_are_named():
    result, driver, _ = run(inputs={"so_cif": "00103840"})
    assert result["status"] == "refused"
    assert "tai_khoan_nhan" in result["message"] and "so_tien" in result["message"]
    assert required_inputs(WORKFLOW) == ["so_cif", "tai_khoan_nhan", "so_tien"]


def test_money_step_is_refused_on_a_real_window():
    driver = FakeDriver(title="TPSS - Chuyển tiền")
    result, driver, gdv = run(driver=driver)
    assert result["status"] == "refused"
    assert gdv.asked == [("review", "s4", 3)]  # never even asked to approve
    assert ("click", "role=push button[name='Gửi duyệt']") not in driver.calls


def test_sandbox_runs_a_draft_on_the_mock_without_asking():
    controller = AutoController()
    result = run_workflow(dict(WORKFLOW, status="draft"), INPUTS, FakeDriver(), controller, sandbox=True, sleep=lambda s: None)
    assert result["status"] == "finished"
    assert ("s8", "auto_approved", "chế độ thử") in controller.log


def test_sandbox_refuses_a_window_that_is_not_the_mock():
    result = run_workflow(
        dict(WORKFLOW, status="draft"), INPUTS, FakeDriver(title="TPSS"), AutoController(), sandbox=True
    )
    assert result["status"] == "refused"


def test_results_never_contain_input_values():
    result, _, gdv = run()
    dumped = json.dumps([result, gdv.progress_log], ensure_ascii=False)
    for value in list(INPUTS.values()) + ["001076060577"]:
        assert value not in dumped


def test_driver_error_is_reported_as_failed():
    class Broken(FakeDriver):
        def fill(self, selectors, value):
            raise RuntimeError("không điền được ô Số CIF")

    result, _, _ = run(driver=Broken())
    assert result["status"] == "failed" and "s1" in result["message"]
