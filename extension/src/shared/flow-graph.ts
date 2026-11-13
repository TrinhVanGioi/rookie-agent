/**
 * A workflow as a graph of nodes, in the style of n8n: one node per step, one node per piece of
 * information the GDV has to give, and lines for what passes between them.
 *
 *   flow line   step -> next step               (the order of work)
 *   data line   information -> step that uses it
 *               step that read something -> step that uses it
 *
 * Steps are laid out in a snake, four to a row, so even a long flow fits one screen at a size
 * that is easy to read and the camera never has to chase the work. Pure data: nothing here
 * touches the DOM.
 */
import type { Workflow, WorkflowInput, WorkflowStep } from "./server-api";

export const NODE_W = 232;
export const NODE_H = 122;
export const GAP_X = 72;
export const ROW_GAP = 96;
export const PER_ROW = 4;
/** Space between rows of information nodes, tighter than between rows of steps. */
const INFO_ROW_GAP = 36;

export type NodeKind = "param" | "step";
export type Side = "left" | "right" | "top" | "bottom";

export interface GraphNode {
  id: string;
  kind: NodeKind;
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
  subtitle: string;
  /** Row in the snake (0 is the first row of steps). Information nodes sit above, at -1 and less. */
  row: number;
  /** Odd rows run right to left, so the line from one row to the next is a short drop. */
  flip: boolean;
  index?: number;
  step?: WorkflowStep;
  input?: WorkflowInput;
}

export interface GraphEdge {
  id: string;
  from: string;
  to: string;
  kind: "flow" | "data";
  /** Name of the value carried, for data lines. */
  carries?: string;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ---- words the GDV sees (plain business language, see CLAUDE.md rule 10) -------------------------------

export const ACTION_LABEL: Record<string, string> = {
  goto: "Mở trang",
  click: "Bấm",
  fill: "Điền",
  select: "Chọn",
  read_value: "Lấy thông tin",
  wait_for: "Chờ màn hình",
  extract_table: "Lấy bảng",
  compare: "Đối chiếu",
  save: "Lưu",
};

export const RISK_LABEL: Record<string, string> = { read: "Chỉ xem", write: "Sửa dữ liệu", money: "Liên quan tiền" };
export const RISK_HINT: Record<string, string> = {
  read: "Bước này chỉ xem, không thay đổi gì.",
  write: "Bước này sửa dữ liệu nên luôn chờ bạn duyệt.",
  money: "Bước này liên quan đến tiền nên luôn chờ bạn duyệt.",
};
export const MODE_LABEL: Record<string, string> = { auto: "Tự làm", review: "Cho tôi xem", approve: "Chờ tôi duyệt" };
export const MODE_HINT: Record<string, string> = {
  auto: "Agent tự làm bước này.",
  review: "Agent làm xong sẽ dừng để bạn xem kết quả.",
  approve: "Agent dừng và chờ bạn duyệt trước khi làm.",
};
export const NEXT_MODE: Record<string, string> = { auto: "review", review: "approve", approve: "auto" };
export const TYPE_LABEL: Record<string, string> = { date: "Ngày", number: "Số" };

const PLACEHOLDER = /\{([a-z][a-z0-9_]*)\}/g;
const NAMED_SELECTOR = /^role=[^[]+\[name='((?:[^'\\]|\\.)*)'\]$/;
const LABELED_SELECTOR = /^(?:label|text)=(.+)$/;

/** What to call a step's target: its recorded caption, else the name inside a selector, else the page. */
export function captionOf(step: WorkflowStep): string {
  if (step.target?.label) return step.target.label;
  for (const selector of step.target?.selectors ?? []) {
    const named = NAMED_SELECTOR.exec(selector) ?? LABELED_SELECTOR.exec(selector);
    if (named) return named[1]!.replace(/\\(.)/g, "$1");
  }
  return step.url ?? "";
}

/** "so_tien" -> "So tien", only for a workflow that has no caption for the field. */
export function humanize(name: string): string {
  const text = name.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function placeholdersOf(text: unknown): string[] {
  if (typeof text !== "string") return [];
  return [...text.matchAll(PLACEHOLDER)].map((match) => match[1]!);
}

export function paramNodeId(name: string): string {
  return `param:${name}`;
}

// ---- layout ------------------------------------------------------------------------------------------------

export function buildGraph(workflow: Workflow): Graph {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];

  const infoRows = Math.ceil(workflow.inputs.length / PER_ROW);
  const infoHeight = infoRows === 0 ? 0 : infoRows * NODE_H + (infoRows - 1) * INFO_ROW_GAP;
  const stepsTop = infoRows === 0 ? 0 : infoHeight + ROW_GAP;

  workflow.inputs.forEach((input, index) => {
    const row = Math.floor(index / PER_ROW);
    nodes.push({
      id: paramNodeId(input.name),
      kind: "param",
      x: (index % PER_ROW) * (NODE_W + GAP_X),
      y: row * (NODE_H + INFO_ROW_GAP),
      w: NODE_W,
      h: NODE_H,
      title: "Thông tin cần nhập",
      subtitle: input.label || humanize(input.name),
      row: row - infoRows,
      flip: false,
      input,
    });
  });

  const producer = new Map<string, string>(); // value name -> id of the step that read it
  const seen = new Set<string>();
  workflow.steps.forEach((step, index) => {
    const row = Math.floor(index / PER_ROW);
    const flip = row % 2 === 1;
    const column = flip ? PER_ROW - 1 - (index % PER_ROW) : index % PER_ROW;
    nodes.push({
      id: step.id,
      kind: "step",
      x: column * (NODE_W + GAP_X),
      y: stepsTop + row * (NODE_H + ROW_GAP),
      w: NODE_W,
      h: NODE_H,
      title: ACTION_LABEL[step.action] ?? step.action,
      subtitle: captionOf(step),
      row,
      flip,
      index: index + 1,
      step,
    });
    if (index > 0) {
      const previous = workflow.steps[index - 1]!.id;
      edges.push({ id: `${previous}->${step.id}:flow`, from: previous, to: step.id, kind: "flow" });
    }
    const used = [...placeholdersOf(step.value), ...placeholdersOf(step.tolerance), ...(step.inputs ?? [])];
    for (const name of used) {
      const from = producer.get(name) ?? (workflow.inputs.some((i) => i.name === name) ? paramNodeId(name) : null);
      if (from === null) continue;
      const id = `${from}->${step.id}:data:${name}`;
      if (seen.has(id)) continue;
      seen.add(id);
      edges.push({ id, from, to: step.id, kind: "data", carries: name });
    }
    if (step.save_as) producer.set(step.save_as, step.id);
  });

  return { nodes, edges };
}

/** Which side of each node a line leaves from and arrives at. */
export function sidesFor(edge: GraphEdge, from: Pick<GraphNode, "row" | "flip" | "kind">, to: Pick<GraphNode, "row" | "flip" | "kind">): [Side, Side] {
  if (edge.kind === "flow") {
    if (from.row === to.row) return from.flip ? ["left", "right"] : ["right", "left"];
    return ["bottom", "top"];
  }
  if (from.row === to.row) return ["bottom", "bottom"]; // a U under the row, so it never crosses a node
  return from.row < to.row ? ["bottom", "top"] : ["top", "bottom"];
}

export interface Point {
  x: number;
  y: number;
}

const NORMAL: Record<Side, Point> = { left: { x: -1, y: 0 }, right: { x: 1, y: 0 }, top: { x: 0, y: -1 }, bottom: { x: 0, y: 1 } };

/** A smooth line that leaves one port and arrives at another along the ports' own directions. */
export function connect(from: Point, fromSide: Side, to: Point, toSide: Side): string {
  const distance = Math.hypot(to.x - from.x, to.y - from.y);
  const reach = Math.min(160, Math.max(50, distance / 2));
  const a = NORMAL[fromSide];
  const b = NORMAL[toSide];
  return `M ${from.x} ${from.y} C ${from.x + a.x * reach} ${from.y + a.y * reach}, ${to.x + b.x * reach} ${to.y + b.y * reach}, ${to.x} ${to.y}`;
}

export function portPoint(node: Pick<GraphNode, "w" | "h">, at: Point, side: Side): Point {
  if (side === "left") return { x: at.x, y: at.y + node.h / 2 };
  if (side === "right") return { x: at.x + node.w, y: at.y + node.h / 2 };
  if (side === "top") return { x: at.x + node.w / 2, y: at.y };
  return { x: at.x + node.w / 2, y: at.y + node.h };
}

// ---- camera ----------------------------------------------------------------------------------------------------

export interface View {
  x: number;
  y: number;
  k: number;
}

export const MIN_ZOOM = 0.25;
export const MAX_ZOOM = 2;
/** Smallest scale at which a node's text is still comfortable to read. */
export const READABLE_ZOOM = 0.78;

type Box = Pick<GraphNode, "x" | "y" | "w" | "h">;

/** The view that shows every node, with a margin. */
export function fitView(nodes: Box[], width: number, height: number, margin = 48): View {
  if (nodes.length === 0 || width <= 0 || height <= 0) return { x: margin, y: margin, k: 1 };
  const left = Math.min(...nodes.map((n) => n.x));
  const top = Math.min(...nodes.map((n) => n.y));
  const right = Math.max(...nodes.map((n) => n.x + n.w));
  const bottom = Math.max(...nodes.map((n) => n.y + n.h));
  const k = Math.min(1, (width - 2 * margin) / (right - left), (height - 2 * margin) / (bottom - top));
  const clamped = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, k));
  return {
    k: clamped,
    x: (width - (right - left) * clamped) / 2 - left * clamped,
    y: (height - (bottom - top) * clamped) / 2 - top * clamped,
  };
}

/**
 * The view to open a flow with. Show everything when it fits at a readable size; otherwise
 * stay at the readable size from the top left and let the GDV pan.
 */
export function readableView(nodes: Box[], width: number, height: number, margin = 48): View {
  const fit = fitView(nodes, width, height, margin);
  if (fit.k >= READABLE_ZOOM || nodes.length === 0) return fit;
  const left = Math.min(...nodes.map((n) => n.x));
  const top = Math.min(...nodes.map((n) => n.y));
  return { k: READABLE_ZOOM, x: margin - left * READABLE_ZOOM, y: margin - top * READABLE_ZOOM };
}

/**
 * Keep a node comfortably on screen. Returns the same view when the node is already inside the
 * middle of the canvas, so a short flow never moves; otherwise the smallest slide that brings it
 * back with room to spare. The margin is smaller than the one a flow opens with (48), so a flow that
 * fits the screen never makes the camera move.
 */
export function ensureVisible(view: View, node: Box, width: number, height: number, margin = 40): View {
  if (width <= 0 || height <= 0) return view;
  const left = node.x * view.k + view.x;
  const top = node.y * view.k + view.y;
  const right = left + node.w * view.k;
  const bottom = top + node.h * view.k;
  let dx = 0;
  let dy = 0;
  if (left < margin) dx = margin - left;
  else if (right > width - margin) dx = width - margin - right;
  if (top < margin) dy = margin - top;
  else if (bottom > height - margin) dy = height - margin - bottom;
  return dx === 0 && dy === 0 ? view : { ...view, x: view.x + dx, y: view.y + dy };
}
