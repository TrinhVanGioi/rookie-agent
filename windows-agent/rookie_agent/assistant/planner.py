"""From one sentence to a card «Sẽ chạy» (design 3). Decides the state; never runs anything and never approves anything."""

from __future__ import annotations

import time
import uuid
from datetime import date
from typing import Any

from rookie_agent.assistant import mask, slots
from rookie_agent.assistant.catalog import build_catalog, for_server, vocabulary

RUN_AT = 0.80
ASK_AT = 0.50
MARGIN = 0.15
PLAN_LIFE_SECONDS = 600
RISK_WORDS = {"read": "chỉ đọc", "write": "có bước ghi", "money": "có bước tiền"}


class Planner:
    """`ask(payload) -> reply` is the server (or a fake in tests). Sentences and values stay in `self.plans`, in memory, for 10 minutes."""

    def __init__(self, ask, flows, habit_runs=None, now=time.time) -> None:
        self._ask, self._flows, self._habit_runs, self._now = ask, flows, habit_runs, now
        self.plans: dict[str, dict[str, Any]] = {}

    def plan(self, text: str) -> dict[str, Any]:
        self._forget_old()
        text = (text or "").strip()
        if not text:
            return self._state("blocked", "Bạn gõ việc cần làm vào ô trên.")
        catalog = build_catalog(self._flows(), self._habit_runs() if self._habit_runs else None)
        if not catalog:
            return self._state("blocked", "Chưa có agent nào đã duyệt. Hãy Ghi, Học rồi Duyệt agent trước.")
        prepared = mask.prepare(text, vocabulary(catalog))
        request = {"schema_version": 1, "text": prepared["text"], "slots": prepared["slots"], "catalog": for_server(catalog)}
        try:
            reply = self._ask(request)
        except Exception as error:   # noqa: BLE001  the person gets a sentence, never a stack
            return self._state("blocked", f"Chưa hỏi được máy chủ: {error}. Mở mục Kết nối rồi thử lại.")
        problems = self._check(reply, catalog, prepared["slots"])
        if problems:
            return self._state("blocked", "Máy chủ trả lời không đúng dạng nên Trợ lý không dùng. Thử lại sau.")
        plan_id = uuid.uuid4().hex[:12]
        self.plans[plan_id] = {"at": self._now(), "catalog": catalog, "reply": reply, "values": prepared["values"], "slots": prepared["slots"],
                               "choice": None, "given": {}, "texts": [text], "local": {}}
        return self._shape(plan_id)

    def answer(self, plan_id: str, choice: str | None = None, given: dict[str, Any] | None = None, text: str | None = None) -> dict[str, Any]:
        """A choice, values typed in the card, or a line typed in the chat (`text`: read here, on this PC; `understood` says whether it
        filled anything, so the chat can treat it as a new request when it did not)."""
        self._forget_old()
        plan = self.plans.get(plan_id)
        if plan is None:
            return self._state("blocked", "Câu hỏi này đã hết hạn. Hãy hỏi lại.")
        if choice is not None:
            if choice not in {e["ref"] for e in plan["catalog"]}:
                return self._state("blocked", "Lựa chọn không có trong danh sách.")
            plan["choice"] = choice
        for name, value in (given or {}).items():
            if str(value).strip():
                plan["given"][str(name)] = str(value).strip()
        if text and text.strip():
            plan["texts"].append(text.strip()[: mask.MAX_TEXT])
        shown = self._shape(plan_id)
        if text and text.strip():
            shown["understood"] = bool(plan.get("understood"))
        return shown

    def take(self, plan_id: str) -> tuple[str, dict[str, str]] | None:
        """The one thing a run needs: the title of the agent and its inputs. A plan is used once; None when it is not `ready`."""
        shown = self._shape(plan_id) if plan_id in self.plans else None
        if shown is None or shown["state"] != "ready":
            return None
        plan = self.plans.pop(plan_id)
        entry = self._entry(plan)
        return entry["_flow_title"], {i["name"]: i["value"] for i in shown["inputs"] if i["value"] != ""}

    def method_of(self, plan_id: str) -> dict[str, Any]:
        plan = self.plans.get(plan_id)
        return {"method": (plan or {}).get("reply", {}).get("method", "rule")}

    # ---- internals -----------------------------------------------------------------------------

    def _forget_old(self) -> None:
        for plan_id in [p for p, v in self.plans.items() if self._now() - v["at"] > PLAN_LIFE_SECONDS]:
            del self.plans[plan_id]

    @staticmethod
    def _check(reply: Any, catalog: list[dict[str, Any]], slots: list[dict[str, str]]) -> list[str]:
        """The second check of what came back (the first is on the server): codes, slots and parameter names must be ours."""
        if not isinstance(reply, dict) or not isinstance(reply.get("candidates"), list) or reply.get("chain"):
            return ["shape"]
        entries = {e["ref"]: {i["name"] for i in e["inputs"]} for e in catalog}
        ids = {s["id"] for s in slots}
        for item in reply["candidates"][:3]:
            if not isinstance(item, dict) or item.get("ref") not in entries or not isinstance(item.get("confidence"), (int, float)):
                return ["candidate"]
            for slot_id, name in (item.get("slots") or {}).items():
                if slot_id not in ids or name not in entries[item["ref"]]:
                    return ["slot"]
        return []

    def _entry(self, plan: dict[str, Any]) -> dict[str, Any]:
        ref = plan["choice"] or plan["reply"]["candidates"][0]["ref"]
        return next(e for e in plan["catalog"] if e["ref"] == ref)

    def _state(self, state: str, message: str, **more: Any) -> dict[str, Any]:
        return {"plan_id": None, "state": state, "message": message, "candidates": [], "workflow": None, "inputs": [], "questions": [], "method": None, **more}

    def _shape(self, plan_id: str) -> dict[str, Any]:
        plan = self.plans[plan_id]
        reply, catalog = plan["reply"], plan["catalog"]
        by_ref = {e["ref"]: e for e in catalog}
        candidates = [{"ref": c["ref"], "title": by_ref[c["ref"]]["title"], "confidence": c["confidence"], "risk_max": by_ref[c["ref"]]["risk_max"]}
                      for c in reply["candidates"][:3]]
        common = {"plan_id": plan_id, "candidates": candidates, "method": reply.get("method", "rule"), "fallback_reason": reply.get("fallback_reason")}
        if plan["choice"] is None:
            if not candidates or candidates[0]["confidence"] < ASK_AT:
                return self._state("none", "Chưa có agent cho việc này. Bạn có thể Ghi rồi Học một agent mới.", **common)
            second = candidates[1]["confidence"] if len(candidates) > 1 else 0.0
            if candidates[0]["confidence"] < RUN_AT or candidates[0]["confidence"] - second < MARGIN:
                return self._state("choose", "Bạn muốn làm việc nào?", **common)
        entry = self._entry(plan)
        return self._filled(plan, entry, common)

    def _today(self) -> date:
        return date.fromtimestamp(self._now())

    def _local(self, plan: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
        """Fill what the sentence (and the lines typed after it) holds, on this PC. {values, asks, used}; each line is read once."""
        state = plan["local"].setdefault(entry["ref"], {"values": {}, "asks": {}, "used": set(), "done": 0})
        while state["done"] < len(plan["texts"]):
            text = plan["texts"][state["done"]]
            first = state["done"] == 0
            state["done"] += 1
            empty = [i for i in entry["_local_inputs"] if i["name"] not in state["values"] and i["name"] not in plan["given"]]
            result = slots.fill(slots.extract(text, self._today()), empty, self._today())
            state["values"].update(result["values"])
            state["used"] |= result["used"]
            state["asks"] = result["asks"]
            understood = bool(result["values"])
            missing = [i for i in empty if i["name"] not in state["values"]]
            if not first and not understood and len(missing) == 1 and slots.input_kind(missing[0]) is None and "\n" not in text:
                state["values"][missing[0]["name"]] = text            # a plain answer to a plain question
                understood = True
            if not first:
                plan["understood"] = understood
        return state

    def _filled(self, plan: dict[str, Any], entry: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
        chosen = next((c for c in plan["reply"]["candidates"] if c["ref"] == entry["ref"]), {"slots": {}})
        local = self._local(plan, entry)
        by_name = {i["name"]: i for i in entry["_local_inputs"]}
        kinds = {name: slots.input_kind(item) for name, item in by_name.items()}
        from_text = {name: plan["values"].get(slot_id, "") for slot_id, name in (chosen.get("slots") or {}).items()}
        for slot_id, name in (chosen.get("slots") or {}).items():
            kind = next((s["class"] for s in plan["slots"] if s["id"] == slot_id), "")
            if kind == "amount":
                from_text[name] = mask.amount_digits(plan["values"].get(slot_id, ""))
        from_text = {n: v for n, v in from_text.items() if not str(kinds.get(n) or "").startswith("date")}   # a number never goes into a date
        used_slots = set((chosen.get("slots") or {}).keys())
        inputs, questions = [], []
        for item in entry["inputs"]:
            name = item["name"]
            if name in plan["given"]:
                value, source = plan["given"][name], "bạn nhập"
            elif from_text.get(name):
                value, source = from_text[name], "lấy từ câu bạn gõ"
            elif local["values"].get(name):
                value, source = local["values"][name], "lấy từ câu bạn gõ"
            elif item["has_default"]:
                value, source = "", "giá trị mặc định"
            else:
                value, source = "", ""
            if value == "" and item["required"]:
                ask = local["asks"].get(name)
                questions.append(f"Cần nhập «{item['label']}»." if ask is None else ask)    # "" = asked together with another input
            kind = kinds.get(name) or ""
            hint = ""
            if kind.startswith("date"):
                hint = by_name[name].get("format") or ("yyyy-mm-dd" if by_name[name].get("type") == "date" else slots.DEFAULT_FORMAT)
            inputs.append({"name": name, "label": item["label"], "value": value, "required": item["required"], "source": source, "kind": kind, "hint": hint})
        questions = [q for q in questions if q]
        needs = any(i["value"] == "" and i["required"] for i in inputs)

        def kept(slot: dict[str, str]) -> bool:
            value = plan["values"].get(slot["id"], "")
            return (mask.amount_digits(value) if slot["class"] == "amount" else value) in local["used"]

        leftover = [s for s in plan["slots"] if s["id"] not in used_slots and not kept(s)]
        if leftover and not plan["given"]:
            questions.append("Có giá trị trong câu chưa biết điền vào ô nào. Bạn điền giúp vào các ô bên dưới.")
            needs = True
        workflow = {"title": entry["title"], "risk_max": entry["risk_max"], "steps": entry["step_labels"]}
        if needs:
            return self._state("need_inputs", "Cần thêm thông tin trước khi chạy.", workflow=workflow, inputs=inputs, questions=questions, **common)
        words = RISK_WORDS.get(entry["risk_max"], "")
        note = "" if entry["risk_max"] == "read" else " Có bước ghi hoặc tiền: sẽ dừng chờ bạn Duyệt."
        return self._state("ready", f"Sẽ chạy «{entry['title']}» ({words}).{note}", workflow=workflow, inputs=inputs, **common)
