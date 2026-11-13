/**
 * "What goes into this step?" for the GDV, in the words of the counter.
 *
 * For one step: what the agent does, which information it takes and where that comes from,
 * what it hands on, what it may touch and how much control it has. For a step that asks for
 * approval, the whole list of what the agent is about to act on, so the GDV reads the account
 * numbers and the amount before pressing Duyệt.
 *
 * Values are the ones the GDV typed in this browser. They are masked while browsing (a customer
 * may be standing at the counter) and shown in full on a step that waits for approval, because
 * a decision needs to be read. Values the agent read from the application are never sent here.
 */
import { MODE_HINT, MODE_LABEL, RISK_HINT, RISK_LABEL, captionOf, takesOf, type Taken } from "./flow-graph";
import { STATUS_TEXT, type StepStatus } from "./run-state";
import type { Workflow, WorkflowStep } from "./server-api";

export interface InfoItem {
  /** What the GDV calls it ("Số tiền"). */
  name: string;
  /** Where it comes from, in words. */
  source: string;
  /** The value, or null when it is not known here. */
  value: string | null;
  sensitive: boolean;
  /** Why there is no value, when there is none. */
  missing: string;
}

export interface StepDetail {
  index: number;
  headline: string;
  doing: string;
  status: string;
  takes: InfoItem[];
  gives: { name: string; note: string }[];
  touches: { label: string; hint: string };
  control: { label: string; hint: string };
  /** Everything the agent is about to act on, for a step that waits for approval. */
  summary: InfoItem[] | null;
  /** The step is waiting for the GDV to decide, so the summary is shown in full. */
  deciding: boolean;
}

export const DOING: Record<string, (caption: string) => string> = {
  goto: (c) => `Mở trang ${c}`.trim(),
  click: (c) => `Bấm «${c}»`,
  fill: (c) => `Điền vào ô «${c}»`,
  submit: (c) => `Nhấn Enter trong ô «${c}»`,
  select: (c) => `Chọn trong «${c}»`,
  read_value: (c) => `Đọc thông tin ở «${c}» để dùng ở bước sau`,
  wait_for: (c) => `Chờ «${c}» hiện ra`,
  extract_table: (c) => `Lấy bảng «${c}»`,
  compare: () => "Đối chiếu các thông tin đã lấy",
  save: () => "Lưu kết quả",
};

/** "001076060577" -> "•••••••••577": enough to tell accounts apart, not enough to read them out. */
export function mask(value: string): string {
  if (value.length <= 4) return "•".repeat(Math.max(value.length, 3));
  return "•".repeat(Math.min(value.length - 3, 9)) + value.slice(-3);
}

export function toItem(taken: Taken, values: Record<string, string>): InfoItem {
  if (taken.from === "fixed") {
    return { name: taken.caption, source: "Cố định, theo lần bạn làm mẫu", value: taken.fixed ?? "", sensitive: false, missing: "" };
  }
  if (taken.from === "step") {
    const where = taken.producerIndex === undefined ? "" : `bước ${taken.producerIndex + 1} `;
    return {
      name: taken.caption,
      source: `Agent đọc ở ${where}«${captionOf(taken.producer!)}»`,
      value: null,
      sensitive: true,
      missing: "Agent tự lấy khi chạy, không hiển thị ở đây",
    };
  }
  const input = taken.input!;
  const typed = values[input.name];
  const fallback = input.default !== undefined && input.default !== null ? String(input.default) : null;
  const value = typed !== undefined && typed !== "" ? typed : fallback;
  return {
    name: taken.caption,
    source: typed !== undefined && typed !== "" ? "Bạn đã nhập" : fallback !== null ? "Giá trị thường dùng, bạn đổi được" : "Bạn nhập khi chạy",
    value,
    sensitive: Boolean(input.value_class),
    missing: "Bạn chưa nhập",
  };
}

export function describeStep(
  workflow: Workflow,
  stepId: string,
  values: Record<string, string>,
  status: StepStatus | undefined,
  deciding = false,
): StepDetail | null {
  const index = workflow.steps.findIndex((s) => s.id === stepId);
  if (index < 0) return null;
  const step: WorkflowStep = workflow.steps[index]!;
  const caption = captionOf(step);
  const takes = takesOf(workflow, index).map((t) => toItem(t, values));
  const gives = step.save_as ? [{ name: caption || "Thông tin đã đọc", note: "Dùng ở các bước sau" }] : [];

  let summary: InfoItem[] | null = null;
  if (step.mode === "approve" || step.risk !== "read") {
    // everything the agent has put in or will put in before and at this step
    const seen = new Set<string>();
    summary = [];
    for (let i = 0; i <= index; i++) {
      const earlier = workflow.steps[i]!;
      if (earlier.action !== "fill" && earlier.action !== "select") continue;
      for (const taken of takesOf(workflow, i)) {
        const key = `${taken.from}:${taken.name}:${taken.caption}`;
        if (seen.has(key)) continue;
        seen.add(key);
        summary.push(toItem(taken, values));
      }
    }
  }

  return {
    index: index + 1,
    headline: `Bước ${index + 1}`,
    doing: (DOING[step.action] ?? (() => step.action))(caption),
    status: STATUS_TEXT[status ?? "pending"],
    takes,
    gives,
    touches: { label: RISK_LABEL[step.risk]!, hint: RISK_HINT[step.risk]! },
    control: { label: MODE_LABEL[step.mode]!, hint: MODE_HINT[step.mode]! },
    summary,
    deciding,
  };
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

export interface RenderOptions {
  /** Show sensitive values in full. Off while browsing, on for a step that waits for a decision. */
  reveal: boolean;
  /** The GDV pressed "Hiện" or "Ẩn". */
  onReveal?(reveal: boolean): void;
}

function valueText(item: InfoItem, reveal: boolean): { text: string; known: boolean } {
  if (item.value === null || item.value === "") return { text: item.missing, known: false };
  return { text: item.sensitive && !reveal ? mask(item.value) : item.value, known: true };
}

function renderItems(items: InfoItem[], reveal: boolean): HTMLElement {
  const list = el("dl", "rk-info-list");
  for (const item of items) {
    const row = el("div", "rk-info-row");
    row.append(el("dt", "", item.name));
    const { text, known } = valueText(item, reveal);
    const value = el("dd", known ? "value" : "value missing", text);
    row.append(value, el("small", "source", item.source));
    list.appendChild(row);
  }
  return list;
}

/** Draw the detail. Text only: nothing from the workflow or the values is ever set as HTML. */
export function renderStepDetail(container: HTMLElement, detail: StepDetail | null, options: RenderOptions): void {
  container.replaceChildren();
  if (detail === null) {
    container.appendChild(el("p", "rk-note", "Bấm vào một bước trên màn hình để xem thông tin đi vào bước đó."));
    return;
  }
  const head = el("div", "rk-detail-head");
  head.append(el("b", "", detail.headline), el("span", "rk-detail-status", detail.status));
  container.append(head, el("p", "rk-detail-doing", detail.doing));

  const section = (title: string, ...body: HTMLElement[]) => {
    container.appendChild(el("span", "rk-label", title));
    container.append(...body);
  };

  const showing = options.reveal || detail.deciding;
  if (detail.summary && (detail.deciding || detail.summary.length > 0)) {
    section(detail.deciding ? "Bạn sắp duyệt việc này" : "Agent sẽ dùng các thông tin này", renderItems(detail.summary, showing));
  } else {
    section("Thông tin đi vào bước này", detail.takes.length > 0 ? renderItems(detail.takes, showing) : el("p", "rk-note", "Bước này không cần thông tin nào."));
  }
  if (detail.gives.length > 0) {
    section("Thông tin bước này đưa ra", renderItems(detail.gives.map((g) => ({ name: g.name, source: g.note, value: "Đã lấy", sensitive: false, missing: "" })), true));
  }

  const hasSensitive = (detail.summary ?? detail.takes).some((i) => i.sensitive && i.value);
  if (hasSensitive && !detail.deciding) {
    const toggle = el("button", "rk-link", options.reveal ? "Ẩn bớt thông tin" : "Hiện đầy đủ thông tin");
    toggle.type = "button";
    toggle.addEventListener("click", () => options.onReveal?.(!options.reveal));
    container.appendChild(toggle);
  }
  if (detail.deciding && hasSensitive) {
    container.appendChild(el("p", "rk-note", "Thông tin được hiện đầy đủ để bạn đọc trước khi duyệt."));
  }

  section("Bước này chạm vào", el("p", "rk-detail-line", `${detail.touches.label}. ${detail.touches.hint}`));
  section("Cách agent làm bước này", el("p", "rk-detail-line", `${detail.control.label}. ${detail.control.hint}`));
}
