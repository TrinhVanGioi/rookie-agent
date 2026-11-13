/** What the flow canvas shows while an agent runs, built only from the agent's events. */
import type { AgentEvent } from "./rpc";

export type StepStatus =
  | "pending"
  | "running"
  | "done"
  | "waiting_approval"
  | "waiting_review"
  | "auto_approved"
  | "needs_help"
  | "failed"
  | "stopped"
  | "rejected"
  | "refused";

export interface Waiting {
  kind: "approve" | "review";
  stepId: string;
  label: string | null;
  risk: string;
}

export interface RunState {
  phase: "idle" | "running" | "finished";
  sandbox: boolean;
  /** Steps in the order they were reported; the flow's own order comes from the workflow. */
  steps: Record<string, StepStatus>;
  /** The step being worked on or waited for. */
  current: string | null;
  waiting: Waiting | null;
  result: { status: string; message: string } | null;
}

export const idleState = (): RunState => ({
  phase: "idle",
  sandbox: false,
  steps: {},
  current: null,
  waiting: null,
  result: null,
});

export const startedState = (sandbox: boolean): RunState => ({ ...idleState(), phase: "running", sandbox });

const KNOWN: ReadonlySet<string> = new Set([
  "running", "done", "waiting_approval", "waiting_review", "auto_approved",
  "needs_help", "failed", "stopped", "rejected", "refused",
]);

export function reduce(state: RunState, event: AgentEvent): RunState {
  if (event.event === "progress") {
    const status = String(event.status);
    const stepId = String(event.step_id);
    if (!KNOWN.has(status)) return state;
    const keepWaiting = status === "waiting_approval" || status === "waiting_review" ? state.waiting : null;
    // The agent has no event for "the GDV looked and said go on": when it starts or waits on another
    // step, a step that was waiting for a look is done.
    const settled = { ...state.steps };
    for (const [id, was] of Object.entries(settled)) if (id !== stepId && was === "waiting_review") settled[id] = "done";
    return {
      ...state,
      phase: state.phase === "idle" ? "running" : state.phase,
      steps: { ...settled, [stepId]: status as StepStatus },
      current: status === "done" ? state.current : stepId,
      waiting: status === "running" || status === "done" ? null : keepWaiting,
    };
  }
  if (event.event === "waiting") {
    return {
      ...state,
      phase: "running",
      current: String(event.step_id),
      waiting: {
        kind: event.kind === "review" ? "review" : "approve",
        stepId: String(event.step_id),
        label: typeof event.label === "string" ? event.label : null,
        risk: String(event.risk ?? "read"),
      },
    };
  }
  if (event.event === "finished") {
    const done = { ...state.steps };
    if (event.status === "finished") for (const [id, was] of Object.entries(done)) if (was === "waiting_review") done[id] = "done";
    return {
      ...state,
      steps: done,
      phase: "finished",
      sandbox: Boolean(event.sandbox),
      waiting: null,
      result: { status: String(event.status), message: String(event.message ?? "") },
    };
  }
  return state;
}

/** What the GDV reads on a step, in plain words. */
export const STATUS_TEXT: Record<StepStatus, string> = {
  pending: "Chờ",
  running: "Đang làm",
  done: "Xong",
  waiting_approval: "Chờ bạn duyệt",
  waiting_review: "Chờ bạn xem",
  auto_approved: "Đã tự duyệt (thử)",
  needs_help: "Cần bạn giúp",
  failed: "Gặp sự cố",
  stopped: "Đã dừng",
  rejected: "Bạn không duyệt",
  refused: "Không được phép",
};
