/**
 * The canvas: nodes you can drag, lines that light up as the agent works, a pan and zoom view.
 * No library: the machines this runs on have no internet and are often old, so it is plain
 * SVG and DOM, light enough for any counter PC.
 *
 * Calm by design. The flow is laid out to fit one screen, so the camera stays put and only
 * slides when the step being worked on has left the view. Nodes keep their size whatever their
 * state, new nodes fade in instead of the flow being redrawn, and the screen the agent is
 * working on sits in a fixed card instead of following the steps around.
 *
 * What a node may show: the action, the caption of the target, what the step may touch, how much
 * control it has, and its status. Never a value the GDV typed or the agent read. Information
 * nodes hold an input box, but its value lives only in that element and in the callback.
 */
import {
  MAX_ZOOM,
  MIN_ZOOM,
  MODE_HINT,
  MODE_LABEL,
  NEXT_MODE,
  RISK_HINT,
  RISK_LABEL,
  TYPE_LABEL,
  connect,
  ensureVisible,
  portPoint,
  readableView,
  sidesFor,
  type Graph,
  type GraphEdge,
  type GraphNode,
  type View,
} from "./flow-graph";
import { STATUS_TEXT, type RunState, type StepStatus } from "./run-state";

export type Positions = Record<string, { x: number; y: number }>;

export interface LayoutStore {
  load(key: string): Positions;
  save(key: string, positions: Positions): void;
}

export interface CanvasHandlers {
  onDecision?(approve: boolean): void;
  onParam?(name: string, value: string): void;
  /** The GDV changed how much control a step has. Only offered for steps that only read. */
  onMode?(stepId: string, mode: string): void;
  /** The sentence shown while a run goes on and when it ends. Defaults to the agent's own message. */
  describeResult?(state: RunState): string;
}

export interface CanvasOptions {
  /** Turn motion off (tests, reduced motion). Defaults to on when the browser can animate. */
  animate?: boolean;
}

/** The drawing of a screen sent by the agent: boxes only, no values (see wireframe.py). */
export interface Drawing {
  title: string;
  width: number;
  height: number;
  items: { role: string; kind: string; name: string | null; x: number; y: number; w: number; h: number }[];
}

const SVG_NS = "http://www.w3.org/2000/svg";
const DOCK_W = 300;
const DOCK_H = 168;
/** Room kept under the flow for the screen card. Short windows get no card space and fold the card instead. */
const DOCK_RESERVE = 300;
const TALL_ENOUGH = 780;
const CAMERA_EASE = "transform 0.85s cubic-bezier(0.22, 0.8, 0.3, 1)";

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function svg<K extends keyof SVGElementTagNameMap>(tag: K, attributes: Record<string, string> = {}): SVGElementTagNameMap[K] {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  return element;
}

interface NodeParts {
  root: HTMLElement;
  signature: string;
  status?: HTMLElement;
  ok?: HTMLButtonElement;
  no?: HTMLButtonElement;
  shown?: StepStatus;
  asking?: "approve" | "review" | null;
}

const easeOut = (t: number) => 1 - Math.pow(1 - t, 3);

export class FlowCanvas {
  private readonly world = el("div", "rk-world");
  private readonly lines = svg("svg", { class: "rk-lines" });
  private readonly layer = el("div", "rk-layer");
  private readonly banner = el("div", "rk-banner");
  private readonly dock = el("div", "rk-dock");
  private readonly dockTitle = el("div", "rk-dock-title");
  private readonly dockBoard = el("div", "rk-dock-board");
  private readonly nodeEls = new Map<string, NodeParts>();
  private readonly lineEls = new Map<string, { path: SVGPathElement; edge: GraphEdge }>();
  private graph: Graph = { nodes: [], edges: [] };
  private positions: Positions = {};
  private moved = new Set<string>();
  private layoutKey = "";
  private view: View = { x: 40, y: 40, k: 1 };
  private current: string | null = null;
  private lastRun: RunState | null = null;
  private drawingKey = "";
  private dockItems: SVGGElement[] = [];
  private dockNames: (string | null)[] = [];
  private readonly animate: boolean;
  private cameraTimer: number | undefined;
  private tween = 0;
  private readonly cleanup: (() => void)[] = [];

  constructor(
    private readonly root: HTMLElement,
    private readonly handlers: CanvasHandlers = {},
    private readonly store?: LayoutStore,
    options: CanvasOptions = {},
  ) {
    this.animate =
      options.animate ??
      (typeof window.requestAnimationFrame === "function" && !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
    root.classList.add("rk-canvas");
    root.replaceChildren();

    const defs = svg("defs");
    const marker = svg("marker", { id: "rk-arrow", viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse" });
    marker.appendChild(svg("path", { d: "M 0 0 L 10 5 L 0 10 z", class: "rk-arrow-head" }));
    defs.appendChild(marker);
    this.lines.appendChild(defs);
    this.world.append(this.lines, this.layer);

    this.banner.setAttribute("role", "status");
    this.banner.setAttribute("aria-live", "polite");
    this.buildDock();
    root.append(this.world, this.banner, this.dock, this.buildLegend(), this.buildToolbar());
    this.bindView();
    this.applyView();
  }

  // ---- public -----------------------------------------------------------------------------------------

  /**
   * Show a flow. The same flow shown again with more or changed steps keeps what is on screen:
   * nodes that are already there stay, new ones fade in, and the camera eases to fit.
   */
  setGraph(graph: Graph, layoutKey: string): void {
    const sameFlow = layoutKey === this.layoutKey && this.nodeEls.size > 0;
    const firstTime = !sameFlow;
    const saved = sameFlow ? {} : (this.store?.load(layoutKey) ?? {});
    if (!sameFlow) {
      this.clearAll();
      this.moved = new Set(Object.keys(saved));
      this.positions = {};
    }
    this.layoutKey = layoutKey;
    this.graph = graph;

    const targets: Positions = {};
    for (const node of graph.nodes) {
      const own = this.moved.has(node.id) ? (saved[node.id] ?? this.positions[node.id]) : undefined;
      targets[node.id] = own ?? { x: node.x, y: node.y };
    }

    const ids = new Set(graph.nodes.map((n) => n.id));
    for (const [id, parts] of this.nodeEls) {
      if (ids.has(id)) continue;
      this.nodeEls.delete(id);
      delete this.positions[id];
      this.fadeOut(parts.root);
    }
    const edgeIds = new Set(graph.edges.map((e) => e.id));
    for (const [id, line] of this.lineEls) {
      if (edgeIds.has(id)) continue;
      this.lineEls.delete(id);
      this.fadeOut(line.path);
    }

    for (const node of graph.nodes) {
      const existing = this.nodeEls.get(node.id);
      if (existing) {
        this.refreshNode(existing, node);
      } else {
        this.positions[node.id] = targets[node.id]!;
        this.addNode(node, !firstTime);
      }
    }
    for (const edge of graph.edges) {
      const known = this.lineEls.get(edge.id);
      if (known) {
        known.edge = edge;
        continue;
      }
      const path = svg("path", { class: `rk-line ${edge.kind}${firstTime ? "" : " rk-enter"}`, "marker-end": "url(#rk-arrow)" });
      path.dataset.edge = edge.id;
      this.lines.appendChild(path);
      this.lineEls.set(edge.id, { path, edge });
    }

    this.moveNodes(targets, firstTime ? 0 : 450);
    this.updatePorts();
    this.setRun(this.lastRun);
    this.fit(!firstTime);
  }

  /** Light the nodes up from the run state. `null` shows the flow at rest. */
  setRun(state: RunState | null): void {
    this.lastRun = state;
    const steps = state?.steps ?? {};
    const waiting = state?.waiting ?? null;
    const previous = this.current;
    this.current = state && state.phase === "running" ? state.current : null;

    for (const node of this.graph.nodes) {
      const parts = this.nodeEls.get(node.id);
      if (!parts) continue;
      if (node.kind !== "step" || !node.step) {
        parts.root.classList.toggle("passed", state !== null && state.phase !== "idle");
        continue;
      }
      const status: StepStatus = steps[node.id] ?? "pending";
      const asking = waiting !== null && waiting.stepId === node.id ? waiting.kind : null;
      if (parts.shown !== status) {
        if (parts.shown) parts.root.classList.remove(`status-${parts.shown}`);
        parts.root.classList.add(`status-${status}`);
        parts.shown = status;
        if (parts.status) parts.status.textContent = STATUS_TEXT[status];
        parts.root.setAttribute(
          "aria-label",
          `Bước ${node.index}: ${node.title} ${node.subtitle}. ${RISK_LABEL[node.step.risk]}. ${STATUS_TEXT[status]}`,
        );
      }
      parts.root.classList.toggle("current", this.current === node.id);
      if (parts.asking !== asking) {
        parts.asking = asking;
        parts.root.classList.toggle("is-asking", asking !== null);
        if (parts.ok && parts.no) {
          parts.ok.textContent = asking === "review" ? "Đi tiếp" : "Duyệt";
          parts.no.textContent = asking === "review" ? "Dừng" : "Không duyệt";
        }
      }
    }
    for (const { path, edge } of this.lineEls.values()) {
      const toStatus = steps[edge.to];
      path.classList.toggle("active", toStatus === "running" || toStatus === "waiting_approval" || toStatus === "waiting_review");
      path.classList.toggle("passed", toStatus === "done" || toStatus === "auto_approved");
    }

    const text = state === null ? "" : (this.handlers.describeResult?.(state) ?? this.defaultBanner(state));
    this.setBanner(text, state?.result?.status ?? (state ? "running" : ""));

    if (this.current !== null && this.current !== previous) this.keepInView(this.current);
  }

  /** Show what the agent's screen looks like, with the target of the current step lit. */
  setScreen(drawing: Drawing | null, highlight: string | null): void {
    this.dock.classList.toggle("show", drawing !== null);
    this.dock.setAttribute("aria-hidden", String(drawing === null));
    if (drawing === null) return;
    const key = JSON.stringify(drawing);
    if (key !== this.drawingKey) {
      const first = this.drawingKey === "";
      this.drawingKey = key;
      this.drawBoard(drawing);
      // a short window has no room under the flow: start with the card folded
      if (first && this.root.clientHeight > 0 && this.root.clientHeight < TALL_ENOUGH) this.dock.classList.add("collapsed");
    }
    this.dockItems.forEach((group, index) => group.classList.toggle("hl", highlight !== null && this.dockNames[index] === highlight));
  }

  /** The height the flow may use: the canvas minus the space kept for the screen card. */
  private usableHeight(): number {
    const height = this.root.clientHeight || this.root.getBoundingClientRect().height;
    return height >= TALL_ENOUGH ? height - DOCK_RESERVE : height;
  }

  fit(animate = false): void {
    const rect = this.root.getBoundingClientRect();
    const boxes = this.graph.nodes.map((n) => ({ ...this.positions[n.id]!, w: n.w, h: n.h }));
    this.setView(readableView(boxes, this.root.clientWidth || rect.width, this.usableHeight()), animate);
  }

  zoomBy(factor: number, around?: { x: number; y: number }): void {
    const k = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, this.view.k * factor));
    const cx = around?.x ?? this.root.clientWidth / 2;
    const cy = around?.y ?? this.root.clientHeight / 2;
    this.setView({ k, x: cx - ((cx - this.view.x) / this.view.k) * k, y: cy - ((cy - this.view.y) / this.view.k) * k }, false);
  }

  nodePosition(id: string): { x: number; y: number } | undefined {
    return this.positions[id];
  }

  currentView(): View {
    return { ...this.view };
  }

  destroy(): void {
    cancelAnimationFrame(this.tween);
    window.clearTimeout(this.cameraTimer);
    for (const undo of this.cleanup) undo();
    this.cleanup.length = 0;
  }

  // ---- nodes --------------------------------------------------------------------------------------------

  private clearAll(): void {
    for (const { root } of this.nodeEls.values()) root.remove();
    for (const { path } of this.lineEls.values()) path.remove();
    this.nodeEls.clear();
    this.lineEls.clear();
    this.current = null;
    cancelAnimationFrame(this.tween);
  }

  private fadeOut(element: Element): void {
    element.classList.add("rk-exit");
    window.setTimeout(() => element.remove(), 280);
  }

  private signatureOf(node: GraphNode): string {
    return JSON.stringify([node.title, node.subtitle, node.step?.risk, node.step?.mode, node.row, node.flip, node.index]);
  }

  private addNode(node: GraphNode, entering: boolean): void {
    const root = el("div", `rk-node rk-${node.kind}${entering ? " rk-enter" : ""}`);
    root.dataset.id = node.id;
    root.setAttribute("role", "group");
    root.style.width = `${node.w}px`;
    const at = this.positions[node.id]!;
    root.style.transform = `translate(${at.x}px, ${at.y}px)`;
    const parts: NodeParts = { root, signature: "" };
    this.nodeEls.set(node.id, parts);
    this.fillNode(parts, node);
    this.layer.appendChild(root);
    if (entering) window.setTimeout(() => root.classList.remove("rk-enter"), 700);
  }

  private refreshNode(parts: NodeParts, node: GraphNode): void {
    const signature = this.signatureOf(node);
    if (signature === parts.signature) return;
    if (node.kind === "param") {
      parts.signature = signature;
      parts.root.querySelector(".rk-body")!.textContent = node.subtitle;
      return;
    }
    parts.shown = undefined;
    parts.asking = undefined;
    this.fillNode(parts, node);
  }

  private fillNode(parts: NodeParts, node: GraphNode): void {
    const { root } = parts;
    parts.signature = this.signatureOf(node);
    root.replaceChildren();
    root.classList.remove("risk-read", "risk-write", "risk-money", "mode-auto", "mode-review", "mode-approve", "is-asking");
    root.classList.toggle("flip", node.flip);
    for (const side of ["left", "right", "top", "bottom"]) root.appendChild(el("span", `rk-port ${side}`));

    const head = el("div", "rk-head");
    head.addEventListener("pointerdown", (event) => this.startNodeDrag(event as PointerEvent, node.id));

    if (node.kind === "step" && node.step) {
      const step = node.step;
      root.classList.add(`risk-${step.risk}`, `mode-${step.mode}`);
      head.append(el("span", "rk-index", String(node.index)), el("span", "rk-title", node.title));
      parts.status = el("span", "rk-status", STATUS_TEXT.pending);
      head.appendChild(parts.status);

      const badges = el("div", "rk-badges");
      const risk = el("span", `rk-badge risk-${step.risk}`, RISK_LABEL[step.risk]);
      risk.title = RISK_HINT[step.risk];
      badges.append(risk, this.modeControl(step));

      const actions = el("div", "rk-actions");
      const ok = el("button", "rk-go", "Duyệt");
      const no = el("button", "rk-no", "Không duyệt");
      ok.type = no.type = "button";
      ok.addEventListener("click", () => this.handlers.onDecision?.(true));
      no.addEventListener("click", () => this.handlers.onDecision?.(false));
      actions.append(ok, no);
      parts.ok = ok;
      parts.no = no;
      root.append(head, el("div", "rk-body", node.subtitle ? `«${node.subtitle}»` : ""), badges, actions);
    } else if (node.input) {
      const input = node.input;
      root.classList.add("rk-param");
      head.appendChild(el("span", "rk-title", node.title));
      const chips = el("div", "rk-badges rk-chips");
      if (TYPE_LABEL[input.type]) chips.appendChild(el("span", "rk-badge", TYPE_LABEL[input.type]!));
      if (input.value_class) {
        const sensitive = el("span", "rk-badge sensitive", "Nhạy cảm");
        sensitive.title = "Giá trị này không được lưu lại ở bất kỳ đâu.";
        chips.appendChild(sensitive);
      }
      head.appendChild(chips);
      const field = document.createElement("input");
      field.className = "rk-param-input";
      field.type = "text";
      field.autocomplete = "off";
      field.spellcheck = false;
      field.placeholder = input.default !== undefined && input.default !== null ? `Thường là ${input.default}` : "Nhập khi chạy";
      field.setAttribute("aria-label", node.subtitle);
      field.name = input.name;
      field.addEventListener("input", () => this.handlers.onParam?.(input.name, field.value));
      field.addEventListener("pointerdown", (event) => event.stopPropagation());
      root.append(head, el("div", "rk-body", node.subtitle), field);
    }
  }

  /** How much control the step has. A step that only reads can be changed with one click; the others are fixed. */
  private modeControl(step: NonNullable<GraphNode["step"]>): HTMLElement {
    const label = (mode: string) => MODE_LABEL[mode]!;
    if (step.risk !== "read" || !this.handlers.onMode) {
      const fixed = el("span", `rk-badge rk-mode mode-${step.mode}${step.risk === "read" ? "" : " locked"}`, label(step.mode));
      fixed.title = step.risk === "read" ? MODE_HINT[step.mode]! : `${RISK_HINT[step.risk]} Không đổi được.`;
      return fixed;
    }
    const button = el("button", `rk-badge rk-mode mode-${step.mode}`, label(step.mode));
    button.type = "button";
    let mode = step.mode as string;
    const describe = () => (button.title = `${MODE_HINT[mode]} Bấm để đổi.`);
    describe();
    button.addEventListener("click", () => {
      mode = NEXT_MODE[mode]!;
      button.textContent = label(mode);
      button.className = `rk-badge rk-mode mode-${mode}`;
      describe();
      this.handlers.onMode?.(step.id, mode);
    });
    button.addEventListener("pointerdown", (event) => event.stopPropagation());
    return button;
  }

  // ---- geometry ----------------------------------------------------------------------------------------------

  private node(id: string): GraphNode | undefined {
    return this.graph.nodes.find((n) => n.id === id);
  }

  private updateLines(): void {
    for (const { path, edge } of this.lineEls.values()) {
      const from = this.node(edge.from);
      const to = this.node(edge.to);
      if (!from || !to || !this.positions[from.id] || !this.positions[to.id]) continue;
      const [fromSide, toSide] = sidesFor(edge, from, to);
      path.setAttribute(
        "d",
        connect(portPoint(from, this.positions[from.id]!, fromSide), fromSide, portPoint(to, this.positions[to.id]!, toSide), toSide),
      );
    }
  }

  /** Flow ports are green going out and orange coming in; on a flipped row the two swap sides. */
  private updatePorts(): void {
    for (const node of this.graph.nodes) {
      const root = this.nodeEls.get(node.id)?.root;
      if (!root) continue;
      root.querySelector(".rk-port.left")!.className = `rk-port left ${node.flip ? "out" : "in"}`;
      root.querySelector(".rk-port.right")!.className = `rk-port right ${node.flip ? "in" : "out"}`;
    }
  }

  private placeNode(id: string): void {
    const parts = this.nodeEls.get(id);
    const at = this.positions[id];
    if (parts && at) parts.root.style.transform = `translate(${at.x}px, ${at.y}px)`;
  }

  /** Slide nodes to their places, lines following, instead of letting them jump. */
  private moveNodes(targets: Positions, ms: number): void {
    cancelAnimationFrame(this.tween);
    const from: Positions = {};
    const ids = Object.keys(targets).filter((id) => this.positions[id]);
    for (const id of ids) from[id] = { ...this.positions[id]! };
    const changed = ids.filter((id) => from[id]!.x !== targets[id]!.x || from[id]!.y !== targets[id]!.y);
    const finish = () => {
      for (const id of ids) {
        this.positions[id] = { ...targets[id]! };
        this.placeNode(id);
      }
      this.updateLines();
    };
    if (changed.length === 0 || ms === 0 || !this.animate) {
      finish();
      return;
    }
    const start = performance.now();
    const frame = (now: number) => {
      const t = Math.min(1, (now - start) / ms);
      const e = easeOut(t);
      for (const id of changed) {
        this.positions[id] = {
          x: from[id]!.x + (targets[id]!.x - from[id]!.x) * e,
          y: from[id]!.y + (targets[id]!.y - from[id]!.y) * e,
        };
        this.placeNode(id);
      }
      this.updateLines();
      if (t < 1) this.tween = requestAnimationFrame(frame);
      else finish();
    };
    this.tween = requestAnimationFrame(frame);
  }

  // ---- camera and interaction ------------------------------------------------------------------------------------

  private applyView(): void {
    this.world.style.transform = `translate(${this.view.x}px, ${this.view.y}px) scale(${this.view.k})`;
  }

  /** Move the camera. A glide is a CSS transition on the whole world, so nodes and lines move together. */
  private setView(view: View, glide: boolean): void {
    window.clearTimeout(this.cameraTimer);
    const moves = Math.abs(view.x - this.view.x) > 1 || Math.abs(view.y - this.view.y) > 1 || Math.abs(view.k - this.view.k) > 0.005;
    const gliding = glide && this.animate && moves;
    this.world.style.transition = gliding ? CAMERA_EASE : "";
    this.view = view;
    this.applyView();
    if (gliding) this.cameraTimer = window.setTimeout(() => (this.world.style.transition = ""), 900);
  }

  /** Only slide the camera when the step being worked on has left the middle of the view. */
  private keepInView(id: string): void {
    const node = this.node(id);
    const at = this.positions[id];
    if (!node || !at) return;
    const next = ensureVisible(this.view, { ...at, w: node.w, h: node.h }, this.root.clientWidth, this.usableHeight());
    if (next !== this.view) this.setView(next, true);
  }

  private startNodeDrag(event: PointerEvent, id: string): void {
    if (event.button !== undefined && event.button !== 0) return;
    event.stopPropagation();
    this.setView(this.view, false);
    const start = { x: event.clientX, y: event.clientY };
    const origin = { ...this.positions[id]! };
    let moved = false;
    const move = (e: Event) => {
      const pointer = e as PointerEvent;
      this.positions[id] = {
        x: origin.x + (pointer.clientX - start.x) / this.view.k,
        y: origin.y + (pointer.clientY - start.y) / this.view.k,
      };
      this.placeNode(id);
      moved = true;
      this.updateLines();
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (!moved) return;
      this.moved.add(id);
      const mine: Positions = {};
      for (const key of this.moved) if (this.positions[key]) mine[key] = this.positions[key]!;
      this.store?.save(this.layoutKey, mine);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  private bindView(): void {
    const down = (event: Event) => {
      const pointer = event as PointerEvent;
      if ((pointer.target as HTMLElement).closest(".rk-node, .rk-toolbar, .rk-dock")) return;
      this.setView(this.view, false);
      const start = { x: pointer.clientX, y: pointer.clientY, vx: this.view.x, vy: this.view.y };
      const move = (e: Event) => {
        const p = e as PointerEvent;
        this.view = { ...this.view, x: start.vx + p.clientX - start.x, y: start.vy + p.clientY - start.y };
        this.applyView();
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    };
    const wheel = (event: Event) => {
      const e = event as WheelEvent;
      if ((e.target as HTMLElement).closest(".rk-dock")) return;
      e.preventDefault();
      const rect = this.root.getBoundingClientRect();
      this.zoomBy(e.deltaY < 0 ? 1.1 : 1 / 1.1, { x: e.clientX - rect.left, y: e.clientY - rect.top });
    };
    this.root.addEventListener("pointerdown", down);
    this.root.addEventListener("wheel", wheel, { passive: false });
    this.cleanup.push(() => this.root.removeEventListener("pointerdown", down), () => this.root.removeEventListener("wheel", wheel));
  }

  // ---- chrome around the canvas ----------------------------------------------------------------------------------------

  private defaultBanner(state: RunState): string {
    return state.phase === "finished" ? (state.result?.message ?? "") : state.phase === "running" ? "Agent đang làm…" : "";
  }

  /** The sentence at the top. It fades in and out and keeps its place, so nothing around it moves. */
  private setBanner(text: string, tone: string): void {
    if (text) this.banner.textContent = text;
    this.banner.className = `rk-banner${text ? " show" : ""}${tone ? ` tone-${tone}` : ""}`;
  }

  private buildToolbar(): HTMLElement {
    const bar = el("div", "rk-toolbar");
    const make = (text: string, title: string, action: () => void) => {
      const button = el("button", "rk-tool", text);
      button.type = "button";
      button.title = title;
      button.setAttribute("aria-label", title);
      button.addEventListener("click", action);
      return button;
    };
    bar.append(
      make("−", "Thu nhỏ", () => this.zoomBy(0.8)),
      make("+", "Phóng to", () => this.zoomBy(1.25)),
      make("Xem tất cả", "Hiện toàn bộ việc này", () => this.fit(true)),
    );
    return bar;
  }

  private buildLegend(): HTMLElement {
    const legend = el("div", "rk-legend");
    legend.setAttribute("aria-hidden", "true");
    for (const [kind, text] of [["flow", "Thứ tự làm"], ["data", "Thông tin được dùng"]] as const) {
      const item = el("span");
      item.append(el("i", kind), document.createTextNode(text));
      legend.appendChild(item);
    }
    return legend;
  }

  private buildDock(): void {
    this.dock.setAttribute("aria-hidden", "true");
    this.dock.style.width = `${DOCK_W}px`;
    const head = el("div", "rk-dock-head");
    const toggle = el("button", "rk-dock-toggle", "Thu gọn");
    toggle.type = "button";
    toggle.addEventListener("click", () => {
      const collapsed = this.dock.classList.toggle("collapsed");
      toggle.textContent = collapsed ? "Mở ra" : "Thu gọn";
    });
    head.append(el("span", "rk-dock-name", "Màn hình agent đang làm việc"), toggle);
    this.dock.append(head, this.dockTitle, this.dockBoard, el("p", "rk-dock-note", "Chỉ hiện khung màn hình, không hiện thông tin của khách."));
  }

  private drawBoard(drawing: Drawing): void {
    const scale = Math.min((DOCK_W - 24) / Math.max(drawing.width, 1), DOCK_H / Math.max(drawing.height, 1));
    const board = svg("svg", {
      class: "rk-board",
      viewBox: `0 0 ${Math.max(drawing.width, 1)} ${Math.max(drawing.height, 1)}`,
      width: String(Math.round(drawing.width * scale)),
      height: String(Math.round(drawing.height * scale)),
    });
    board.appendChild(svg("rect", { x: "0", y: "0", width: String(drawing.width), height: String(drawing.height), class: "rk-frame" }));
    this.dockItems = [];
    this.dockNames = [];
    for (const item of drawing.items) {
      const group = svg("g", { class: `rk-item ${item.kind}` });
      group.appendChild(svg("rect", { x: String(item.x), y: String(item.y), width: String(item.w), height: String(item.h), rx: "4" }));
      if (item.name) {
        const size = Math.max(14, Math.min(20, item.h - 8));
        const text = svg("text", { x: String(item.x + 6), y: String(item.y + item.h / 2 + size / 3), "font-size": String(size) });
        text.textContent = item.name;
        group.appendChild(text);
      }
      board.appendChild(group);
      this.dockItems.push(group);
      this.dockNames.push(item.name);
    }
    this.dockTitle.textContent = drawing.title;
    this.dockBoard.replaceChildren(board);
  }
}
