"""Edit a flow on the admin page (task 10.4; docs/design.md 13). Pure: the caller stores the result as a new draft version.

A canvas node is a group of API calls (`api[].group`) when the flow has API nodes, otherwise a workflow step. Operations, in order:

- delete {node}                     refused when another node takes data from it (or, for a step, uses what it saved)
- reorder {order: [node, ...]}      refused when a node would come before the node it takes data from
- add_http {after, label, method, url, headers, body, links}   only on a flow with API nodes; risk from the rules
- edit_http {node: call id, label?, method?, url?, headers?, body?}   refused for a node whose template was masked on the PC
- label {node, label}               a group label, or the label of a step
- input_label {name, label}
- mode {node, mode}                 only up: auto < review < approve
- risk {node, risk}                 only up: read < write < money

The rules hold after every edit: risk only goes up and is never below what the rules give; write is always approve; money never auto;
a step only a person may do (the checker's Duyệt) is never put in a flow; no template piece looks like data.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from app import api_nodes
from app.risk import ORDER, risk_of_call
from app.schemas import SchemaError, validate_workflow

MODES = {"auto": 0, "review": 1, "approve": 2}
_MARK = re.compile(r"⟦([a-z0-9_]+)⟧")
_VAR = re.compile(r"\{([a-z][a-z0-9_]*)\}")


class EditError(ValueError):
    """The message is safe to show the person editing (Vietnamese)."""


def _least_mode(risk: str) -> str:
    return "auto" if risk == "read" else "approve"


def _higher_mode(current: str, wanted: str) -> str:
    return wanted if MODES[wanted] > MODES[current] else current


class _Flow:
    def __init__(self, workflow: dict[str, Any], api: list[dict[str, Any]] | None) -> None:
        self.workflow = copy.deepcopy(workflow)
        self.api = copy.deepcopy(api) if api else None

    # ---- what a canvas node is ----------------------------------------------------------------------------------------

    def groups(self) -> list[str]:
        seen: list[str] = []
        for node in self.api or []:
            if node["group"] not in seen:
                seen.append(node["group"])
        return seen

    def calls(self, group: str) -> list[dict[str, Any]]:
        return [n for n in self.api or [] if n["group"] == group]

    def group_label(self, group: str) -> str:
        calls = self.calls(group)
        return (calls[0].get("group_label") or calls[0]["label"]) if calls else group

    def step(self, step_id: str) -> dict[str, Any]:
        for step in self.workflow["steps"]:
            if step["id"] == step_id:
                return step
        raise EditError(f"Không có nút {step_id} trong luồng này.")

    def need_group(self, group: str) -> None:
        if group not in self.groups():
            raise EditError(f"Không có nút {group} trong luồng này.")

    def call(self, call_id: str) -> dict[str, Any]:
        for node in self.api or []:
            if node["id"] == call_id:
                return node
        raise EditError(f"Không có lời gọi {call_id} trong luồng này.")

    def users_of(self, group: str) -> list[str]:
        """Labels of the other groups that take data from a call of `group`."""
        ids = {n["id"] for n in self.calls(group)}
        users = []
        for other in self.groups():
            if other != group and any(rule.get("from") in ids for n in self.calls(other) for rule in (n.get("links") or {}).values()):
                users.append(self.group_label(other))
        return users

    # ---- operations ---------------------------------------------------------------------------------------------------

    def delete(self, op: dict[str, Any]) -> None:
        node = str(op.get("node") or "")
        if self.api is not None:
            self.need_group(node)
            users = self.users_of(node)
            if users:
                raise EditError(f"Không xoá được: nút «{', '.join(users)}» đang lấy dữ liệu từ nút này.")
            step_ids = {n.get("step_id") for n in self.calls(node)} - {None}
            self.api = [n for n in self.api if n["group"] != node]
            left = {n.get("step_id") for n in self.api}
            for step_id in step_ids - left:     # its step goes too, so running on the screen and by API stay the same
                if len(self.workflow["steps"]) > 1:
                    self.workflow["steps"] = [s for s in self.workflow["steps"] if s["id"] != step_id]
            if not self.api:
                raise EditError("Luồng phải còn ít nhất một nút.")
            return
        step = self.step(node)
        if len(self.workflow["steps"]) == 1:
            raise EditError("Luồng phải còn ít nhất một nút.")
        saved = step.get("save_as")
        if saved and any(saved in self._vars_of(s) for s in self.workflow["steps"] if s is not step):
            raise EditError(f"Không xoá được: một bước sau dùng dữ liệu «{saved}» mà bước này đọc.")
        self.workflow["steps"].remove(step)

    @staticmethod
    def _vars_of(step: dict[str, Any]) -> set[str]:
        names = set(_VAR.findall(str(step.get("value") or "")) + _VAR.findall(str(step.get("tolerance") or "")))
        return names | set(step.get("inputs") or [])

    def reorder(self, op: dict[str, Any]) -> None:
        order = [str(x) for x in op.get("order") or []]
        if self.api is not None:
            if sorted(order) != sorted(self.groups()):
                raise EditError("Thứ tự mới phải có đủ các nút của luồng, mỗi nút một lần.")
            position = {g: i for i, g in enumerate(order)}
            group_of = {n["id"]: n["group"] for n in self.api}
            for node in self.api:
                for rule in (node.get("links") or {}).values():
                    source = group_of.get(rule.get("from"))
                    if source is not None and position[source] > position[node["group"]]:
                        raise EditError(f"Nút «{self.group_label(node['group'])}» lấy dữ liệu từ «{self.group_label(source)}», "
                                        "nên phải đứng sau nút đó.")
            self.api = sorted(self.api, key=lambda n: position[n["group"]])     # stable: calls of a group keep their order
            return
        steps = {s["id"]: s for s in self.workflow["steps"]}
        if sorted(order) != sorted(steps):
            raise EditError("Thứ tự mới phải có đủ các nút của luồng, mỗi nút một lần.")
        saved_at = {s["save_as"]: i for i, s in enumerate(order and [steps[x] for x in order]) if s.get("save_as")}
        for index, step_id in enumerate(order):
            for name in self._vars_of(steps[step_id]):
                if name in saved_at and saved_at[name] > index:
                    raise EditError(f"Bước «{step_id}» dùng dữ liệu «{name}» nên phải đứng sau bước đọc nó.")
        self.workflow["steps"] = [steps[x] for x in order]

    def _check_call(self, node: dict[str, Any]) -> None:
        risk = risk_of_call(node["method"], node["url"], node.get("group_label") or node["label"])
        if risk.human_only:
            raise EditError("Bước Duyệt hoặc Từ chối của người kiểm soát luôn do người bấm, không đưa vào luồng.")
        if ORDER[risk.level] > ORDER[node.get("risk", "read")]:
            node["risk"] = risk.level
        node["mode"] = _higher_mode(node.get("mode") or _least_mode(node["risk"]), _least_mode(node["risk"]))
        names = set(_MARK.findall(node["url"] + node.get("body", "") + node.get("headers", "")))
        known = {i["name"] for i in self.workflow["inputs"]}
        ids = {n["id"] for n in self.api or []}
        node["unresolved"] = sorted(n for n in names if n not in known and n not in (node.get("links") or {}))
        node["unresolved"] += sorted(name for name, rule in (node.get("links") or {}).items() if rule.get("from") not in ids)

    def add_http(self, op: dict[str, Any]) -> None:
        if self.api is None:
            raise EditError("Chỉ thêm được nút API vào luồng chạy bằng API (luồng học từ trang web trong Internet Explorer).")
        label = str(op.get("label") or "").strip()
        method = str(op.get("method") or "GET").upper()
        url = str(op.get("url") or "").strip()
        if not label or not url:
            raise EditError("Nút mới cần tên và địa chỉ.")
        groups = self.groups()
        number = 1 + max([int(g[1:]) for g in groups if g[1:].isdigit()] or [0])
        call_number = 1 + max([int(n["id"][1:]) for n in self.api if n["id"].startswith("n") and n["id"][1:].isdigit()] or [0])
        group = f"g{number}"
        path = url.split("?", 1)[0]
        node = {"id": f"n{call_number}", "step_id": None, "group": group, "group_label": label, "label": f"{label} → {method} {path[-60:]}",
                "kind": "http", "via": "", "method": method, "url": url, "headers": str(op.get("headers") or ""), "body": str(op.get("body") or ""),
                "links": {str(k): dict(v) for k, v in (op.get("links") or {}).items()}, "risk": "read", "complete": True,
                "unresolved": [], "ms": 0, "masked": 0, "added": True}
        after = op.get("after")
        if after is None:
            index = 0
        else:
            self.need_group(str(after))
            index = max(i for i, n in enumerate(self.api) if n["group"] == after) + 1
        self.api.insert(index, node)
        self._check_call(node)

    def edit_http(self, op: dict[str, Any]) -> None:
        if self.api is None:
            raise EditError("Luồng này không có nút API.")
        node = self.call(str(op.get("node") or ""))
        changes = {k: str(op[k]) for k in ("method", "url", "headers", "body") if k in op}
        if changes and node.get("masked"):
            raise EditError("Nút này ghi từ máy GDV, một phần mẫu chỉ nằm trên máy đó nên không sửa mẫu ở đây được. "
                            "Đổi tên, mức kiểm soát được; muốn đổi mẫu thì thêm nút mới.")
        node.update({k: (v.upper() if k == "method" else v) for k, v in changes.items()})
        if "label" in op:
            node["label"] = str(op["label"])
        if changes:
            self._check_call(node)

    def label(self, op: dict[str, Any]) -> None:
        node, text = str(op.get("node") or ""), str(op.get("label") or "").strip()
        if not text:
            raise EditError("Tên nút không được để trống.")
        if self.api is not None:
            self.need_group(node)
            for call in self.calls(node):
                tail = call["label"].split(" → ", 1)[1] if " → " in call["label"] else call["label"]
                call["group_label"], call["label"] = text, f"{text} → {tail}"
                if call.get("added"):
                    self._check_call(call)       # a new label may say more about the risk; it never lowers it
            return
        step = self.step(node)
        if step.get("target") is not None:
            step["target"]["label"] = text

    def input_label(self, op: dict[str, Any]) -> None:
        name, text = str(op.get("name") or ""), str(op.get("label") or "").strip()
        for item in self.workflow["inputs"]:
            if item["name"] == name:
                item["label"] = text or None
                return
        raise EditError(f"Không có ô nhập {name}.")

    def mode(self, op: dict[str, Any]) -> None:
        node, wanted = str(op.get("node") or ""), str(op.get("mode") or "")
        if wanted not in MODES:
            raise EditError("Mức kiểm soát chỉ là auto, review hoặc approve.")
        targets = self._targets(node)
        for target in targets:
            current = target.get("mode") or _least_mode(target["risk"])
            if MODES[wanted] < MODES[current]:
                raise EditError("Chỉ được nâng mức kiểm soát, không được hạ.")
            target["mode"] = wanted

    def risk(self, op: dict[str, Any]) -> None:
        node, wanted = str(op.get("node") or ""), str(op.get("risk") or "")
        if wanted not in ORDER:
            raise EditError("Mức rủi ro chỉ là read, write hoặc money.")
        for target in self._targets(node):
            if ORDER[wanted] < ORDER[target["risk"]]:
                raise EditError("Chỉ được nâng mức rủi ro, không được hạ.")
            target["risk"] = wanted
            target["mode"] = _higher_mode(target.get("mode") or _least_mode(wanted), _least_mode(wanted))

    def _targets(self, node: str) -> list[dict[str, Any]]:
        if self.api is not None:
            self.need_group(node)
            return self.calls(node)
        return [self.step(node)]


OPERATIONS = ("delete", "reorder", "add_http", "edit_http", "label", "input_label", "mode", "risk")


def apply(workflow: dict[str, Any], api: list[dict[str, Any]] | None, ops: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    """The edited copies of `workflow` and `api`. The caller sets the new version and status. Raises EditError."""
    if not ops:
        raise EditError("Chưa có thay đổi nào.")
    flow = _Flow(workflow, api)
    for index, op in enumerate(ops):
        kind = str(op.get("op") or "")
        if kind not in OPERATIONS:
            raise EditError(f"Thao tác {index + 1}: không biết «{kind}».")
        getattr(flow, kind)(op)
    for step in flow.workflow["steps"]:          # the hard rules (CLAUDE.md 3): the schema says so too
        if step["risk"] == "write":
            step["mode"] = "approve"
        if step["risk"] == "money" and step["mode"] == "auto":
            step["mode"] = "approve"
    try:
        validate_workflow(flow.workflow)
        if flow.api is not None:
            api_nodes.check(flow.api)
    except SchemaError as error:
        raise EditError(str(error)) from None
    return flow.workflow, flow.api
