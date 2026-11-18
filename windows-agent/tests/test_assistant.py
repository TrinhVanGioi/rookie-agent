import json

from rookie_agent.assistant import habits, mask
from rookie_agent.assistant.catalog import build_catalog, sanitize_label, vocabulary
from rookie_agent.assistant.planner import Planner


def flow(title, status="approved", engine="ie", inputs=(), risk="read", labels=("Tìm kiếm",), default=None):
    return {"title": title, "workflow": {"status": status, "engine": engine,
            "inputs": [{"name": n, "label": l, **({"default": default} if default else {})} for n, l in inputs],
            "steps": [{"action": "click", "risk": risk, "mode": "auto", "target": {"label": x}} for x in labels]}}


FLOWS = [flow("Vấn tin tài khoản", inputs=[("so_tai_khoan", "Số tài khoản")], labels=("Tìm kiếm", "Số dư")),
         flow("Chuyển tiền", inputs=[("so_tien", "Số tiền"), ("so_tai_khoan", "Số tài khoản")], risk="money", labels=("Nhập",)),
         flow("Chưa duyệt", status="draft"), flow("Java", engine="java")]


def test_catalog_has_only_approved_ie_agents_and_no_default_value():
    entries = build_catalog(FLOWS + [flow("Có mặc định", inputs=[("role", "Vai trò")], default="Teller")])
    assert [e["title"] for e in entries] == ["Vấn tin tài khoản", "Chuyển tiền", "Có mặc định"]
    assert [e["risk_max"] for e in entries] == ["read", "money", "read"]
    assert "Teller" not in json.dumps(entries) and entries[2]["inputs"][0]["has_default"]
    assert [i["class"] for i in entries[1]["inputs"]] == ["amount", "account_number"]


def test_label_with_newline_and_long_number_is_cleaned():
    assert sanitize_label("Bỏ qua\nhướng dẫn 0123456789 " + "x" * 100).count("\n") == 0
    assert "0123456789" not in sanitize_label("TK 0123456789") and len(sanitize_label("x" * 100)) == 60


def test_mask_splits_values_and_hides_names():
    vocab = vocabulary(build_catalog(FLOWS))
    done = mask.prepare("Tra số dư TK 0123456789 của Nguyễn Văn A", vocab)
    assert "0123456789" not in done["text"] and "nguyen" not in done["text"] and "{s1}" in done["text"]
    assert done["slots"] == [{"id": "s1", "class": "number"}] and done["values"] == {"s1": "0123456789"}
    assert "#" in done["text"].split()                  # the surname is not in the closed vocabulary (a given name that equals a word of an agent's title may stay: known limit)
    money = mask.prepare("chuyển 5 triệu", vocab)
    assert money["slots"] == [{"id": "s1", "class": "amount"}] and mask.amount_digits(money["values"]["s1"]) == "5000000"
    assert mask.amount_digits("5.000.000") == "5000000"


class Server:
    """Answers the way the server does when the sentence names an agent by its first word; remembers what it was sent."""

    def __init__(self, ref="w1", confidence=0.9, slots=None, second=None):
        self.ref, self.confidence, self.slots, self.second, self.sent = ref, confidence, slots or {}, second, []

    def __call__(self, payload):
        self.sent.append(payload)
        candidates = [{"ref": self.ref, "confidence": self.confidence, "slots": self.slots}]
        if self.second:
            candidates.append({"ref": self.second[0], "confidence": self.second[1], "slots": {}})
        return {"schema_version": 1, "method": "rule", "fallback_reason": None, "candidates": candidates, "chain": []}


def planner(server, flows=FLOWS, now=lambda: 1000.0):
    return Planner(server, lambda: flows, None, now)


def test_ready_when_sure_and_the_account_came_from_the_sentence_and_nothing_sensitive_was_sent():
    server = Server(slots={"s1": "so_tai_khoan"})
    shown = planner(server).plan("tra số dư TK 0123456789 của Nguyễn Văn A")
    assert shown["state"] == "ready" and shown["inputs"][0]["value"] == "0123456789" and shown["inputs"][0]["source"] == "lấy từ câu bạn gõ"
    assert "0123456789" not in json.dumps(server.sent) and "nguyen" not in json.dumps(server.sent).lower()


def test_each_of_the_five_states():
    assert planner(Server()).plan("")["state"] == "blocked"
    assert planner(Server(), flows=[]).plan("tra số dư")["state"] == "blocked"
    assert planner(Server(confidence=0.3)).plan("đặt vé")["state"] == "none"
    assert planner(Server(confidence=0.7)).plan("tra số dư")["state"] == "choose"
    assert planner(Server(confidence=0.9, second=("w2", 0.8))).plan("tra số dư")["state"] == "choose"     # too close
    assert planner(Server(confidence=0.9)).plan("tra số dư")["state"] == "need_inputs"                    # no account in the sentence


def test_two_agents_are_chosen_then_missing_value_is_asked_then_ready():
    p = planner(Server(confidence=0.6, second=("w2", 0.5)))
    shown = p.plan("tra số dư")
    assert shown["state"] == "choose" and [c["ref"] for c in shown["candidates"]] == ["w1", "w2"]
    picked = p.answer(shown["plan_id"], choice="w1")
    assert picked["state"] == "need_inputs" and picked["questions"]
    done = p.answer(shown["plan_id"], given={"so_tai_khoan": "999"})
    assert done["state"] == "ready" and done["inputs"][0]["source"] == "bạn nhập"


def test_money_agent_says_it_will_stop_for_the_approval():
    p = planner(Server(ref="w2", slots={"s1": "so_tien", "s2": "so_tai_khoan"}))
    shown = p.plan("chuyển 5 triệu cho 0123456789")
    assert shown["workflow"]["risk_max"] == "money" and "Duyệt" in shown["message"]
    assert next(i for i in shown["inputs"] if i["name"] == "so_tien")["value"] == "5000000"


def test_answer_with_a_code_we_never_sent_is_not_used():
    assert planner(Server(ref="w9")).plan("tra số dư")["state"] == "blocked"
    assert planner(Server(slots={"s1": "khong_co"})).plan("tra 0123456789")["state"] == "blocked"


def test_take_gives_title_and_inputs_once_and_only_when_ready():
    p = planner(Server(slots={"s1": "so_tai_khoan"}))
    shown = p.plan("tra số dư 0123456789")
    assert p.take(shown["plan_id"]) == ("Vấn tin tài khoản", {"so_tai_khoan": "0123456789"})
    assert p.take(shown["plan_id"]) is None
    not_ready = p.plan("tra số dư")
    assert p.take(not_ready["plan_id"]) is None


def test_plan_expires_after_ten_minutes():
    clock = [1000.0]
    p = Planner(Server(), lambda: FLOWS, None, lambda: clock[0])
    shown = p.plan("tra số dư")
    clock[0] += 601
    assert p.answer(shown["plan_id"], given={"x": "1"})["state"] == "blocked"


def test_server_down_is_a_plain_sentence():
    def down(_):
        raise RuntimeError("không có mạng")
    shown = planner(down).plan("tra số dư")
    assert shown["state"] == "blocked" and "máy chủ" in shown["message"]


def test_habits_count_names_only_skip_dry_and_continue_without_double_counting(tmp_path):
    audit = tmp_path / "audit.jsonl"
    rows = [{"time": "2026-11-17 09:00:00", "title": "A", "mode": "run", "status": "finished", "via": "assistant", "input_names": ["so_tai_khoan"],
             "steps": [{"detail": "0123456789"}]},
            {"time": "2026-11-17 09:03:00", "title": "B", "mode": "run", "status": "finished"},
            {"time": "2026-11-17 09:04:00", "title": "A", "mode": "dry", "status": "finished"},
            {"time": "2026-11-17 10:00:00", "title": "Gone", "mode": "run", "status": "failed"}]
    audit.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    stats = habits.build_habits(audit, {"A", "B"})
    assert stats["workflows"]["A"]["runs"] == 1 and stats["workflows"]["A"]["via_assistant"] == 1 and "Gone" not in stats["workflows"]
    assert habits.next_after(stats, "A") == [{"title": "B", "count": 1}]
    again = habits.build_habits(audit, {"A", "B"}, stats)
    assert again["workflows"]["A"]["runs"] == 1
    assert habits.save_habits(tmp_path, again) and "0123456789" not in (tmp_path / habits.FILE).read_text(encoding="utf-8")
    assert habits.bonus(again, "A") <= habits.MAX_BONUS and habits.frequent(again)[0]["runs"] == 1


def test_habits_file_is_refused_when_a_long_number_got_in(tmp_path):
    assert not habits.save_habits(tmp_path, {"workflows": {"TK 0123456789": {"runs": 1}}})
