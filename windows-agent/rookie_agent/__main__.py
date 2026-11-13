"""Command line of the Windows agent.

    python -m rookie_agent status              is the bridge working, which Java windows are open
    python -m rookie_agent tree [--window X]   dump the component tree (the spike for task 1.7)
    python -m rookie_agent record --out FILE   record until Enter is pressed, write the events
    python -m rookie_agent upload --server URL --file FILE
                                               send a recorded session to the server
    python -m rookie_agent learn --server URL --id NAME --sessions ID ID ID
                                               ask the server to learn a workflow (draft)
    python -m rookie_agent sandbox --server URL --id NAME --version N [--input k=v ...]
                                               run a draft on the Swing mock; a pass allows `tested`
    python -m rookie_agent promote --server URL --id NAME --version N --to tested|approved
    python -m rookie_agent run --server URL --id NAME [--input k=v ...]
                                               run the approved workflow here, asking before risky steps
    python -m rookie_agent host                Native Messaging host (started by the browser)
    python -m rookie_agent web [--port N]      the local page (check this PC, record, learn); what the desktop icon starts
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
    from rookie_agent.java_feed import JavaFeed

    recorder = Recorder()
    session.attach(recorder)
    feed = JavaFeed(recorder)
    feed.start(recorder.session_id)
    print(f"ĐANG GHI trên: {title}")
    print("Thao tác trên ứng dụng Java, xong thì quay lại đây bấm Enter để Dừng.")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
    feed.stop()
    session.detach()
    events = recorder.stop()
    session.close()
    document = {"schema_version": 1, "engine": "java", "session_id": recorder.session_id, "events": events}
    Path(args.out).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Đã ghi {len(events)} sự kiện vào {args.out}")


def _inputs(pairs: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for pair in pairs or []:
        name, separator, value = pair.partition("=")
        if not separator or not name:
            sys.exit(f"Lỗi: --input phải có dạng ten=gia_tri, nhận được {pair!r}")
        result[name] = value
    return result


def _server(args: argparse.Namespace):
    from rookie_agent.server_client import ServerClient

    return ServerClient(args.server)


def _guard(action):
    """Run a server action and turn ServerError into a plain message."""
    from rookie_agent.server_client import ServerError

    try:
        return action()
    except ServerError as error:
        sys.exit(f"Lỗi: {error}")


def cmd_upload(args: argparse.Namespace) -> None:
    document = json.loads(Path(args.file).read_text(encoding="utf-8"))
    reply = _guard(lambda: _server(args).post_session(document["session_id"], document["engine"], document["events"]))
    print(f"Đã gửi phiên {reply['session_id']} ({reply['event_count']} sự kiện).")


def cmd_learn(args: argparse.Namespace) -> None:
    reply = _guard(lambda: _server(args).learn(args.id, args.sessions))
    workflow = reply["workflow"]
    print(f"Đã học workflow {workflow['id']} bản {workflow['version']} (trạng thái {workflow['status']}).")
    print("Tham số:", ", ".join(item["name"] for item in workflow["inputs"]) or "(không có)")
    for step in workflow["steps"]:
        label = (step.get("target") or {}).get("label") or step["id"]
        print(f"  {step['id']}: {step['action']} «{label}» rủi ro={step['risk']} chế độ={step['mode']}")
    for warning in reply["warnings"]:
        print("CẢNH BÁO:", warning)


def cmd_sandbox(args: argparse.Namespace) -> None:
    from rookie_agent.sandbox import sandbox_and_report

    result = _guard(lambda: sandbox_and_report(_server(args), args.id, args.version, _inputs(args.input), args.role))
    print(f"Kết quả chạy thử: {result['status']} - {result['message']}")
    sys.exit(0 if result["status"] == "finished" else 1)


def cmd_promote(args: argparse.Namespace) -> None:
    reply = _guard(lambda: _server(args).set_status(args.id, args.version, args.to))
    print(f"Workflow {args.id} bản {args.version} giờ ở trạng thái {reply['workflow']['status']}.")


def cmd_run(args: argparse.Namespace) -> None:
    import threading

    from rookie_agent.controllers import ConsoleController
    from rookie_agent.jab.driver import JabDriver
    from rookie_agent.runner import run_workflow

    reply = _guard(lambda: _server(args).approved_workflow(args.id))
    workflow = reply["workflow"]
    print(f"Chạy workflow {workflow['id']} bản {workflow['version']}. Bấm Ctrl+C để Dừng khẩn.")
    session = _open_session()
    stop = threading.Event()
    try:
        hwnd, title = session.wait_for_window(args.window, timeout=10)
        print(f"Cửa sổ: {title}")
        runner = threading.Thread(
            target=lambda: results.append(
                run_workflow(workflow, _inputs(args.input), JabDriver(session, hwnd), ConsoleController(), stop)
            ),
            daemon=True,
        )
        results: list[dict] = []
        runner.start()
        while runner.is_alive():
            try:
                runner.join(0.2)
            except KeyboardInterrupt:
                stop.set()
                print("DỪNG KHẨN: agent dừng ở điểm kiểm soát gần nhất.")
        result = results[0] if results else {"status": "failed", "message": "Runner không trả kết quả."}
    except Exception as error:
        sys.exit(f"Lỗi: {error}")
    finally:
        session.close()
    print(f"Kết quả: {result['status']} - {result['message']}")
    sys.exit(0 if result["status"] == "finished" else 1)


def cmd_host(_: argparse.Namespace) -> None:
    from rookie_agent.native_host import main

    main()


def cmd_web(args: argparse.Namespace) -> None:
    from rookie_agent.webui.server import main as web_main

    web_main(args.port, open_browser=not args.no_browser, auto_bits=args.auto_bits)


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
    upload = commands.add_parser("upload", help="gửi một phiên ghi lên máy chủ")
    upload.add_argument("--server", required=True)
    upload.add_argument("--file", required=True)
    upload.set_defaults(run=cmd_upload)
    learn = commands.add_parser("learn", help="học workflow từ các phiên đã gửi")
    learn.add_argument("--server", required=True)
    learn.add_argument("--id", required=True)
    learn.add_argument("--sessions", nargs="+", required=True)
    learn.set_defaults(run=cmd_learn)
    sandbox = commands.add_parser("sandbox", help="chạy thử bản nháp trên mock Swing")
    sandbox.add_argument("--server", required=True)
    sandbox.add_argument("--id", required=True)
    sandbox.add_argument("--version", type=int, required=True)
    sandbox.add_argument("--input", action="append", default=[], help="ten=gia_tri (giá trị synthetic)")
    sandbox.add_argument("--role", choices=["maker", "checker"], default="maker")
    sandbox.set_defaults(run=cmd_sandbox)
    promote = commands.add_parser("promote", help="chuyển trạng thái workflow")
    promote.add_argument("--server", required=True)
    promote.add_argument("--id", required=True)
    promote.add_argument("--version", type=int, required=True)
    promote.add_argument("--to", choices=["tested", "approved"], required=True)
    promote.set_defaults(run=cmd_promote)
    run = commands.add_parser("run", help="chạy workflow đã duyệt trên máy này")
    run.add_argument("--server", required=True)
    run.add_argument("--id", required=True)
    run.add_argument("--input", action="append", default=[], help="ten=gia_tri")
    run.add_argument("--window", default="", help="một phần tiêu đề cửa sổ")
    run.set_defaults(run=cmd_run)
    commands.add_parser("host", help="chạy Native Messaging host").set_defaults(run=cmd_host)
    web = commands.add_parser("web", help="mở trang quản lý trên máy này")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--no-browser", action="store_true", help="không tự mở trình duyệt")
    web.add_argument("--auto-bits", action="store_true", help="tự chuyển sang Python cùng bit với Java")
    web.set_defaults(run=cmd_web)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
