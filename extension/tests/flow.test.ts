/// <reference types="vite/client" />
import { beforeEach, describe, expect, it, vi } from "vitest";
import { describeResult } from "../src/shared/friendly";
import { FlowCanvas, type Drawing, type LayoutStore, type Positions } from "../src/shared/flow-canvas";
import {
  NODE_H,
  NODE_W,
  PER_ROW,
  READABLE_ZOOM,
  buildGraph,
  captionOf,
  connect,
  ensureVisible,
  fitView,
  humanize,
  placeholdersOf,
  readableView,
  sidesFor,
} from "../src/shared/flow-graph";
import { idleState, reduce, startedState } from "../src/shared/run-state";
import type { Workflow } from "../src/shared/server-api";

const examples = import.meta.glob("../../schemas/examples/valid/workflow-*.json", { eager: true, import: "default" }) as Record<string, Workflow>;
const javaFlow = examples["../../schemas/examples/valid/workflow-java.json"]!;
const webFlow = examples["../../schemas/examples/valid/workflow-web.json"]!;

/** A flow of `count` read steps then one money step, long enough to wrap into rows. */
function longFlow(count: number): Workflow {
  const steps = Array.from({ length: count }, (_, i) => ({
    id: `s${i + 1}`,
    action: "click",
    target: { selectors: ["#x"], label: `Nút ${i + 1}` },
    risk: "read" as const,
    mode: "auto" as const,
  }));
  return { ...javaFlow, inputs: [], steps };
}

describe("buildGraph", () => {
  it("makes one node per step and per piece of information", () => {
    const graph = buildGraph(javaFlow);
    expect(graph.nodes.filter((n) => n.kind === "param").map((n) => n.id)).toEqual(["param:so_cif", "param:tai_khoan_nhan", "param:so_tien"]);
    expect(graph.nodes.filter((n) => n.kind === "step").map((n) => n.id)).toEqual(javaFlow.steps.map((s) => s.id));
  });

  it("shows a field by the caption the GDV sees, not by its internal name", () => {
    const subtitles = buildGraph(javaFlow).nodes.filter((n) => n.kind === "param").map((n) => n.subtitle);
    expect(subtitles).toEqual(["Số CIF", "Tai khoan nhan", "So tien"]); // the first has a caption; the others fall back to a readable name
    expect(humanize("so_tien")).toBe("So tien");
  });

  it("lays steps out in a snake, four to a row, so a long flow still fits one screen", () => {
    const nodes = buildGraph(longFlow(10)).nodes;
    const at = (i: number) => nodes[i]!;
    expect([0, 1, 2, 3].map((i) => at(i).x)).toEqual([0, 304, 608, 912]); // row 0 runs left to right
    expect([4, 5, 6, 7].map((i) => at(i).x)).toEqual([912, 608, 304, 0]); // row 1 runs right to left
    expect([8, 9].map((i) => at(i).x)).toEqual([0, 304]); // row 2 again
    expect(at(4).x).toBe(at(3).x); // the drop from one row to the next is straight down
    expect(at(8).x).toBe(at(7).x);
    expect(new Set([0, 1, 2, 3].map((i) => at(i).y)).size).toBe(1);
    expect(at(4).y).toBeGreaterThan(at(0).y + NODE_H);
    expect(nodes.map((n) => n.flip)).toEqual([false, false, false, false, true, true, true, true, false, false]);
    expect(PER_ROW).toBe(4);
  });

  it("puts the information the GDV gives above the steps, in rows of four too", () => {
    const flow = { ...javaFlow, inputs: Array.from({ length: 5 }, (_, i) => ({ name: `f${i}`, type: "string" })) };
    const graph = buildGraph(flow);
    const infos = graph.nodes.filter((n) => n.kind === "param");
    const steps = graph.nodes.filter((n) => n.kind === "step");
    expect(infos.map((n) => n.y)).toEqual([0, 0, 0, 0, NODE_H + 36]);
    expect(Math.max(...infos.map((n) => n.y + n.h))).toBeLessThan(Math.min(...steps.map((n) => n.y)));
  });

  it("joins steps in order and draws where a value is used", () => {
    const edges = buildGraph(javaFlow).edges;
    expect(edges.filter((e) => e.kind === "flow")).toHaveLength(javaFlow.steps.length - 1);
    const data = edges.filter((e) => e.kind === "data").map((e) => `${e.from}->${e.to}:${e.carries}`);
    expect(data).toContain("param:so_cif->fill_cif:so_cif");
    expect(data).toContain("read_account->fill_from:tai_khoan_chuyen");
  });

  it("follows values through compare and tolerance in a web flow", () => {
    const data = buildGraph(webFlow).edges.filter((e) => e.kind === "data").map((e) => `${e.from}->${e.to}:${e.carries}`);
    expect(data).toContain("param:ngay->set_date_a:ngay");
    expect(data).toContain("param:nguong_lech->compare:nguong_lech");
    expect(data).toContain("extract_a->compare:bao_cao_a");
    expect(data.some((d) => d.endsWith("bao_cao_b"))).toBe(false);
  });

  it("names steps in plain Vietnamese", () => {
    const titles = buildGraph(javaFlow).nodes.filter((n) => n.kind === "step").map((n) => n.title);
    expect(titles).toEqual(["Điền", "Bấm", "Chờ màn hình", "Lấy thông tin", "Điền", "Bấm"]);
  });

  it("names a target by its caption, then by the name inside its selector, then by the page", () => {
    const base = { id: "s", action: "click", risk: "read", mode: "auto" } as const;
    expect(captionOf({ ...base, target: { selectors: ["#x"], label: "Tìm kiếm" } })).toBe("Tìm kiếm");
    expect(captionOf({ ...base, target: { selectors: ["#x", "role=push button[name='Gửi duyệt']"] } })).toBe("Gửi duyệt");
    expect(captionOf({ ...base, target: { selectors: ["label=Ngày báo cáo"] } })).toBe("Ngày báo cáo");
    expect(captionOf({ ...base, action: "goto", url: "/baocao" })).toBe("/baocao");
    expect(captionOf({ ...base, target: { selectors: ["#x"] } })).toBe("");
  });

  it("finds placeholders", () => {
    expect(placeholdersOf("{a} và {b_2}, {Bad}")).toEqual(["a", "b_2"]);
    expect(placeholdersOf(undefined)).toEqual([]);
  });
});

describe("lines", () => {
  const node = (row: number, flip = false) => ({ row, flip, kind: "step" as const });
  const flow = { id: "e", from: "a", to: "b", kind: "flow" as const };
  const data = { ...flow, kind: "data" as const };

  it("choose the sides to leave and arrive by", () => {
    expect(sidesFor(flow, node(0), node(0))).toEqual(["right", "left"]);
    expect(sidesFor(flow, node(1, true), node(1, true))).toEqual(["left", "right"]); // a row that runs right to left
    expect(sidesFor(flow, node(0), node(1, true))).toEqual(["bottom", "top"]); // the drop to the next row
    expect(sidesFor(data, node(0), node(0))).toEqual(["bottom", "bottom"]); // a U under the row, never across a node
    expect(sidesFor(data, { row: -1, flip: false, kind: "param" }, node(0))).toEqual(["bottom", "top"]);
  });

  it("leave a port along its own direction", () => {
    expect(connect({ x: 0, y: 0 }, "right", { x: 300, y: 0 }, "left")).toBe("M 0 0 C 150 0, 150 0, 300 0");
    expect(connect({ x: 0, y: 0 }, "bottom", { x: 0, y: 200 }, "top")).toBe("M 0 0 C 0 100, 0 100, 0 200");
    expect(connect({ x: 300, y: 0 }, "left", { x: 0, y: 0 }, "right")).toBe("M 300 0 C 150 0, 150 0, 0 0");
    expect(connect({ x: 0, y: 0 }, "right", { x: 10, y: 0 }, "left")).toBe("M 0 0 C 50 0, -40 0, 10 0"); // minimum reach
    expect(connect({ x: 0, y: 0 }, "bottom", { x: 100, y: 0 }, "bottom")).toBe("M 0 0 C 0 50, 100 50, 100 0");
  });
});

describe("camera", () => {
  const long = Array.from({ length: 8 }, (_, i) => ({ x: i * 304, y: 242, w: 232, h: 122 }));

  it("fits every node into the view and never zooms in past 1", () => {
    const nodes = [{ x: 0, y: 0, w: 200, h: 100 }, { x: 1800, y: 300, w: 200, h: 100 }];
    const view = fitView(nodes, 800, 600);
    expect(view.k).toBeCloseTo((800 - 96) / 2000, 5);
    expect(2000 * view.k + view.x).toBeLessThanOrEqual(800);
    expect(fitView([{ x: 0, y: 0, w: 10, h: 10 }], 800, 600).k).toBe(1);
    expect(fitView([], 0, 0)).toEqual({ x: 48, y: 48, k: 1 });
  });

  it("opens a short flow showing everything, a long one at a readable size from the top left", () => {
    const few = long.slice(0, 3);
    expect(readableView(few, 1200, 700)).toEqual(fitView(few, 1200, 700));
    const view = readableView(long, 1170, 860);
    expect(view.k).toBe(READABLE_ZOOM);
    expect(view.x).toBeCloseTo(48, 5);
  });

  it("a flow of eight steps in the snake fits a normal screen at a readable size without moving the camera", () => {
    const graph = buildGraph(longFlow(8));
    const view = readableView(graph.nodes, 1170, 800);
    expect(view.k).toBeGreaterThanOrEqual(READABLE_ZOOM);
  });

  it("does not move when the step is already comfortably on screen", () => {
    const view = { x: 0, y: 0, k: 1 };
    expect(ensureVisible(view, { x: 400, y: 300, w: 232, h: 122 }, 1170, 800)).toBe(view);
  });

  it("slides by the least that brings a step back, with room to spare", () => {
    const view = { x: 0, y: 0, k: 1 };
    const right = ensureVisible(view, { x: 1100, y: 300, w: 232, h: 122 }, 1170, 800);
    expect(1100 + 232 + right.x).toBe(1170 - 40);
    expect(right.y).toBe(0);
    const below = ensureVisible(view, { x: 400, y: 900, w: 232, h: 122 }, 1170, 800);
    expect(900 + 122 + below.y).toBe(800 - 40);
    expect(ensureVisible(view, { x: 0, y: 0, w: 232, h: 122 }, 0, 0)).toBe(view); // no size yet: leave it
  });
});

describe("reduce", () => {
  it("follows a run to its end", () => {
    let s = startedState(false);
    s = reduce(s, { event: "progress", step_id: "a", status: "running" });
    expect(s.current).toBe("a");
    s = reduce(s, { event: "progress", step_id: "a", status: "done" });
    s = reduce(s, { event: "progress", step_id: "b", status: "waiting_approval" });
    s = reduce(s, { event: "waiting", kind: "approve", step_id: "b", label: "Gửi duyệt", risk: "money" });
    expect(s.waiting).toEqual({ kind: "approve", stepId: "b", label: "Gửi duyệt", risk: "money" });
    s = reduce(s, { event: "progress", step_id: "b", status: "running" });
    expect(s.waiting).toBeNull();
    s = reduce(s, { event: "finished", status: "finished", message: "Đã chạy xong 2 bước." });
    expect(s.phase).toBe("finished");
  });

  it("finishes a step that was waiting for a look once the agent moves on", () => {
    let s = startedState(false);
    s = reduce(s, { event: "progress", step_id: "a", status: "done" });
    s = reduce(s, { event: "progress", step_id: "a", status: "waiting_review" });
    expect(s.steps["a"]).toBe("waiting_review");
    s = reduce(s, { event: "progress", step_id: "b", status: "running" });
    expect(s.steps).toEqual({ a: "done", b: "running" });
    // and if the run ends right after the look
    let t = reduce(startedState(false), { event: "progress", step_id: "z", status: "waiting_review" });
    t = reduce(t, { event: "finished", status: "finished", message: "" });
    expect(t.steps["z"]).toBe("done");
    // a step that is refused or stopped keeps its status
    let u = reduce(startedState(false), { event: "progress", step_id: "y", status: "waiting_review" });
    u = reduce(u, { event: "finished", status: "stopped", message: "" });
    expect(u.steps["y"]).toBe("waiting_review");
  });

  it("ignores statuses it does not know and unrelated events", () => {
    const s = startedState(true);
    expect(reduce(s, { event: "progress", step_id: "a", status: "levitating" })).toBe(s);
    expect(reduce(s, { event: "something" })).toBe(s);
    expect(idleState().phase).toBe("idle");
  });
});

describe("describeResult", () => {
  const finished = (status: string, current: string | null = "submit", sandbox = false) =>
    reduce({ ...startedState(sandbox), current }, { event: "finished", status, message: "kỹ thuật", sandbox });

  it("speaks about the work in the GDV's words, never a step id", () => {
    const texts = ["finished", "stopped", "rejected", "needs_help", "refused", "failed"].map((s) => describeResult(finished(s), javaFlow));
    for (const text of texts) {
      expect(text).not.toMatch(/submit|s\d|selector|phần tử|sandbox|mock|GDV/i);
    }
    expect(texts[0]).toBe("Xong. Agent đã làm đủ 6 bước.");
    expect(texts[2]).toContain("«Gửi duyệt»");
    expect(texts[3]).toContain("«Gửi duyệt»");
    expect(texts[4]).toContain("chưa được phép");
    expect(texts[5]).toContain("«Gửi duyệt»");
  });

  it("tells a test run apart from the real thing", () => {
    expect(describeResult(finished("finished", null, true), javaFlow)).toContain("Bạn có thể bấm Duyệt để dùng thật");
    expect(describeResult(startedState(true), javaFlow)).toContain("dữ liệu mẫu");
  });

  it("falls back to a general phrase when it does not know the step", () => {
    expect(describeResult(finished("failed", "khong-co"), javaFlow)).toContain("bước này");
    expect(describeResult(idleState(), javaFlow)).toBe("");
  });
});

describe("FlowCanvas", () => {
  let root: HTMLElement;
  let saved: Record<string, Positions>;
  let store: LayoutStore;

  beforeEach(() => {
    document.body.replaceChildren();
    root = document.createElement("div");
    document.body.appendChild(root);
    saved = {};
    store = { load: (key) => saved[key] ?? {}, save: vi.fn((key, positions) => void (saved[key] = positions)) };
  });

  const make = (handlers = {}, withStore = false) => new FlowCanvas(root, handlers, withStore ? store : undefined, { animate: false });
  const node = (id: string) => root.querySelector<HTMLElement>(`[data-id="${id}"]`)!;

  it("draws a node per step and per field and a line per edge", () => {
    const canvas = make();
    const graph = buildGraph(javaFlow);
    canvas.setGraph(graph, "wf");
    expect(root.querySelectorAll(".rk-node.rk-step")).toHaveLength(javaFlow.steps.length);
    expect(root.querySelectorAll(".rk-node.rk-param")).toHaveLength(javaFlow.inputs.length);
    const lines = [...root.querySelectorAll("path.rk-line[data-edge]")];
    expect(lines).toHaveLength(graph.edges.length);
    expect(lines.every((p) => /^M [\d.-]+ [\d.-]+ C/.test(p.getAttribute("d")!))).toBe(true);
  });

  it("says in plain words what each step may touch and how much control it has", () => {
    make().setGraph(buildGraph(javaFlow), "wf");
    const money = node("submit");
    expect(money.textContent).toContain("Liên quan tiền");
    expect(money.textContent).toContain("Chờ tôi duyệt");
    expect(money.textContent).toContain("«Gửi duyệt»");
    expect(money.querySelector(".risk-money")!.getAttribute("title")).toContain("luôn chờ bạn duyệt");
    expect(node("fill_cif").textContent).toContain("Chỉ xem");
    expect(node("fill_cif").textContent).toContain("Tự làm");
    expect(root.textContent).not.toMatch(/risk|mode|draft|sandbox|mock|selector/i);
  });

  it("keeps every node the same size in every state, and puts the question over the badges instead of next to them", () => {
    const canvas = make();
    canvas.setGraph(buildGraph(javaFlow), "wf");
    const before = node("submit").className.includes("is-asking");
    canvas.setRun(reduce(startedState(false), { event: "waiting", kind: "approve", step_id: "submit", label: "Gửi duyệt", risk: "money" }));
    expect(before).toBe(false);
    expect(node("submit").classList.contains("is-asking")).toBe(true);
    expect(node("submit").querySelector(".rk-actions")!.hasAttribute("hidden")).toBe(false); // never toggled with display: it fades
    expect(node("submit").style.height).toBe(""); // the height comes from the stylesheet, one value for every state
  });

  it("lights up the running step, marks finished ones and passes along the lines", () => {
    const canvas = make();
    canvas.setGraph(buildGraph(javaFlow), "wf");
    let state = startedState(false);
    state = reduce(state, { event: "progress", step_id: "fill_cif", status: "running" });
    canvas.setRun(state);
    expect(node("fill_cif").classList.contains("current")).toBe(true);
    expect(node("fill_cif").querySelector(".rk-status")!.textContent).toBe("Đang làm");
    expect(root.querySelector('[data-edge="param:so_cif->fill_cif:data:so_cif"]')!.classList.contains("active")).toBe(true);
    state = reduce(state, { event: "progress", step_id: "fill_cif", status: "done" });
    state = reduce(state, { event: "progress", step_id: "search_cif", status: "running" });
    canvas.setRun(state);
    expect(node("fill_cif").classList.contains("status-done")).toBe(true);
    expect(node("fill_cif").classList.contains("current")).toBe(false);
    expect(root.querySelector('[data-edge="fill_cif->search_cif:flow"]')!.classList.contains("active")).toBe(true);
    expect(node("param:so_cif").classList.contains("passed")).toBe(true);
  });

  it("asks for approval inside the node that is waiting, and reports the answer", () => {
    const decisions: boolean[] = [];
    const canvas = make({ onDecision: (a: boolean) => decisions.push(a) });
    canvas.setGraph(buildGraph(javaFlow), "wf");
    canvas.setRun(reduce(startedState(false), { event: "waiting", kind: "approve", step_id: "submit", label: "Gửi duyệt", risk: "money" }));
    expect(node("fill_cif").classList.contains("is-asking")).toBe(false);
    const [ok, no] = node("submit").querySelectorAll<HTMLButtonElement>(".rk-actions button");
    expect([ok!.textContent, no!.textContent]).toEqual(["Duyệt", "Không duyệt"]);
    ok!.click();
    no!.click();
    expect(decisions).toEqual([true, false]);
    canvas.setRun(reduce(startedState(false), { event: "waiting", kind: "review", step_id: "submit", label: null, risk: "money" }));
    expect([...node("submit").querySelectorAll(".rk-actions button")].map((b) => b.textContent)).toEqual(["Đi tiếp", "Dừng"]);
  });

  it("lets the GDV change how much control a read step has with one click, and nothing else", () => {
    const changes: [string, string][] = [];
    make({ onMode: (id: string, mode: string) => changes.push([id, mode]) }).setGraph(buildGraph(javaFlow), "wf");
    const button = node("fill_cif").querySelector<HTMLButtonElement>("button.rk-mode")!;
    expect(button.textContent).toBe("Tự làm");
    button.click();
    expect(button.textContent).toBe("Cho tôi xem");
    button.click();
    expect(button.textContent).toBe("Chờ tôi duyệt");
    button.click();
    expect(button.textContent).toBe("Tự làm");
    expect(changes).toEqual([["fill_cif", "review"], ["fill_cif", "approve"], ["fill_cif", "auto"]]);
    const money = node("submit").querySelector(".rk-mode")!;
    expect(money.tagName).toBe("SPAN"); // not a button: a step that touches money cannot be loosened
    expect(money.classList.contains("locked")).toBe(true);
  });

  it("hands typed values to the caller and never draws them back", () => {
    const typed: [string, string][] = [];
    const canvas = make({ onParam: (n: string, v: string) => typed.push([n, v]) });
    canvas.setGraph(buildGraph(javaFlow), "wf");
    const input = node("param:so_tien").querySelector<HTMLInputElement>("input")!;
    expect(input.autocomplete).toBe("off");
    input.value = "5000000";
    input.dispatchEvent(new Event("input"));
    expect(typed).toEqual([["so_tien", "5000000"]]);
    canvas.setRun(reduce(startedState(false), { event: "finished", status: "finished", message: "xong" }));
    const text = [...root.querySelectorAll("*")].filter((e) => e.children.length === 0 && !(e instanceof HTMLInputElement)).map((e) => e.textContent).join(" ");
    expect(text).not.toContain("5000000");
    expect(node("param:so_cif").textContent).toContain("Nhạy cảm");
  });

  it("keeps what is on screen when the same flow grows, and fades the new nodes in", () => {
    const canvas = make();
    const partial = { ...javaFlow, inputs: [], steps: javaFlow.steps.slice(0, 3) };
    canvas.setGraph(buildGraph(partial), "wf");
    const first = node("fill_cif");
    expect(first.classList.contains("rk-enter")).toBe(false);
    canvas.setGraph(buildGraph({ ...javaFlow, inputs: [], steps: javaFlow.steps.slice(0, 4) }), "wf");
    expect(node("fill_cif")).toBe(first); // the very same element: nothing was redrawn
    expect(node("read_account").classList.contains("rk-enter")).toBe(true);
    expect(root.querySelectorAll("path.rk-line.flow")).toHaveLength(3);
  });

  it("keeps what the user typed when the flow is shown again", () => {
    const canvas = make();
    canvas.setGraph(buildGraph(javaFlow), "wf");
    const input = node("param:so_tien").querySelector<HTMLInputElement>("input")!;
    input.value = "123";
    canvas.setGraph(buildGraph(javaFlow), "wf");
    expect(node("param:so_tien").querySelector<HTMLInputElement>("input")).toBe(input);
    expect(input.value).toBe("123");
  });

  it("starts over only when a different flow is shown", () => {
    const canvas = make();
    canvas.setGraph(buildGraph(javaFlow), "a");
    const old = node("fill_cif");
    canvas.setGraph(buildGraph(webFlow), "b");
    expect(old.isConnected).toBe(false);
    expect(root.querySelectorAll(".rk-node.rk-step")).toHaveLength(webFlow.steps.length);
    expect(root.querySelectorAll(".rk-node.rk-param")).toHaveLength(webFlow.inputs.length);
  });

  it("moves a node by dragging its header, redraws its lines and remembers only what the user moved", () => {
    const canvas = make({}, true);
    canvas.setGraph(buildGraph(javaFlow), "wf");
    const before = canvas.nodePosition("search_cif")!;
    const edge = root.querySelector('[data-edge="fill_cif->search_cif:flow"]')!;
    const dBefore = edge.getAttribute("d");
    node("search_cif").querySelector(".rk-head")!.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, clientX: 100, clientY: 100 }));
    window.dispatchEvent(new MouseEvent("pointermove", { clientX: 160, clientY: 130 }));
    window.dispatchEvent(new MouseEvent("pointerup"));
    const k = canvas.currentView().k;
    expect(canvas.nodePosition("search_cif")).toEqual({ x: before.x + 60 / k, y: before.y + 30 / k });
    expect(edge.getAttribute("d")).not.toBe(dBefore);
    expect(Object.keys(saved["wf"]!)).toEqual(["search_cif"]);

    const again = new FlowCanvas(document.createElement("div"), {}, store, { animate: false });
    again.setGraph(buildGraph(javaFlow), "wf");
    expect(again.nodePosition("search_cif")).toEqual(canvas.nodePosition("search_cif"));
    expect(again.nodePosition("fill_cif")).toEqual({ x: 0, y: buildGraph(javaFlow).nodes.find((n) => n.id === "fill_cif")!.y });
  });

  it("does not save when a header was only clicked", () => {
    const canvas = make({}, true);
    canvas.setGraph(buildGraph(javaFlow), "wf");
    node("fill_cif").querySelector(".rk-head")!.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, clientX: 5, clientY: 5 }));
    window.dispatchEvent(new MouseEvent("pointerup"));
    expect(store.save).not.toHaveBeenCalled();
  });

  it("zooms around a point and keeps the zoom inside its limits", () => {
    const canvas = make();
    canvas.setGraph(buildGraph(javaFlow), "wf");
    for (let i = 0; i < 40; i++) canvas.zoomBy(1.25);
    expect(canvas.currentView().k).toBe(2);
    for (let i = 0; i < 80; i++) canvas.zoomBy(0.8);
    expect(canvas.currentView().k).toBe(0.25);
  });

  describe("camera while a run goes on", () => {
    const size = (width: number, height: number) => {
      Object.defineProperty(root, "clientWidth", { value: width, configurable: true });
      Object.defineProperty(root, "clientHeight", { value: height, configurable: true });
    };

    it("stays still for a flow that fits, whichever step is working", () => {
      size(1170, 860);
      const canvas = make();
      canvas.setGraph(buildGraph(longFlow(8)), "wf");
      const view = canvas.currentView();
      for (const id of ["s1", "s4", "s5", "s8"]) canvas.setRun(reduce(startedState(false), { event: "progress", step_id: id, status: "running" }));
      expect(canvas.currentView()).toEqual(view);
    });

    it("keeps the screen card's space free of the flow on a tall window, and none on a short one", () => {
      size(1170, 900);
      const tall = make();
      tall.setGraph(buildGraph(longFlow(8)), "wf");
      const nodes = buildGraph(longFlow(8)).nodes;
      const view = tall.currentView();
      const lowest = Math.max(...nodes.map((n) => n.y + n.h));
      expect(lowest * view.k + view.y).toBeLessThanOrEqual(900 - 300 + 0.5); // the card has the bottom 300px

      root.replaceChildren();
      size(1170, 700);
      const short = make();
      short.setGraph(buildGraph(longFlow(8)), "wf");
      short.setScreen({ title: "x", width: 10, height: 10, items: [] }, null);
      expect(root.querySelector(".rk-dock")!.classList.contains("collapsed")).toBe(true); // folded: no room for it
    });

    it("slides only when the step working has left the view", () => {
      size(900, 420);
      const canvas = make();
      canvas.setGraph(buildGraph(longFlow(16)), "wf");
      canvas.zoomBy(1.0);
      const before = canvas.currentView();
      canvas.setRun(reduce(startedState(false), { event: "progress", step_id: "s16", status: "running" }));
      const after = canvas.currentView();
      const at = canvas.nodePosition("s16")!;
      expect(after.k).toBe(before.k);
      expect(at.y * after.k + after.y + NODE_H * after.k).toBeLessThanOrEqual(420 - 40 + 0.001);
      expect(at.x * after.k + after.x).toBeGreaterThanOrEqual(40 - 0.001);
    });
  });

  describe("screen card", () => {
    const drawing: Drawing = {
      title: "Mock TPSS - Chuyển tiền",
      width: 800,
      height: 600,
      items: [
        { role: "text", kind: "field", name: "Số tiền", x: 120, y: 50, w: 140, h: 24 },
        { role: "push button", kind: "button", name: "Gửi duyệt", x: 120, y: 150, w: 90, h: 28 },
        { role: "label", kind: "label", name: null, x: 10, y: 10, w: 200, h: 20 },
      ],
    };
    const dock = () => root.querySelector<HTMLElement>(".rk-dock")!;

    it("is hidden until the agent sends a drawing, and fades rather than appearing and disappearing", () => {
      const canvas = make();
      canvas.setGraph(buildGraph(javaFlow), "wf");
      expect(dock().classList.contains("show")).toBe(false);
      canvas.setScreen(drawing, null);
      expect(dock().classList.contains("show")).toBe(true);
      canvas.setScreen(null, null);
      expect(dock().classList.contains("show")).toBe(false);
    });

    it("stays where it is while the work moves, lights the target, and does not redraw for the same screen", () => {
      const canvas = make();
      canvas.setGraph(buildGraph(javaFlow), "wf");
      canvas.setRun(reduce(startedState(false), { event: "progress", step_id: "fill_cif", status: "running" }));
      canvas.setScreen(drawing, "Số tiền");
      const board = dock().querySelector("svg.rk-board")!;
      expect(dock().querySelectorAll("g.rk-item")).toHaveLength(3);
      expect([...dock().querySelectorAll("g.rk-item.hl text")].map((t) => t.textContent)).toEqual(["Số tiền"]);
      canvas.setRun(reduce(startedState(false), { event: "progress", step_id: "submit", status: "running" }));
      canvas.setScreen(drawing, "Gửi duyệt");
      expect(dock().querySelector("svg.rk-board")).toBe(board); // the same drawing is kept, only the highlight moves
      expect([...dock().querySelectorAll("g.rk-item.hl text")].map((t) => t.textContent)).toEqual(["Gửi duyệt"]);
      expect(dock().textContent).toContain("Mock TPSS - Chuyển tiền");
      expect(dock().textContent).toContain("không hiện thông tin của khách");
    });

    it("can be folded away", () => {
      const canvas = make();
      canvas.setGraph(buildGraph(javaFlow), "wf");
      canvas.setScreen(drawing, null);
      const toggle = dock().querySelector<HTMLButtonElement>("button.rk-dock-toggle")!;
      toggle.click();
      expect(dock().classList.contains("collapsed")).toBe(true);
      expect(toggle.textContent).toBe("Mở ra");
    });
  });

  it("puts a sentence at the top that fades, using the caller's words", () => {
    const canvas = make({ describeResult: () => "Xong. Agent đã làm đủ 6 bước." });
    canvas.setGraph(buildGraph(javaFlow), "wf");
    const banner = root.querySelector<HTMLElement>(".rk-banner")!;
    expect(banner.classList.contains("show")).toBe(false);
    canvas.setRun(reduce(startedState(false), { event: "finished", status: "finished", message: "kỹ thuật" }));
    expect(banner.textContent).toBe("Xong. Agent đã làm đủ 6 bước.");
    expect(banner.classList.contains("show") && banner.classList.contains("tone-finished")).toBe(true);
    canvas.setRun(null);
    expect(banner.classList.contains("show")).toBe(false);
    expect(banner.textContent).toBe("Xong. Agent đã làm đủ 6 bước."); // the words stay while it fades
  });

  it("has fixed node sizes for lines to attach to", () => {
    expect([NODE_W, NODE_H]).toEqual([232, 122]);
  });
});
