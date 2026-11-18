from fastapi.testclient import TestClient

from app import assistant
from app.main import create_app


def entry(ref, title, steps=(), inputs=()):
    return {"ref": ref, "title": title, "risk_max": "read", "step_labels": list(steps), "keywords": [],
            "inputs": [{"name": n, "label": n, "class": c, "required": True} for n, c in inputs], "habit_runs": 0}


CATALOG = [entry("w1", "Vấn tin tài khoản", ["Tìm kiếm", "Số dư"], [("so_tai_khoan", "account_number")]),
           entry("w2", "Chuyển tiền", ["Nhập số tiền"], [("so_tien", "amount"), ("so_tai_khoan", "account_number")])]


def ask(text, slots=(), catalog=CATALOG):
    return {"schema_version": 1, "text": text, "slots": list(slots), "catalog": catalog}


def test_sentence_that_names_the_job_ranks_it_first_and_fits_the_account():
    reply = assistant.rule_plan(ask("tra số dư TK {s1}", [{"id": "s1", "class": "number"}]))
    top = reply["candidates"][0]
    assert top["ref"] == "w1" and top["confidence"] >= 0.8 and top["slots"] == {"s1": "so_tai_khoan"}


def test_unknown_sentence_scores_low():
    reply = assistant.rule_plan(ask("đặt vé máy bay"))
    assert not reply["candidates"] or reply["candidates"][0]["confidence"] < 0.5


def test_two_parameters_of_the_same_class_are_not_guessed():
    catalog = [entry("w1", "Chuyển khoản", [], [("tk_nguon", "account_number"), ("tk_dich", "account_number")])]
    reply = assistant.rule_plan(ask("chuyển khoản {s1}", [{"id": "s1", "class": "number"}], catalog))
    assert reply["candidates"][0]["slots"] == {}


def test_reply_with_unknown_ref_or_wrong_slot_class_is_refused():
    request = ask("x {s1}", [{"id": "s1", "class": "number"}])
    assert assistant.check_plan_reply(request, {"candidates": [{"ref": "w9", "confidence": 0.9}]})
    assert assistant.check_plan_reply(request, {"candidates": [{"ref": "w2", "confidence": 0.9, "slots": {"s1": "so_tien"}}]})
    assert not assistant.check_plan_reply(request, {"candidates": [{"ref": "w2", "confidence": 0.9, "slots": {"s1": "so_tai_khoan"}}]})
    assert assistant.check_plan_reply(request, {"candidates": [], "chain": [{"ref": "w1"}]})


class Liar:
    def plan_request(self, request):
        return {"candidates": [{"ref": "w9", "confidence": 1.0}], "chain": []}


class Other:
    def plan_request(self, request):
        return {"schema_version": 1, "candidates": [{"ref": "w2", "confidence": 0.95, "slots": {}}], "chain": [], "llm": {"calls": []}}


def test_bad_model_answer_falls_back_to_rules_and_disagreement_asks():
    request = ask("tra số dư")
    bad = assistant.plan(request, Liar())
    assert bad["method"] == "rule" and "không hợp lệ" in bad["fallback_reason"]
    split = assistant.plan(request, Other())
    assert {c["ref"] for c in split["candidates"]} >= {"w1", "w2"} and all(c["confidence"] < 0.8 for c in split["candidates"])


def test_endpoint_refuses_unmasked_and_answers_masked(tmp_path):
    with TestClient(create_app(tmp_path / "db")) as client:
        assert client.post("/assistant/plan", json=ask("tra 0123456789012")).status_code == 422
        ok = client.post("/assistant/plan", json=ask("tra số dư {s1}", [{"id": "s1", "class": "number"}]))
        assert ok.status_code == 200 and ok.json()["candidates"][0]["ref"] == "w1"
