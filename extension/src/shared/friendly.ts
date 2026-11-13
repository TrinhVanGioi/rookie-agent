/**
 * Sentences for the GDV. A result says what happened to the work and what they can do next, in
 * terms of what they see on screen («Gửi duyệt»), never an internal step id or a technical term.
 */
import { captionOf } from "./flow-graph";
import type { RunState } from "./run-state";
import type { Workflow } from "./server-api";

function where(state: RunState, workflow: Workflow | null): string {
  const step = workflow?.steps.find((s) => s.id === state.current);
  const caption = step ? captionOf(step) : "";
  return caption ? `«${caption}»` : "bước này";
}

export function describeResult(state: RunState, workflow: Workflow | null): string {
  if (state.phase === "idle") return "";
  if (state.phase === "running") return state.sandbox ? "Đang thử trên dữ liệu mẫu, không ảnh hưởng gì thật…" : "Agent đang làm…";
  const result = state.result;
  if (!result) return "";
  const total = workflow?.steps.length ?? 0;
  switch (result.status) {
    case "finished":
      return state.sandbox
        ? `Thử xong, agent làm đủ ${total} bước. Bạn có thể bấm Duyệt để dùng thật.`
        : `Xong. Agent đã làm đủ ${total} bước.`;
    case "stopped":
      return "Đã dừng theo yêu cầu của bạn. Các bước làm rồi vẫn giữ nguyên, bước chưa làm thì chưa thực hiện.";
    case "rejected":
      return `Bạn không đồng ý ở ${where(state, workflow)}, nên agent đã dừng và không làm tiếp.`;
    case "needs_help":
      return `Agent không tìm thấy ${where(state, workflow)} trên màn hình nên dừng lại hỏi bạn. Có thể màn hình đã thay đổi.`;
    case "refused":
      return "Agent chưa được phép chạy việc này. Việc cần được duyệt trước, hoặc có bước vi phạm quy tắc an toàn.";
    default:
      return `Agent dừng ở ${where(state, workflow)} vì gặp sự cố. Bạn có thể thử lại hoặc làm bước này bằng tay.`;
  }
}
