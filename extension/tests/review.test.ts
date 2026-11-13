import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReviewView, buildReview } from "../src/shared/review";
import { idleState, reduce, startedState, type RunState } from "../src/shared/run-state";
import { describeStep, mask, renderStepDetail } from "../src/shared/step-detail";
import type { Workflow, WorkflowStep } from "../src/shared/server-api";

const step = (id: string, action: string, label: string, extra: Partial<WorkflowStep> = {}): WorkflowStep => ({
  id,
  action,
  target: { selectors: ["#x"], label },
  risk: "read",
  mode: "auto",
  ...extra,
});

/** Look up a customer, then make a transfer: the money step waits for approval. */
const transfer: Workflow = {
  schema_version: 1,
  engine: "java",
  id: "chuyen-tien",
  title: "Tra CIF và lập lệnh chuyển tiền",
  version: 1,
  status: "approved",
  inputs: [
    { name: "so_cif", label: "Số CIF", type: "string", value_class: "cif_number" },
    { name: "tai_khoan_chuyen", label: "Tài khoản chuyển", type: "string", value_class: "account_number" },
    { name: "tai_khoan_nhan", label: "Tài khoản nhận", type: "string", value_class: "account_number" },
    { name: "so_tien", label: "Số tiền", type: "string", value_class: "amount" },
    { name: "ghi_chu", label: "Nội dung", type: "string", default: "Chuyển khoản" },
  ],
  steps: [
    step("s1", "fill", "Số CIF", { value: "{so_cif}" }),
    step("s2", "click", "Tra cứu CIF", { mode: "review" }),
    step("s3", "fill", "Tài khoản chuyển", { value: "{tai_khoan_chuyen}" }),
    step("s4", "fill", "Tài khoản nhận", { value: "{tai_khoan_nhan}" }),
    step("s5", "fill", "Số tiền", { value: "{so_tien}" }),
    step("s6", "select", "Loại tiền", { value: "USD" }),
    step("s7", "fill", "Nội dung", { value: "{ghi_chu}" }),
    step("s8", "click", "Gửi duyệt", { risk: "money", mode: "approve" }),
  ],
};
const VALUES = { so_cif: "00103840", tai_khoan_chuyen: "001076060577", tai_khoan_nhan: "002033605304", so_tien: "5000000" };

function waitingAt(stepId: string, kind: "approve" | "review", done: string[]): RunState {
  let state = startedState(false);
  for (const id of done) state = reduce(state, { event: "progress", step_id: id, status: "done" });
  return reduce(state, { event: "waiting", kind, step_id: stepId, label: null, risk: "money" });
}
const ALL_BEFORE_S8 = ["s1", "s2", "s3", "s4", "s5", "s6", "s7"];

describe("mask", () => {
  it("keeps the last three characters so accounts can be told apart, and hides the rest", () => {
    expect(mask("001076060577")).toBe("•••••••••577");
    expect(mask("5000000")).toBe("••••000");
    expect(mask("12")).toBe("•••");
    expect(mask("00103840").endsWith("840")).toBe(true);
    expect(mask("0".repeat(40)).length).toBe(12); // never as long as the value
  });
});

describe("describeStep", () => {
  it("says what the step does and what it may touch, in plain words", () => {
    const detail = describeStep(transfer, "s5", VALUES, "done")!;
    expect(detail.headline).toBe("Bước 5");
    expect(detail.doing).toBe("Điền vào ô «Số tiền»");
    expect(detail.status).toBe("Xong");
    expect(detail.touches.label).toBe("Chỉ xem");
    expect(detail.control.label).toBe("Tự làm");
  });

  it("lists the information that goes into a step and where it comes from", () => {
    const [taken] = describeStep(transfer, "s5", VALUES, undefined)!.takes;
    expect(taken).toMatchObject({ name: "Số tiền", source: "Bạn đã nhập", value: "5000000", sensitive: true });
    const [empty] = describeStep(transfer, "s5", {}, undefined)!.takes;
    expect(empty).toMatchObject({ source: "Bạn nhập khi chạy", value: null, missing: "Bạn chưa nhập" });
    const [usual] = describeStep(transfer, "s7", {}, undefined)!.takes;
    expect(usual).toMatchObject({ name: "Nội dung", value: "Chuyển khoản", source: "Giá trị thường dùng, bạn đổi được", sensitive: false });
  });

  it("shows a value fixed when the work was demonstrated, and a value the agent read itself", () => {
    const [fixed] = describeStep(transfer, "s6", VALUES, undefined)!.takes;
    expect(fixed).toMatchObject({ name: "Loại tiền", value: "USD", source: "Cố định, theo lần bạn làm mẫu", sensitive: false });
    const flow: Workflow = {
      ...transfer,
      steps: [step("r1", "read_value", "Tài khoản thanh toán", { save_as: "tk" }), step("r2", "fill", "Tài khoản chuyển", { value: "{tk}" })],
    };
    const read = describeStep(flow, "r1", {}, undefined)!;
    expect(read.gives).toEqual([{ name: "Tài khoản thanh toán", note: "Dùng ở các bước sau" }]);
    const [used] = describeStep(flow, "r2", {}, undefined)!.takes;
    expect(used.source).toBe("Agent đọc ở bước 1 «Tài khoản thanh toán»");
    expect(used.value).toBeNull(); // the agent's reading never reaches the panel
    expect(used.missing).toContain("không hiển thị");
  });

  it("gives the whole list of what will be acted on for a step that asks for approval", () => {
    const detail = describeStep(transfer, "s8", VALUES, "waiting_approval", true)!;
    expect(detail.summary!.map((i) => i.name)).toEqual(["Số CIF", "Tài khoản chuyển", "Tài khoản nhận", "Số tiền", "Loại tiền", "Nội dung"]);
    expect(describeStep(transfer, "s5", VALUES, undefined)!.summary).toBeNull(); // a step that only reads has no summary
    expect(describeStep(transfer, "khong-co", VALUES, undefined)).toBeNull();
  });
});

describe("renderStepDetail", () => {
  let box: HTMLElement;
  beforeEach(() => {
    document.body.replaceChildren();
    box = document.createElement("div");
    document.body.appendChild(box);
  });

  it("hides sensitive values while browsing and shows them when asked", () => {
    const reveal: boolean[] = [];
    const draw = (on: boolean) => renderStepDetail(box, describeStep(transfer, "s5", VALUES, "done"), { reveal: on, onReveal: (r) => reveal.push(r) });
    draw(false);
    expect(box.textContent).toContain("••••000");
    expect(box.textContent).not.toContain("5000000");
    box.querySelector<HTMLButtonElement>("button.rk-link")!.click();
    expect(reveal).toEqual([true]);
    draw(true);
    expect(box.textContent).toContain("5000000");
    expect(box.querySelector("button.rk-link")!.textContent).toBe("Ẩn bớt thông tin");
  });

  it("shows everything on a step that waits for a decision, with no way to hide it", () => {
    renderStepDetail(box, describeStep(transfer, "s8", VALUES, "waiting_approval", true), { reveal: false });
    expect(box.textContent).toContain("Bạn sắp duyệt việc này");
    expect(box.textContent).toContain("5000000");
    expect(box.textContent).toContain("001076060577");
    expect(box.querySelector("button.rk-link")).toBeNull();
  });

  it("invites the GDV to pick a step when none is chosen, and never turns text into markup", () => {
    renderStepDetail(box, null, { reveal: false });
    expect(box.textContent).toContain("Bấm vào một bước");
    const hostile: Workflow = { ...transfer, steps: [step("x", "click", "<img src=x onerror=alert(1)>")] };
    renderStepDetail(box, describeStep(hostile, "x", {}, undefined), { reveal: false });
    expect(box.querySelector("img")).toBeNull();
    expect(box.textContent).toContain("<img src=x onerror=alert(1)>");
  });
});

describe("buildReview", () => {
  it("has nothing to review when nobody is waiting", () => {
    expect(buildReview(transfer, idleState(), VALUES)).toBeNull();
    expect(buildReview(transfer, startedState(false), VALUES)).toBeNull();
  });

  it("lays out the whole work: done, waiting for the GDV, still to come", () => {
    const review = buildReview(transfer, waitingAt("s5", "approve", ["s1", "s2", "s3", "s4"]), VALUES)!;
    expect(review.timeline.map((t) => t.state)).toEqual(["done", "done", "done", "done", "now", "later", "later", "later"]);
    expect(review.timeline[4]).toEqual({ index: 5, text: "Điền vào ô «Số tiền»", state: "now" });
    expect(review.title).toBe("Bạn sắp duyệt: Điền vào ô «Số tiền»");
  });

  it("asks the GDV to tick every piece of sensitive information on a step that touches money", () => {
    const review = buildReview(transfer, waitingAt("s8", "approve", ALL_BEFORE_S8), VALUES)!;
    expect(review.risk).toMatchObject({ level: "money", label: "Liên quan tiền" });
    expect(review.facts.map((f) => f.name)).toEqual(["Số CIF", "Tài khoản chuyển", "Tài khoản nhận", "Số tiền", "Loại tiền", "Nội dung"]);
    expect(review.mustCheck.map((f) => f.name)).toEqual(["Số CIF", "Tài khoản chuyển", "Tài khoản nhận", "Số tiền"]);
  });

  it("does not make the GDV tick anything for a step that only reads, and cannot tick what it cannot see", () => {
    const reading: Workflow = { ...transfer, steps: transfer.steps.map((s) => (s.id === "s3" ? { ...s, mode: "approve" as const } : s)) };
    expect(buildReview(reading, waitingAt("s3", "approve", ["s1", "s2"]), VALUES)!.mustCheck).toEqual([]);
    const unseen = buildReview(transfer, waitingAt("s8", "approve", ALL_BEFORE_S8), {})!;
    expect(unseen.mustCheck).toEqual([]); // nothing typed here: nothing to tick, and the missing values are shown as such
    expect(unseen.facts.every((f) => f.value === null || f.value === "USD" || f.value === "Chuyển khoản")).toBe(true);
  });

  it("for a step the GDV only looks at, says where to look and treats it as already done", () => {
    const review = buildReview(transfer, waitingAt("s2", "review", ["s1", "s2"]), VALUES, "Mock TPSS - Khách hàng (CIF)")!;
    expect(review.kind).toBe("review");
    expect(review.timeline.map((t) => t.state).slice(0, 3)).toEqual(["done", "done", "later"]);
    expect(review.title).toBe("Xem kết quả: Bấm «Tra cứu CIF»");
    expect(review.question).toContain("«Mock TPSS - Khách hàng (CIF)»");
    expect(review.facts).toEqual([]);
    expect(review.mustCheck).toEqual([]);
  });
});

describe("ReviewView", () => {
  let host: HTMLElement;
  let decisions: boolean[];
  let closed: number;
  let view: ReviewView;
  const approve = () => buildReview(transfer, waitingAt("s8", "approve", ALL_BEFORE_S8), VALUES)!;

  beforeEach(() => {
    document.body.replaceChildren();
    host = document.createElement("div");
    document.body.appendChild(host);
    decisions = [];
    closed = 0;
    view = new ReviewView(host, { onDecision: (a) => decisions.push(a), onClose: () => closed++ });
  });

  const go = () => host.querySelector<HTMLButtonElement>(".rk-go")!;
  const boxes = () => [...host.querySelectorAll<HTMLInputElement>("input[type=checkbox]")];

  it("is closed until a step waits, and is a dialog when it opens", () => {
    expect(host.querySelector<HTMLElement>(".rk-review")!.hidden).toBe(true);
    view.show(approve());
    const dialog = host.querySelector<HTMLElement>(".rk-review")!;
    expect(dialog.hidden).toBe(false);
    expect(dialog.getAttribute("role")).toBe("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.getAttribute("aria-label")).toContain("Bạn sắp duyệt");
  });

  it("shows the checklist of the whole work and the information to check", () => {
    view.show(approve());
    expect([...host.querySelectorAll(".rk-tl")].map((e) => e.className.replace("rk-tl ", ""))).toEqual(["done", "done", "done", "done", "done", "done", "done", "now"]);
    expect(host.querySelector(".rk-tl.now")!.textContent).toContain("Bấm «Gửi duyệt»");
    expect(host.querySelector(".rk-review-col:nth-child(2)")!.textContent).toContain("5000000");
    expect(host.textContent).toContain("Liên quan tiền");
    expect(boxes()).toHaveLength(4);
  });

  it("keeps Duyệt off until every item is ticked, and says how many are left", () => {
    view.show(approve());
    expect(go().disabled).toBe(true);
    expect(host.querySelector(".rk-review-need")!.textContent).toBe("Còn 4 mục chưa kiểm tra");
    boxes().slice(0, 3).forEach((box) => {
      box.checked = true;
      box.dispatchEvent(new Event("change"));
    });
    expect(go().disabled).toBe(true);
    expect(host.querySelector(".rk-review-need")!.textContent).toBe("Còn 1 mục chưa kiểm tra");
    const last = boxes()[3]!;
    last.checked = true;
    last.dispatchEvent(new Event("change"));
    expect(go().disabled).toBe(false);
    expect(host.querySelector(".rk-review-need")!.textContent).toBe("Đã kiểm tra đủ, có thể duyệt");
    go().click();
    expect(decisions).toEqual([true]);
  });

  it("lets the GDV refuse at any time without ticking anything", () => {
    view.show(approve());
    host.querySelector<HTMLButtonElement>(".rk-no")!.click();
    expect(decisions).toEqual([false]);
  });

  it("looking away is not a decision: Escape and 'Xem lại luồng' close it and the step keeps waiting", () => {
    view.show(approve());
    host.querySelector<HTMLButtonElement>("header .rk-link")!.click();
    expect(closed).toBe(1);
    expect(host.querySelector<HTMLElement>(".rk-review")!.hidden).toBe(true);
    expect(decisions).toEqual([]);
    view.show(approve());
    host.querySelector(".rk-review")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(closed).toBe(2);
    expect(decisions).toEqual([]);
    view.close(); // already closed: nothing happens
    expect(closed).toBe(2);
  });

  it("keeps the ticks when the same step is shown again, and starts clean for another step", () => {
    view.show(approve());
    boxes()[0]!.checked = true;
    boxes()[0]!.dispatchEvent(new Event("change"));
    view.close();
    view.show(approve());
    expect(boxes()[0]!.checked).toBe(true);
    expect(host.querySelector(".rk-review-need")!.textContent).toBe("Còn 3 mục chưa kiểm tra");
    const other = buildReview({ ...transfer, steps: transfer.steps.map((s) => (s.id === "s5" ? { ...s, risk: "write" as const, mode: "approve" as const } : s)) }, waitingAt("s5", "approve", ["s1", "s2", "s3", "s4"]), VALUES)!;
    view.show(other);
    expect(boxes().some((b) => b.checked)).toBe(false);
  });

  it("can hide the values when a customer stands next to the screen", () => {
    view.show(approve());
    expect(host.textContent).toContain("001076060577");
    const toggle = [...host.querySelectorAll<HTMLButtonElement>("button.rk-link")].find((b) => b.textContent!.startsWith("Che thông tin"))!;
    toggle.click();
    expect(host.textContent).not.toContain("001076060577");
    expect(host.textContent).toContain("•••••••••577");
    expect(host.textContent).toContain("Hiện thông tin");
    expect(boxes()).toHaveLength(4); // the ticks are still there
  });

  it("for a step to look at: no boxes, the decision is Đi tiếp or Dừng, and it says where to look", () => {
    view.show(buildReview(transfer, waitingAt("s2", "review", ["s1", "s2"]), VALUES, "Mock TPSS - Khách hàng (CIF)")!);
    expect(boxes()).toHaveLength(0);
    expect(go().textContent).toBe("Đi tiếp");
    expect(go().disabled).toBe(false);
    expect(host.querySelector(".rk-no")!.textContent).toBe("Dừng");
    expect(host.textContent).toContain("Nhìn vào màn hình «Mock TPSS - Khách hàng (CIF)»");
    go().click();
    expect(decisions).toEqual([true]);
  });

  it("is emptied without a word when the step has been decided elsewhere", () => {
    view.show(approve());
    view.dismiss();
    expect(view.isOpen).toBe(false);
    expect(host.querySelector(".rk-review")!.children).toHaveLength(0);
    expect(closed).toBe(0);
  });

  it("uses plain wording and never turns text into markup", () => {
    view.show(approve());
    expect(host.textContent).not.toMatch(/risk|mode|sandbox|mock\b|selector|s\d\b/i);
    const hostile = buildReview({ ...transfer, steps: [step("s1", "click", "<b>x</b>", { risk: "money", mode: "approve" })] }, waitingAt("s1", "approve", []), {})!;
    view.show(hostile);
    expect(host.querySelector(".rk-review b")).toBeNull();
    expect(vi.isMockFunction(console.log)).toBe(false);
  });
});
