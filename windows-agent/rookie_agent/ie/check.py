"""A recording checks itself right after «Dừng ghi» (task 11.3): one list of rules, in plain words for the teller, each with what to do.

Read from the saved recording (events and request templates) and the notes the recorder kept; nothing is sent anywhere. A finding is
{"level": "ok" | "note" | "redo", "text", "hint"}: «redo» means the flow will not run from this recording as it is and says what to
record again; «note» is worth knowing; «ok» says what went well.
"""

from __future__ import annotations

from typing import Any

from rookie_agent.ie import clean


def learned(api: list[dict[str, Any]], workflow: dict[str, Any]) -> dict[str, Any]:
    """Task 11.4: what a flow just learned can do, in plain words: how many of its steps run again by request, which are not sure and
    why, what to do. Steps that write or move money are counted apart: they run on the screen with a Duyệt, never by request."""
    from rookie_agent.ie import replay

    if not api:
        return {"ready": 0, "total": len(workflow.get("steps", [])), "lines": ["Luồng này chạy bằng cách bấm trên màn hình (không có lời gọi hệ thống được ghi)."]}
    by_id = {n["id"]: n for n in api}
    groups = replay.groups_of(api)
    ready, lines = 0, []
    for group in groups:
        calls = [by_id[c] for c in group["calls"]]
        if group["risk"] != "read":
            lines.append(f"«{group['label']}» ghi dữ liệu hoặc liên quan tiền: chạy trên màn hình, chờ bạn Duyệt.")
            continue
        broken = [c for c in calls if not c.get("complete") or c.get("unresolved")]
        if not broken:
            ready += 1
            continue
        why = ("có giá trị chưa biết lấy từ đâu: " + ", ".join(sorted({u for c in broken for u in c.get("unresolved") or []}))
               if any(c.get("unresolved") for c in broken) else "có mã bảo mật không rõ nguồn hoặc yêu cầu bị cắt khi ghi")
        lines.append(f"«{group['label']}» chưa chạy lại được bằng yêu cầu ({why}). Nên ghi thêm một lần, bắt đầu từ lúc mở màn hình.")
    reads = sum(1 for g in groups if g["risk"] == "read")
    head = f"Chạy lại được bằng yêu cầu: {ready}/{reads} bước chỉ xem." if reads else "Không có bước chỉ xem nào."
    files = sum(1 for n in api if n.get("kind") == "file")
    if files:
        head += f" Có {files} bước trả về file (lưu vào thư mục Rookie, có nút In)."
    return {"ready": ready, "total": len(groups), "lines": [head] + lines}


def _label(event: dict[str, Any] | None) -> str:
    if not event:
        return "lúc mở màn hình"
    return str((event.get("target") or {}).get("label") or event.get("type") or "?")


def check(document: dict[str, Any], notes: list[str] | None = None, requests_on: bool = True) -> list[dict[str, str]]:
    events = document.get("events") or []
    requests = document.get("requests") or []
    by_seq = {int(e["seq"]): e for e in events if e.get("seq") is not None}
    found: list[dict[str, str]] = []

    def add(level: str, text: str, hint: str = "") -> None:
        found.append({"level": level, "text": text, "hint": hint})

    if not requests_on:
        add("note", "Chưa bật «Ghi yêu cầu»: agent chỉ chạy được bằng cách bấm trên màn hình.",
            "Bật «Ghi yêu cầu» rồi ghi lại nếu muốn trợ lý lấy kết quả và file mà không cần mở màn hình.")
        return found

    asking = clean.polling(requests)
    real = [r for i, r in enumerate(requests) if int(r.get("index", i)) not in asking]
    boxes = [r for r in real if clean.is_message_box(str(r.get("url") or ""))]
    if boxes:
        add("note", f"Có {len(boxes)} lần hiện hộp thông báo của trang (thường do bấm nhầm hoặc nhập sai định dạng).",
            "Đã bỏ qua khi học. Nếu lần nào cũng hiện thì kiểm tra lại cách nhập.")
    failed = [r for r in real if int(r.get("status") or 0) >= 400 or (int(r.get("status") or 0) == 0 and r.get("kind") == "xhr")]
    for r in failed[:5]:
        add("redo", f"Ở bước «{_label(by_seq.get(r.get('after_seq')))}», hệ thống báo lỗi khi ghi.",
            "Ghi lại khi hệ thống chạy bình thường; bước lỗi không được học.")
    blocked = [r for r in real if not r.get("complete") and r not in failed and not clean.is_message_box(str(r.get("url") or ""))]
    for r in blocked[:5]:
        add("redo", f"Ở bước «{_label(by_seq.get(r.get('after_seq')))}» có mã bảo mật không rõ lấy từ đâu: bước này không chạy lại được bằng yêu cầu.",
            "Ghi lại từ lúc mở màn hình (đừng bắt đầu ghi giữa chừng), để agent thấy nơi mã đó được cấp.")
    guessed = [r for r in real if (r.get("file") or {}).get("guess")]
    for r in guessed[:5]:
        add("note", f"Bước «{_label(by_seq.get(r.get('after_seq')))}» có vẻ trả về một file (chưa chắc).", "Lúc chạy agent sẽ biết chắc và lưu file vào thư mục Rookie.")
    sure_files = [r for r in real if r.get("file") and not (r.get("file") or {}).get("guess")]
    pressed = [e for e in events if e.get("type") in ("click", "submit")]
    quiet = [e for e in pressed if not clean.effect({"requests": requests}, int(e["seq"]))]
    mistaken = len(pressed) - len([e for e in clean.drop_mistakes(document).get("events") or [] if e.get("type") in ("click", "submit")])
    if mistaken:
        add("note", f"Có {mistaken} lần bấm không có tác dụng rồi bấm lại (bấm nhầm).", "Đã bỏ qua khi học.")
    if pressed and len(quiet) == len(pressed) and real:
        add("redo", "Không thao tác nào gọi tới hệ thống: có thể bộ ghi không theo được trang.",
            "Bấm «Kiểm tra máy», rồi ghi lại; nếu vẫn vậy, bấm «Gửi chẩn đoán».")
    for note in notes or []:
        if "không với tới" in note or "unreadable" in note or "từ chối bộ ghi" in note:
            add("redo", "Có một phần của trang (khung hoặc hộp thoại) bộ ghi không đọc được.", "Bấm «Gửi chẩn đoán» để nhóm phát triển xem.")
            break
    for one in document.get("report_maps") or []:
        add("ok", f"Agent đã học cách dựng bản «{one.get('title')}» từ dữ liệu hệ thống trả về ({len(one.get('fields') or [])} trường có nhãn).",
            "Chạy xong sẽ có file «… (bản in).html» để xem và in.")
    if not any(f["level"] == "redo" for f in found):
        calls = len([r for r in real if not clean.is_message_box(str(r.get("url") or ""))])
        add("ok", f"Bản ghi dùng được: {len(events)} thao tác, {calls} lời gọi hệ thống" + (f", {len(sure_files) + len(guessed)} file" if sure_files or guessed else "") + ".",
            "Nên ghi thêm 1–2 lần với dữ liệu khác rồi bấm Học.")
    return found
