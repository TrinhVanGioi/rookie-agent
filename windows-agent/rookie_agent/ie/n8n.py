"""Gate 9: the process as an n8n-style workflow file, to look at and keep (a download from the page; nothing is sent anywhere).

API calls become `httpRequest` nodes (n8n needs one per call) with the method, the url and the body as TEMPLATES (the `⟦cif⟧`, `⟦l1⟧`
marks, never a value); no headers are written (they may hold a cookie or a token). The calls of one step are named under it and a sticky
note around them says which step they belong to; a step that writes has one Duyệt in front of its first call. A Duyệt is a `wait` node, a handover a `noOp`. The file cannot run the
process: a real run must be inside the teller's signed-in IE page.
"""

from __future__ import annotations

from typing import Any

NOTE = "Chỉ để xem/lưu; chạy thật phải trong phiên IE của GDV"
ROLE_WORDS = {"maker": "GDV", "checker": "KSV"}
STEP = 240


def export(name: str, stages: list[dict[str, Any]]) -> dict[str, Any]:
    """`stages`: [{label, role, api: [node...], steps: [{id, label, risk}...]}]; the nodes of the flow as `build_api` made them (each may
    say its `group`, `group_label` and `name`; a flow saved before groups has none and its calls are grouped by the step they belong to)."""
    nodes: list[dict[str, Any]] = []
    order: list[str] = []
    seen: dict[str, int] = {}
    placed = [0]                                       # the chain's nodes so far: a sticky note takes no place in the chain

    def add(label: str, kind: str, row: int, parameters: dict[str, Any], note: str = "") -> str:
        seen[label] = seen.get(label, 0) + 1
        unique = label if seen[label] == 1 else f"{label} ({seen[label]})"
        node: dict[str, Any] = {"id": f"n{len(nodes) + 1}", "name": unique, "type": kind, "typeVersion": 1,
                                "position": [placed[0] * STEP, row * 280], "parameters": parameters}
        placed[0] += 1
        if note:
            node["notes"], node["notesInFlow"] = note, True
        nodes.append(node)
        order.append(unique)
        return unique

    add("Bắt đầu", "n8n-nodes-base.manualTrigger", 0, {}, NOTE)
    for index, stage in enumerate(stages):
        role = ROLE_WORDS.get(str(stage.get("role")), str(stage.get("role") or ""))
        head = f"{stage.get('label') or 'Chặng ' + str(index + 1)} ({role})"
        if index:
            add("Bàn giao / Hàng chờ duyệt", "n8n-nodes-base.noOp", index, {}, "Lệnh nằm trong hàng chờ cho chặng sau; không gửi gì đi.")
        if stage.get("role") == "checker":
            add(f"Duyệt: {head}", "n8n-nodes-base.wait", index, {"resume": "webhook"}, "Người kiểm soát bấm Duyệt; agent không tự duyệt.")
        items = stage.get("api") or []
        if items:
            for group in _steps_of(items):
                first = placed[0]
                if group["risk"] in ("write", "money"):
                    add(f"Duyệt: {group['label']}", "n8n-nodes-base.wait", index, {"resume": "webhook"}, "Bước ghi hoặc tiền luôn chờ người Duyệt.")
                total = len(group["items"])
                for number, item in enumerate(group["items"], 1):
                    add(f"{group['label']} · {number}/{total} {item.get('name') or item['method']}", "n8n-nodes-base.httpRequest", index,
                        {"method": item["method"], "url": item["url"], "sendBody": bool(item.get("body")), "body": item.get("body", ""), "options": {}},
                        f"{head}. Mẫu có dấu ⟦…⟧ thay cho giá trị; không có header.")
                last = placed[0]
                nodes.append({"id": f"n{len(nodes) + 1}", "name": f"Bước: {group['label']}", "type": "n8n-nodes-base.stickyNote", "typeVersion": 1,
                              "position": [first * STEP - 40, index * 280 - 90],
                              "parameters": {"content": f"{group['label']}\n{total} lời gọi của một bước ({head})", "width": (last - first) * STEP, "height": 260}})
        else:
            for step in stage.get("steps") or []:
                if step.get("risk") in ("write", "money"):
                    add(f"Duyệt: {step['label']}", "n8n-nodes-base.wait", index, {"resume": "webhook"}, "Bước ghi hoặc tiền luôn chờ người Duyệt.")
                add(step["label"], "n8n-nodes-base.noOp", index, {}, f"{head}: thao tác trên màn hình.")
    add("Kết thúc", "n8n-nodes-base.noOp", max(len(stages) - 1, 0), {})
    connections = {a: {"main": [[{"node": b, "type": "main", "index": 0}]]} for a, b in zip(order, order[1:])}
    return {"name": name, "nodes": nodes, "connections": connections, "active": False, "settings": {}, "meta": {"note": NOTE}}


def _steps_of(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The calls of a stage as its steps, in order: [{label, risk, items}]."""
    steps: list[dict[str, Any]] = []
    for item in items:
        key = item.get("group")
        label = item.get("group_label") or str(item.get("label") or "").rsplit(" → ", 1)[0]
        if not steps or (steps[-1]["key"] != key if key is not None else steps[-1]["label"] != label):
            steps.append({"key": key, "label": label, "risk": "read", "items": []})
        steps[-1]["items"].append(item)
        if item.get("risk") in ("write", "money") and steps[-1]["risk"] != "money":
            steps[-1]["risk"] = item["risk"]
    return steps
