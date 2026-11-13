/**
 * The background script's whole job: connect the side panel (and any extra view such as the
 * full-tab canvas) to the Windows agent. It forwards requests unchanged, routes each reply
 * to the view that asked, broadcasts the agent's events to every view, and keeps the
 * "recording" badge truthful.
 */
import type { PortLike } from "./rpc";

export const HOST_NAME = "com.rookie_agent.host";

interface Route {
  panel: number;
  id: number;
  cmd: string;
}

export class Relay {
  private readonly panels = new Map<number, PortLike>();
  private readonly routes = new Map<number, Route>();
  private host: PortLike | null = null;
  private nextPanel = 1;
  private nextGlobalId = 1;

  constructor(
    private readonly connectHost: () => PortLike,
    private readonly setRecording: (recording: boolean) => void,
    /** The browser's reason for the last failed native connection, if any. */
    private readonly lastError: () => string | undefined = () => undefined,
  ) {}

  attach(port: PortLike): void {
    const panel = this.nextPanel++;
    this.panels.set(panel, port);
    port.onMessage.addListener((message) => this.fromPanel(panel, message));
    port.onDisconnect.addListener(() => this.panels.delete(panel));
  }

  private ensureHost(): PortLike | null {
    if (this.host) return this.host;
    try {
      const host = this.connectHost();
      host.onMessage.addListener((message) => this.fromHost(message));
      host.onDisconnect.addListener(() => this.hostGone(this.lastError()));
      this.host = host;
      return host;
    } catch (error) {
      this.hostGone(error instanceof Error ? error.message : String(error));
      return null;
    }
  }

  private fromPanel(panel: number, message: any): void {
    if (message === null || typeof message !== "object" || typeof message.id !== "number") return;
    const host = this.ensureHost();
    if (!host) return; // hostGone already told every view
    const id = this.nextGlobalId++;
    this.routes.set(id, { panel, id: message.id, cmd: String(message.cmd) });
    try {
      host.postMessage({ ...message, id });
    } catch (error) {
      this.routes.delete(id);
      this.hostGone(error instanceof Error ? error.message : String(error));
    }
  }

  private fromHost(message: any): void {
    if (message === null || typeof message !== "object") return;
    if (typeof message.id === "number") {
      const route = this.routes.get(message.id);
      if (!route) return;
      this.routes.delete(message.id);
      if (message.ok === true && route.cmd === "start") this.setRecording(true);
      if (route.cmd === "stop") this.setRecording(false);
      this.panels.get(route.panel)?.postMessage({ ...message, id: route.id });
      return;
    }
    if (typeof message.event === "string") {
      for (const port of this.panels.values()) port.postMessage(message);
    }
  }

  private hostGone(reason: string | undefined): void {
    this.host = null;
    this.routes.clear();
    this.setRecording(false);
    const text = reason || "Agent chưa được cài hoặc chưa đăng ký với trình duyệt.";
    for (const port of this.panels.values()) port.postMessage({ event: "agent_disconnected", error: text });
  }
}
