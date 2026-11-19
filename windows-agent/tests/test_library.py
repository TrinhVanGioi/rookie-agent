"""Kho luồng (cards of approved agents with a finished run), the n8n file of a card, how the Assistant runs a flow, and the recorded date format."""

import json



def node(step_id, risk, group, label="Xuất báo cáo", kind="xhr"):
    return {"id": f"{group}_1", "step_id": step_id, "kind": kind, "group": group, "group_label": label, "label": label, "frame": "top", "method": "POST",
            "url": "/api/export", "headers": "", "body": "from=⟦tu_ngay⟧", "links": {}, "risk": risk, "complete": True, "answer": "", "ms": 5, "shape": None,
            "unresolved": [], **({"file": {"ctype": "application/pdf", "size": 10, "guess": False}} if kind == "file" else {})}


def step(step_id, risk, label, tag="button"):
    return {"id": step_id, "action": "click", "risk": risk, "mode": "auto" if risk == "read" else "approve", "target": {"selectors": ["x"], "label": label, "tag": tag}}


def flow(title, status="approved", risk="read", api=None, steps=None, **more):
    return {"title": title, "steps": [], "inputs": [], "learned_at": "2026-11-19 09:00:00", "api": api if api is not None else [node("s1", risk, "g1")],
            "workflow": {"id": "w-" + title, "engine": "ie", "status": status, "version": 1,
                         "inputs": [{"name": "so_tai_khoan", "label": "Số tài khoản"}, {"name": "tu_ngay", "label": "Từ ngày"}],
                         "steps": steps or [step("s1", risk, "Xuất báo cáo")]}, **more}


def audit(core, *lines):
    with (core.store.home / "audit.jsonl").open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def ran(title, status="finished", mode="simulate", time="2026-11-19 10:00:00"):
    return {"time": time, "title": title, "mode": mode, "status": status, "seconds": 1, "decisions": [], "steps": []}


def test_the_library_lists_only_approved_agents_that_finished_a_real_run(tmp_path):
    core, _ = make_core(tmp_path)
    core.store.put("flows", [flow("Có đủ"), flow("Chưa duyệt", status="draft"), flow("Chưa chạy"), flow("Chạy lỗi"), flow("Chỉ chạy thử"), flow("Chỉ bản sao")])
    audit(core, ran("Có đủ", time="2026-11-18 08:00:00"), ran("Có đủ", time="2026-11-19 10:00:00"), ran("Có đủ", status="failed", time="2026-11-19 11:00:00"),
          ran("Chưa duyệt"), ran("Chạy lỗi", status="failed"), ran("Chạy lỗi", status="stopped"), ran("Chỉ chạy thử", mode="dry"), ran("Chỉ bản sao", mode="twin"))
    status, reply = core.dispatch("GET", "/api/library", {})
    assert status == 200 and [c["title"] for c in reply["flows"]] == ["Có đủ"]
    card = reply["flows"][0]
    assert card["last_run"] == "2026-11-19 10:00:00" and card["input_labels"] == ["Số tài khoản", "Từ ngày"]
    assert card["steps_n"] == 1 and card["calls_n"] == 1 and card["api_nodes"] and "Số tài khoản" in card["summary"]
    assert card["example"].startswith("có đủ") and "stk" in card["example"] and "từ ngày" in card["example"]


def test_a_flow_that_runs_again_after_a_new_approval_state_follows_the_workflow(tmp_path):
    core, _ = make_core(tmp_path)
    core.store.put("flows", [flow("A", status="draft")])
    audit(core, ran("A"))
    assert core.dispatch("GET", "/api/library", {})[1]["flows"] == []
    core.dispatch("POST", "/api/flow/approve", {"title": "A"})
    assert [c["title"] for c in core.dispatch("GET", "/api/library", {})[1]["flows"]] == ["A"]


def test_a_card_says_when_the_answer_is_a_file_and_what_it_may_do(tmp_path):
    core, _ = make_core(tmp_path)
    core.store.put("flows", [flow("Xuất file", api=[node("s1", "read", "g1", kind="file")])])
    audit(core, ran("Xuất file"))
    card = core.dispatch("GET", "/api/library", {})[1]["flows"][0]
    assert card["returns_file"] and "file" in card["summary"] and "Chỉ xem" in card["summary"]


def test_the_n8n_download_of_a_card_has_templates_and_no_value(tmp_path):
    core, _ = make_core(tmp_path)
    core.store.put("flows", [flow("Xuất báo cáo giao dịch")])
    audit(core, ran("Xuất báo cáo giao dịch"))
    status, document = core.dispatch("POST", "/api/library/n8n", {"title": "Xuất báo cáo giao dịch"})
    assert status == 200 and document["name"] == "Xuất báo cáo giao dịch"
    http = [n for n in document["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"]
    assert len(http) == 1 and http[0]["parameters"]["body"] == "from=⟦tu_ngay⟧" and "headers" not in json.dumps(http[0]["parameters"])
    assert core.dispatch("POST", "/api/library/n8n", {"title": "Không có"})[0] == 400


def assistant_mode(tmp_path, the_flow):
    tmp_path = tmp_path / str(abs(hash(json.dumps(the_flow, sort_keys=True))))
    tmp_path.mkdir()
    class Planning:
        def __init__(self, url):
            pass

        def plan_request(self, payload):
            return {"schema_version": 1, "method": "rule", "fallback_reason": None, "chain": [], "candidates": [{"ref": "w1", "confidence": 0.95, "slots": {}}]}

    core, _ = make_core(tmp_path, server_client=Planning)
    core.store.put("flows", [the_flow])
    seen = []
    core.run_start = lambda body, via=None: seen.append(body["mode"]) or {"started": True}
    shown = core.dispatch("POST", "/api/assistant/plan", {"text": "xuất báo cáo stk 0123456789 từ ngày 01/11/2026"})[1]
    assert shown["state"] == "ready", shown
    assert core.dispatch("POST", "/api/assistant/run", {"plan_id": shown["plan_id"], "window": "ie-tab:1"})[0] == 200
    return seen[0]


def test_a_read_flow_runs_by_request(tmp_path):
    assert assistant_mode(tmp_path, flow("Xuất báo cáo")) == "simulate"


def test_a_step_the_teller_confirmed_as_read_only_also_runs_by_request(tmp_path):
    odd = dict(api=[node("s1", "write", "g1", label="Khách hàng lạ")], steps=[step("s1", "write", "Khách hàng lạ")])
    assert assistant_mode(tmp_path, flow("Xuất báo cáo", **odd)) == "run"                                            # not confirmed yet: on the screen
    confirmed = flow("Xuất báo cáo", read_confirmed={"s1": {"at": "2026-11-19 09:00:00"}}, **odd)
    assert assistant_mode(tmp_path, confirmed) == "simulate"


def test_a_write_or_money_step_still_goes_to_the_screen_even_when_marked_confirmed(tmp_path):
    write = dict(api=[node("s1", "write", "g1", label="Lưu giao dịch")], steps=[step("s1", "write", "Lưu giao dịch")])
    assert assistant_mode(tmp_path, flow("Xuất báo cáo", read_confirmed={"s1": {"at": "x"}}, **write)) == "run"       # a rule names it a write
    money = dict(api=[node("s1", "money", "g1", label="Chuyển tiền")], steps=[step("s1", "money", "Chuyển tiền")])
    assert assistant_mode(tmp_path, flow("Xuất báo cáo", read_confirmed={"s1": {"at": "x"}}, **money)) == "run"


def test_a_flow_without_learned_calls_goes_to_the_screen(tmp_path):
    assert assistant_mode(tmp_path, flow("Xuất báo cáo", api=[])) == "run"


def test_learning_keeps_only_the_shape_of_a_recorded_date(tmp_path):
    core, _ = make_core(tmp_path)
    workflow = {"inputs": [{"name": "tu_ngay", "label": "Từ ngày"}, {"name": "so_tai_khoan", "label": "Số tài khoản"}]}
    events = [{"type": "input", "value": "31/01/2026", "target": {"label": "Từ ngày"}}, {"type": "input", "value": "0123456789", "target": {"label": "Số tài khoản"}},
              {"type": "input", "value": None, "target": {"label": "Từ ngày"}}]
    core.store.load = lambda session_id: {"events": events}
    formats = core._input_formats(workflow, ["a"])
    assert formats == {"tu_ngay": "dd/mm/yyyy"} and "2026" not in json.dumps(formats)


def make_core(*a, **k):
    from test_webui import make_core as real    # sibling module (tests/ has no package: the server has one named `tests`)
    return real(*a, **k)
