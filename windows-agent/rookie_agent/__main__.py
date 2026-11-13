"""Command line of the Windows agent.

    python -m rookie_agent status              is the bridge working, which Java windows are open
    python -m rookie_agent tree [--window X]   dump the component tree (the spike for task 1.7)
    python -m rookie_agent record --out FILE   record until Enter is pressed, write the events
    python -m rookie_agent host                Native Messaging host (started by the browser)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _print_tree(node, depth: int = 0) -> tuple[int, int]:
    """Print the tree; return (interactive components, interactive components without a name)."""
    from rookie_agent.recorder import CLICK_ROLES, TABLE_ROLE, TAB_ROLE, TEXT_ROLES, TOGGLE_ROLES

    interactive_roles = CLICK_ROLES | TOGGLE_ROLES | TEXT_ROLES | {TAB_ROLE, TABLE_ROLE, "password text", "combo box", "list"}
    interactive = node.role in interactive_roles and "showing" in node.states.split(",")
    unnamed = interactive and not node.name.strip()
    flag = "  <-- KHÔNG CÓ TÊN" if unnamed else ""
    print(f"{'  ' * depth}{node.role} [{node.name}]{flag}")
    total, missing = int(interactive), int(unnamed)
    for child in node.children:
        child_total, child_missing = _print_tree(child, depth + 1)
        total += child_total
        missing += child_missing
    return total, missing


def _open_session():
    from rookie_agent.jab import bridge as jab
    from rookie_agent.jab.session import JabSession

    try:
        return JabSession().open()
    except jab.BridgeError as error:
        sys.exit(f"Lỗi: {error}")


def cmd_status(_: argparse.Namespace) -> None:
    from rookie_agent.jab import bridge as jab

    print(f"Python {jab.BITS}-bit, cần {jab.DLL_NAME}")
    session = _open_session()
    try:
        session.wait_for_window(timeout=5)
    except jab.BridgeError as error:
        print(error)
    windows = session.windows()
    print(f"Java Access Bridge: sẵn sàng ({session.call(lambda b: b.dll_path)})")
    print(f"Cửa sổ Java đang mở: {len(windows)}")
    for _, title in windows:
        print(f"  - {title}")
    session.close()


def cmd_tree(args: argparse.Namespace) -> None:
    session = _open_session()
    try:
        hwnd, title = session.wait_for_window(args.window, timeout=10)
    except Exception as error:
        sys.exit(f"Lỗi: {error}")
    print(f"Cửa sổ: {title}\n")
    total, missing = _print_tree(session.tree(hwnd))
    print(f"\nThành phần thao tác được đang hiển thị: {total}; không có tên accessible: {missing}")
    if total and missing / total > 0.3:
        print("Nhiều thành phần không có tên: cần phương án Java agent dự phòng (docs/design.md 3B).")
    session.close()


def cmd_record(args: argparse.Namespace) -> None:
    from rookie_agent.recorder import Recorder

    session = _open_session()
    try:
        _, title = session.wait_for_window(args.window, timeout=10)
    except Exception as error:
        sys.exit(f"Lỗi: {error}")
    recorder = Recorder()
    session.attach(recorder)
    print(f"ĐANG GHI trên: {title}")
    print("Thao tác trên ứng dụng Java, xong thì quay lại đây bấm Enter để Dừng.")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
    session.detach()
    events = recorder.stop()
    session.close()
    document = {"schema_version": 1, "engine": "java", "session_id": recorder.session_id, "events": events}
    Path(args.out).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Đã ghi {len(events)} sự kiện vào {args.out}")


def cmd_host(_: argparse.Namespace) -> None:
    from rookie_agent.native_host import main

    main()


def main() -> None:
    # The browser passes the extension origin as an argument when it starts the host.
    if len(sys.argv) > 1 and sys.argv[1].startswith(("chrome-extension://", "moz-extension://")):
        sys.argv[1:] = ["host"]
    if hasattr(sys.stdout, "reconfigure") and sys.argv[1:2] != ["host"]:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="rookie_agent", description="Windows agent của Rookie Agent (hướng B)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="kiểm tra Java Access Bridge").set_defaults(run=cmd_status)
    tree = commands.add_parser("tree", help="in cây thành phần của một cửa sổ Java")
    tree.add_argument("--window", default="", help="một phần tiêu đề cửa sổ")
    tree.set_defaults(run=cmd_tree)
    record = commands.add_parser("record", help="ghi thao tác ra file JSON")
    record.add_argument("--window", default="", help="một phần tiêu đề cửa sổ")
    record.add_argument("--out", required=True, help="file JSON kết quả")
    record.set_defaults(run=cmd_record)
    commands.add_parser("host", help="chạy Native Messaging host").set_defaults(run=cmd_host)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
