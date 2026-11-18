"""Gate 9: the process as an n8n-style workflow file, to look at and keep (a download from the page; nothing is sent anywhere).

API calls become `httpRequest` nodes with the method, the url and the body as TEMPLATES (the `⟦cif⟧`, `⟦l1⟧` marks, never a value);
no headers are written (they may hold a cookie or a token). A Duyệt is a `wait` node, a handover a `noOp`. The file cannot run the
process: a real run must be inside the teller's signed-in IE page.
"""

from __future__ import annotations

from typing import Any

NOTE = "Chỉ để xem/lưu; chạy thật phải trong phiên IE của GDV"
ROLE_WORDS = {"maker": "GDV lập lệnh", "checker": "KSV"}
STEP = 240


def export(name: str, stages: list[dict[str, Any]]) -> dict[str, Any]:
    """`stages`: [{label, role, api: [node...], steps: [{id, label, risk}...]}]; the nodes of the flow as `build_api` made them."""
    nodes: list[dict[str, Any]] = []
    order: list[str] = []
    seen: dict[str, int] = {}

    def add(label: str, kind: str, row: int, parameters: dict[str, Any], note: str = "") -> str:
        seen[label] = seen.get(label, 0) + 1
        unique = label if seen[label] == 1 else f"{label} ({seen[label]})"
        node: dict[str, Any] = {"id": f"n{len(nodes) + 1}", "name": unique, "type": kind, "typeVersion": 1,
                                "position": [len(nodes) * STEP, row * 280], "parameters": parameters}
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
            for item in items:
                if item.get("risk") in ("write", "money"):
                    add(f"Duyệt: {item['label']}", "n8n-nodes-base.wait", index, {"resume": "webhook"}, "Bước ghi hoặc tiền luôn chờ người Duyệt.")
                add(item["label"], "n8n-nodes-base.httpRequest", index,
                    {"method": item["method"], "url": item["url"], "sendBody": bool(item.get("body")), "body": item.get("body", ""), "options": {}},
                    f"{head}. Mẫu có dấu ⟦…⟧ thay cho giá trị; không có header.")
        else:
            for step in stage.get("steps") or []:
                if step.get("risk") in ("write", "money"):
                    add(f"Duyệt: {step['label']}", "n8n-nodes-base.wait", index, {"resume": "webhook"}, "Bước ghi hoặc tiền luôn chờ người Duyệt.")
                add(step["label"], "n8n-nodes-base.noOp", index, {}, f"{head}: thao tác trên màn hình.")
    add("Kết thúc", "n8n-nodes-base.noOp", max(len(stages) - 1, 0), {})
    connections = {a: {"main": [[{"node": b, "type": "main", "index": 0}]]} for a, b in zip(order, order[1:])}
    return {"name": name, "nodes": nodes, "connections": connections, "active": False, "settings": {}, "meta": {"note": NOTE}}
