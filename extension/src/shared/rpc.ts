/**
 * Request/response over a message port, plus events the other side sends on its own.
 *
 * Used twice with the same wire format: side panel <-> background (relay) and, through the
 * relay, side panel <-> Windows agent (Native Messaging host). Requests carry a numeric `id`;
 * replies echo it and have `ok`; anything with an `event` field is an unsolicited event.
 */

export interface PortLike {
  postMessage(message: unknown): void;
  onMessage: { addListener(listener: (message: any) => void): void };
  onDisconnect: { addListener(listener: () => void): void };
  disconnect(): void;
}

export interface AgentEvent {
  event: string;
  [key: string]: any;
}

export type Reply = { ok: true; [key: string]: any };

interface Pending {
  resolve(value: any): void;
  reject(error: Error): void;
  timer: ReturnType<typeof setTimeout>;
}

export class RpcClient {
  private nextId = 1;
  private readonly pending = new Map<number, Pending>();
  private readonly eventListeners = new Set<(event: AgentEvent) => void>();
  private readonly closeListeners = new Set<(reason: string) => void>();
  private closedReason: string | null = null;

  constructor(private readonly port: PortLike) {
    port.onMessage.addListener((message) => this.receive(message));
    port.onDisconnect.addListener(() => this.close("Mất kết nối với agent."));
  }

  get closed(): boolean {
    return this.closedReason !== null;
  }

  request<T = Reply>(cmd: string, payload: Record<string, unknown> = {}, timeoutMs = 20000): Promise<T> {
    if (this.closedReason !== null) return Promise.reject(new Error(this.closedReason));
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Agent không trả lời lệnh ${cmd} sau ${Math.round(timeoutMs / 1000)} giây.`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      try {
        this.port.postMessage({ id, cmd, ...payload });
      } catch (error) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(error instanceof Error ? error : new Error(String(error)));
      }
    });
  }

  onEvent(listener: (event: AgentEvent) => void): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  onClose(listener: (reason: string) => void): () => void {
    this.closeListeners.add(listener);
    return () => this.closeListeners.delete(listener);
  }

  private receive(message: any): void {
    if (message === null || typeof message !== "object") return;
    if (typeof message.event === "string") {
      if (message.event === "agent_disconnected") {
        this.close(typeof message.error === "string" && message.error ? message.error : "Mất kết nối với agent.");
        return;
      }
      for (const listener of [...this.eventListeners]) listener(message as AgentEvent);
      return;
    }
    const pending = typeof message.id === "number" ? this.pending.get(message.id) : undefined;
    if (!pending) return;
    this.pending.delete(message.id);
    clearTimeout(pending.timer);
    if (message.ok === false) pending.reject(new Error(String(message.error ?? "Agent báo lỗi.")));
    else pending.resolve(message);
  }

  private close(reason: string): void {
    if (this.closedReason !== null) return;
    this.closedReason = reason;
    for (const [id, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(new Error(reason));
      this.pending.delete(id);
    }
    for (const listener of [...this.closeListeners]) listener(reason);
  }

  disconnect(): void {
    this.close("Đã ngắt kết nối.");
    this.port.disconnect();
  }
}
