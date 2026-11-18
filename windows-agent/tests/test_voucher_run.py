"""Tasks 6.8 and 6.9: a payment order is read, the teller confirms each field, and an approved flow runs with them on the mock."""

import base64
import json

from rookie_agent.voucher.reader import SAMPLES
from test_webui import run_core, wait_for


def picture(name):
    return base64.b64encode((SAMPLES / f"{name}.png").read_bytes()).decode()


def test_amounts_that_differ_cannot_be_confirmed_and_nothing_can_run_before_the_confirmation(tmp_path):
    core, bridge = run_core(tmp_path)
    read = core.dispatch("POST", "/api/voucher/read", {"data": picture("unc-05")})[1]
    assert read["ready"] is False
    status, reply = core.dispatch("POST", "/api/voucher/confirm", {"id": read["id"], "fields": read["fields"]})
    assert status == 400 and "không khớp" in reply["error"]
    status, reply = core.dispatch("POST", "/api/voucher/run", {"id": read["id"], "title": "Chuyen tien", "window": "ie-tab:1", "mapping": {"acct": "so_tai_khoan_nhan"}})
    assert status == 400 and bridge.done == []


def test_a_confirmed_voucher_runs_the_approved_flow_and_the_money_step_waits_for_a_person(tmp_path):
    core, bridge = run_core(tmp_path)
    read = core.dispatch("POST", "/api/voucher/read", {"data": picture("unc-01")})[1]
    confirmed = core.dispatch("POST", "/api/voucher/confirm", {"id": read["id"], "fields": read["fields"]})[1]
    assert [f["title"] for f in confirmed["flows"]] == ["Chuyen tien"]
    assert core.dispatch("POST", "/api/voucher/run", {"id": read["id"], "title": "Chuyen tien", "window": "ie-tab:1",
                                                      "mapping": {"acct": "so_tai_khoan_nhan"}})[0] == 200
    waiting = wait_for(core, "waiting_approval")
    assert waiting["ask"]["risk"] == "money" and bridge.done[0] == ("fill", "frame=top|id=a", "9876543210")
    assert not any(op == "click" for op, _, _ in bridge.done)
    core.dispatch("POST", "/api/run/stop", {})
    wait_for(core, "stopped")
    core._run["thread"].join(5)
    audit = (core.store.home / "audit.jsonl").read_text(encoding="utf-8")
    lines = [json.loads(line) for line in audit.splitlines()]
    assert any(line["mode"] == "voucher" and "so_tien" in line["fields"] and line["by"] for line in lines)
    assert any(line.get("via") == "voucher" for line in lines)
    for value in ("9876543210", "5.000.000", "NGUYEN VAN MAU", "CONG TY MAU A"):
        assert value not in audit                                   # names and confidence only, never a value or the picture


def test_a_corrected_field_is_kept_and_listed_as_corrected(tmp_path):
    core, _ = run_core(tmp_path)
    read = core.dispatch("POST", "/api/voucher/read", {"data": picture("unc-05")})[1]
    fields = [{**f, "value": "Bảy triệu năm trăm nghìn đồng"} if f["name"] == "so_tien_bang_chu" else f for f in read["fields"]]
    assert core.dispatch("POST", "/api/voucher/confirm", {"id": read["id"], "fields": fields})[0] == 200
    line = json.loads((core.store.home / "audit.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert line["corrected"] == ["so_tien_bang_chu"]


def test_the_page_has_the_voucher_box_with_a_confirmation_before_the_run():
    from pathlib import Path

    page = (Path(__file__).resolve().parents[1] / "rookie_agent" / "webui" / "index.html").read_text(encoding="utf-8")
    for needle in ('id="vcFile"', 'id="vcConfirm"', 'id="vcRunBox" hidden', "Tôi đã soát từng trường", "/api/voucher/run"):
        assert needle in page, needle
