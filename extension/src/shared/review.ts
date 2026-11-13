/**
 * The review screen: what the GDV sees when a step needs them to look or to approve.
 *
 * It shows the whole picture, not only the one step: a checklist of the work (done, waiting for
 * you, still to come), the information the agent is about to act on, and, for a step that touches
 * money or changes data, a box to tick for each piece of information before Duyệt turns on.
 * The decision is only ever made here.
 */
import { RISK_HINT, RISK_LABEL, captionOf, takesOf } from "./flow-graph";
import { DOING, mask, toItem, type InfoItem } from "./step-detail";
import type { RunState } from "./run-state";
import type { Workflow } from "./server-api";

export interface TimelineEntry {
  index: number;
  text: string;
  state: "done" | "now" | "later";
}

export interface ReviewModel {
  stepId: string;
  kind: "approve" | "review";
  title: string;
  question: string;
  risk: { level: string; label: string; hint: string };
  timeline: TimelineEntry[];
  /** Everything the agent is about to act on. Empty for a step that only asks the GDV to look. */
  facts: InfoItem[];
  /** The facts the GDV must tick before approving: only for steps that touch money or change data. */
  mustCheck: InfoItem[];
  /** For a step the GDV only looks at: where to look. */
  lookAt: string;
}

const step = (workflow: Workflow, index: number) => workflow.steps[index]!;
const doingText = (workflow: Workflow, index: number) => (DOING[step(workflow, index).action] ?? (() => step(workflow, index).action))(captionOf(step(workflow, index)));

export function buildReview(workflow: Workflow, state: RunState, values: Record<string, string>, screenTitle = ""): ReviewModel | null {
  const waiting = state.waiting;
  if (!waiting) return null;
  const at = workflow.steps.findIndex((s) => s.id === waiting.stepId);
  if (at < 0) return null;
  const current = step(workflow, at);
  const asks = waiting.kind === "approve";

  const timeline: TimelineEntry[] = workflow.steps.map((_, index) => ({
    index: index + 1,
    text: doingText(workflow, index),
    // a step the GDV only looks at has already been done; a step to approve has not
    state: index < at || (index === at && !asks) ? "done" : index === at ? "now" : "later",
  }));

  const facts: InfoItem[] = [];
  if (asks) {
    const seen = new Set<string>();
    for (let i = 0; i <= at; i++) {
      if (step(workflow, i).action !== "fill" && step(workflow, i).action !== "select") continue;
      for (const taken of takesOf(workflow, i)) {
        const key = `${taken.from}:${taken.name}:${taken.caption}`;
        if (seen.has(key)) continue;
        seen.add(key);
        facts.push(toItem(taken, values));
      }
    }
  }
  const strict = asks && current.risk !== "read";
  const mustCheck = strict ? facts.filter((f) => f.sensitive && f.value) : [];
  const caption = captionOf(current);
  return {
    stepId: current.id,
    kind: waiting.kind,
    title: asks ? `Bạn sắp duyệt: ${doingText(workflow, at)}` : `Xem kết quả: ${doingText(workflow, at)}`,
    question: asks
      ? "Agent đã làm đến đây và đang chờ bạn. Hãy kiểm tra rồi quyết định."
      : `Agent đã làm xong «${caption}». Hãy nhìn kết quả trên màn hình${screenTitle ? ` «${screenTitle}»` : " ứng dụng"} rồi quyết định.`,
    risk: { level: current.risk, label: RISK_LABEL[current.risk]!, hint: RISK_HINT[current.risk]! },
    timeline,
    facts,
    mustCheck,
    lookAt: asks ? "" : screenTitle,
  };
}

export interface ReviewHandlers {
  onDecision(approve: boolean): void;
  /** The GDV went back to look at the flow without deciding. The step keeps waiting. */
  onClose?(): void;
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

const MARK: Record<TimelineEntry["state"], string> = { done: "✓", now: "▶", later: "○" };
const STATE_WORD: Record<TimelineEntry["state"], string> = { done: "Đã làm", now: "Chờ bạn", later: "Sẽ làm sau" };

export class ReviewView {
  private readonly root = el("div", "rk-review");
  private open = false;
  private model: ReviewModel | null = null;
  private checked = new Set<string>();
  private masked = false;
  private previouslyFocused: HTMLElement | null = null;

  constructor(host: HTMLElement, private readonly handlers: ReviewHandlers) {
    this.root.setAttribute("role", "dialog");
    this.root.setAttribute("aria-modal", "true");
    this.root.hidden = true;
    this.root.addEventListener("keydown", (event) => {
      if (event.key === "Escape") this.close(); // looking away is not a decision
    });
    host.appendChild(this.root);
  }

  get isOpen(): boolean {
    return this.open;
  }

  /** Show the review for a waiting step. The same step shown again keeps the ticks already made. */
  show(model: ReviewModel): void {
    if (this.model?.stepId !== model.stepId) {
      this.checked = new Set();
      this.masked = false;
    }
    this.model = model;
    this.open = true;
    this.root.hidden = false;
    this.previouslyFocused = (document.activeElement as HTMLElement | null) ?? null;
    this.render();
    this.root.querySelector<HTMLElement>("input[type=checkbox], .rk-go")?.focus();
  }

  /** Close without a decision (the GDV went back to the flow, or the step is no longer waiting). */
  close(): void {
    if (!this.open) return;
    this.open = false;
    this.root.hidden = true;
    this.previouslyFocused?.focus?.();
    this.handlers.onClose?.();
  }

  /** The step was decided or the run ended: hide without telling anyone. */
  dismiss(): void {
    this.open = false;
    this.model = null;
    this.root.hidden = true;
    this.root.replaceChildren();
  }

  private ticksNeeded(): number {
    return this.model ? this.model.mustCheck.filter((_, i) => !this.checked.has(String(i))).length : 0;
  }

  private render(): void {
    const model = this.model;
    if (!model) return;
    this.root.setAttribute("aria-label", model.title);
    const card = el("div", "rk-review-card");

    const head = el("header", "rk-review-head");
    const tag = el("span", `rk-badge risk-${model.risk.level}`, model.risk.label);
    tag.title = model.risk.hint;
    const back = el("button", "rk-link", "Xem lại luồng");
    back.type = "button";
    back.addEventListener("click", () => this.close());
    head.append(tag, el("h2", "", model.title), el("p", "rk-review-question", model.question), back);

    const body = el("div", "rk-review-body");
    body.append(this.timelineSection(model), model.kind === "approve" ? this.factsSection(model) : this.lookSection(model));

    const foot = el("footer", "rk-review-foot");
    const no = el("button", "rk-no", model.kind === "approve" ? "Không duyệt" : "Dừng");
    no.type = "button";
    no.addEventListener("click", () => this.handlers.onDecision(false));
    const go = el("button", "rk-go", model.kind === "approve" ? "Duyệt" : "Đi tiếp");
    go.type = "button";
    const left = this.ticksNeeded();
    go.disabled = left > 0;
    go.addEventListener("click", () => this.handlers.onDecision(true));
    const note = el("span", "rk-review-need", left > 0 ? `Còn ${left} mục chưa kiểm tra` : model.mustCheck.length > 0 ? "Đã kiểm tra đủ, có thể duyệt" : "");
    note.setAttribute("role", "status");
    foot.append(note, no, go);

    card.append(head, body, foot);
    this.root.replaceChildren(card);
  }

  private timelineSection(model: ReviewModel): HTMLElement {
    const section = el("section", "rk-review-col");
    section.appendChild(el("h3", "", "Toàn bộ việc"));
    const list = el("ol", "rk-timeline");
    for (const entry of model.timeline) {
      const item = el("li", `rk-tl ${entry.state}`);
      const mark = el("span", "mark", MARK[entry.state]);
      mark.setAttribute("aria-hidden", "true");
      const text = el("span", "text", entry.text);
      const state = el("small", "state", STATE_WORD[entry.state]);
      item.append(mark, text, state);
      list.appendChild(item);
    }
    section.appendChild(list);
    return section;
  }

  private factsSection(model: ReviewModel): HTMLElement {
    const section = el("section", "rk-review-col");
    section.appendChild(el("h3", "", model.mustCheck.length > 0 ? "Kiểm tra từng thông tin" : "Thông tin agent sẽ dùng"));
    if (model.facts.length === 0) {
      section.appendChild(el("p", "rk-note", "Bước này không dùng thông tin nào do bạn nhập."));
      return section;
    }
    const list = el("ul", "rk-checks");
    const required = new Map(model.mustCheck.map((item, i) => [item, String(i)]));
    for (const fact of model.facts) {
      const row = el("li", "rk-check");
      const label = el("label");
      const tickId = required.get(fact);
      if (tickId !== undefined) {
        const box = document.createElement("input");
        box.type = "checkbox";
        box.checked = this.checked.has(tickId);
        box.setAttribute("aria-label", `Đã kiểm tra ${fact.name}`);
        box.addEventListener("change", () => {
          if (box.checked) this.checked.add(tickId);
          else this.checked.delete(tickId);
          this.render();
          this.root.querySelectorAll<HTMLInputElement>("input[type=checkbox]")[Number(tickId)]?.focus();
        });
        label.appendChild(box);
      }
      const text = el("span", "what");
      text.append(el("b", "", fact.name), el("small", "", fact.source));
      const known = fact.value !== null && fact.value !== "";
      const shown = known ? (this.masked && fact.sensitive ? mask(fact.value!) : fact.value!) : fact.missing;
      label.append(text, el("span", known ? "value" : "value missing", shown));
      row.appendChild(label);
      list.appendChild(row);
    }
    section.appendChild(list);
    if (model.facts.some((f) => f.sensitive && f.value)) {
      const toggle = el("button", "rk-link", this.masked ? "Hiện thông tin" : "Che thông tin (có khách đứng cạnh)");
      toggle.type = "button";
      toggle.addEventListener("click", () => {
        this.masked = !this.masked;
        this.render();
      });
      section.appendChild(toggle);
    }
    return section;
  }

  private lookSection(model: ReviewModel): HTMLElement {
    const section = el("section", "rk-review-col");
    section.appendChild(el("h3", "", "Việc bạn cần làm"));
    section.appendChild(
      el(
        "p",
        "rk-detail-line",
        model.lookAt ? `Nhìn vào màn hình «${model.lookAt}» của ứng dụng để xem kết quả agent vừa làm.` : "Nhìn vào màn hình ứng dụng để xem kết quả agent vừa làm.",
      ),
    );
    section.appendChild(el("p", "rk-detail-line", "Thấy đúng thì bấm Đi tiếp. Thấy sai hoặc lạ thì bấm Dừng, agent sẽ không làm thêm gì."));
    return section;
  }
}
