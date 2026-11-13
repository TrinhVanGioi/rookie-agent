/** Calls to the Rookie Agent server. Events are checked against the schema before they leave the browser. */
import { validateEvent } from "./validate";

export interface WorkflowStep {
  id: string;
  action: string;
  target?: { selectors: string[]; label?: string | null; tag?: string | null };
  value?: string;
  url?: string;
  save_as?: string;
  inputs?: string[];
  key?: string;
  tolerance?: string | number;
  risk: "read" | "write" | "money";
  mode: "auto" | "review" | "approve";
}

export interface WorkflowInput {
  name: string;
  /** What the GDV sees on screen for this field, e.g. "Số tiền". */
  label?: string | null;
  type: string;
  value_class?: string | null;
  default?: string | number | null;
}

export interface Workflow {
  schema_version: 1;
  engine: "web" | "java";
  id: string;
  /** The name the GDV gave this agent, in their own words. */
  title?: string;
  version: number;
  status: "draft" | "tested" | "approved";
  inputs: WorkflowInput[];
  steps: WorkflowStep[];
}

export interface WorkflowReply {
  workflow: Workflow;
  digest: string;
  warnings: string[];
}

export interface WorkflowSummary {
  id: string;
  title?: string | null;
  version: number;
  status: string;
  engine: string;
}

export interface SessionSummary {
  session_id: string;
  engine: string;
  created_at: string;
  event_count: number;
}

export class ServerError extends Error {}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export class ServerApi {
  readonly baseUrl: string;

  constructor(baseUrl: string, private readonly fetchFn: FetchLike = (input, init) => fetch(input, init)) {
    this.baseUrl = baseUrl.trim().replace(/\/+$/, "");
  }

  private async call<T>(method: string, path: string, body?: unknown): Promise<T> {
    let response: Response;
    try {
      response = await this.fetchFn(this.baseUrl + path, {
        method,
        headers: body === undefined ? undefined : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (error) {
      throw new ServerError(`Không kết nối được máy chủ ${this.baseUrl}.`);
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.join("; ") : data.detail;
      throw new ServerError(`Máy chủ từ chối (${response.status}): ${detail ?? response.statusText}`);
    }
    return data as T;
  }

  health(): Promise<{ status: string }> {
    return this.call("GET", "/health");
  }

  /** Validate every event first: a recording that breaks the schema, or still carries a sensitive value, is not sent. */
  postSession(sessionId: string, engine: "web" | "java", events: unknown[]): Promise<SessionSummary> {
    const problems: string[] = [];
    events.forEach((event, index) => {
      const errors = validateEvent(event);
      if (errors.length > 0) problems.push(`sự kiện ${index}: ${errors[0]}`);
    });
    if (problems.length > 0) {
      return Promise.reject(new ServerError("Phiên ghi không hợp lệ, chưa gửi: " + problems.slice(0, 3).join("; ")));
    }
    return this.call("POST", "/sessions", { schema_version: 1, engine, session_id: sessionId, events });
  }

  async listSessions(): Promise<SessionSummary[]> {
    return (await this.call<{ sessions: SessionSummary[] }>("GET", "/sessions")).sessions;
  }

  /** The GDV names the agent in their own words; the server makes the id. */
  learn(title: string, sessionIds: string[]): Promise<WorkflowReply> {
    return this.call("POST", "/workflows/learn", { title, session_ids: sessionIds });
  }

  /** Change how much control some steps have. Gives a new draft version; the old one stays. */
  revise(workflowId: string, version: number, modes: Record<string, string>): Promise<WorkflowReply> {
    return this.call("POST", `/workflows/${encodeURIComponent(workflowId)}/versions/${version}/revise`, { modes });
  }

  async listWorkflows(): Promise<WorkflowSummary[]> {
    return (await this.call<{ workflows: WorkflowSummary[] }>("GET", "/workflows")).workflows;
  }

  getVersion(workflowId: string, version: number): Promise<WorkflowReply> {
    return this.call("GET", `/workflows/${encodeURIComponent(workflowId)}/versions/${version}`);
  }

  setStatus(workflowId: string, version: number, status: "tested" | "approved"): Promise<WorkflowReply> {
    return this.call("POST", `/workflows/${encodeURIComponent(workflowId)}/versions/${version}/status`, { status });
  }
}
