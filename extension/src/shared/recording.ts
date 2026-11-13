/** Turning what the content scripts report into events of the contract (`schemas/event.schema.json`). */
import { maskPath } from "./mask";

export interface DraftEvent {
  type: "click" | "input" | "select" | "submit";
  url: string;
  target: { selectors: string[]; label: string | null; tag: string | null };
  value: string | null;
  value_class: string | null;
}

export interface WebEvent {
  schema_version: 1;
  engine: "web";
  session_id: string;
  seq: number;
  ts: string;
  type: "click" | "input" | "select" | "navigate" | "submit";
  url: string;
  target: { selectors: string[]; label: string | null; tag: string | null } | null;
  value: string | null;
  value_class: string | null;
  api_calls: [];
  screenshot: null;
}

export interface RecordingState {
  recording: boolean;
  tabId: number | null;
  sessionId: string | null;
  name: string;
  host: string;
  events: WebEvent[];
}

export const idleRecording = (): RecordingState => ({ recording: false, tabId: null, sessionId: null, name: "", host: "", events: [] });

export function newSessionId(random: () => number = Math.random): string {
  return "s-" + Array.from({ length: 12 }, () => "0123456789abcdef"[Math.floor(random() * 16)]).join("");
}

function base(state: RecordingState, now: Date) {
  return { schema_version: 1 as const, engine: "web" as const, session_id: state.sessionId ?? "", seq: state.events.length, ts: now.toISOString(), api_calls: [] as [], screenshot: null };
}

export function appendDraft(state: RecordingState, draft: DraftEvent, now: Date = new Date()): RecordingState {
  const event: WebEvent = { ...base(state, now), type: draft.type, url: draft.url, target: draft.target, value: draft.value, value_class: draft.value_class };
  return { ...state, events: [...state.events, event] };
}

/** A move to another screen. The same address twice in a row is one move. */
export function appendNavigate(state: RecordingState, url: string, now: Date = new Date()): RecordingState {
  const path = maskPath(url);
  const last = [...state.events].reverse().find((event) => event.type === "navigate");
  const lastEvent = state.events[state.events.length - 1];
  if (last && last.url === path && lastEvent === last) return state;
  const event: WebEvent = { ...base(state, now), type: "navigate", url: path, target: null, value: null, value_class: null };
  return { ...state, events: [...state.events, event] };
}

/** Actions the GDV did, not counting the moves between screens. */
export const actionCount = (events: WebEvent[]): number => events.filter((event) => event.type !== "navigate").length;
