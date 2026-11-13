import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Relay } from "../src/shared/relay";
import { RpcClient, type PortLike } from "../src/shared/rpc";

class FakePort implements PortLike {
  sent: any[] = [];
  messageListeners: ((m: any) => void)[] = [];
  disconnectListeners: (() => void)[] = [];
  disconnected = false;
  onMessage = { addListener: (l: (m: any) => void) => void this.messageListeners.push(l) };
  onDisconnect = { addListener: (l: () => void) => void this.disconnectListeners.push(l) };
  postMessage(m: unknown) {
    this.sent.push(m);
  }
  disconnect() {
    this.disconnected = true;
  }
  receive(m: unknown) {
    this.messageListeners.forEach((l) => l(m));
  }
  drop() {
    this.disconnectListeners.forEach((l) => l());
  }
}

describe("RpcClient", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("matches replies to requests by id, in any order", async () => {
    const port = new FakePort();
    const rpc = new RpcClient(port);
    const first = rpc.request("status");
    const second = rpc.request("start", { session_id: "s1" });
    expect(port.sent).toEqual([{ id: 1, cmd: "status" }, { id: 2, cmd: "start", session_id: "s1" }]);
    port.receive({ id: 2, ok: true, session_id: "s1" });
    port.receive({ id: 1, ok: true, bridge: "ready" });
    await expect(first).resolves.toMatchObject({ bridge: "ready" });
    await expect(second).resolves.toMatchObject({ session_id: "s1" });
  });

  it("rejects with the agent's message when ok is false", async () => {
    const port = new FakePort();
    const rpc = new RpcClient(port);
    const reply = rpc.request("stop");
    port.receive({ id: 1, ok: false, error: "Chưa bắt đầu ghi." });
    await expect(reply).rejects.toThrow("Chưa bắt đầu ghi.");
  });

  it("gives up on a silent agent", async () => {
    const rpc = new RpcClient(new FakePort());
    const reply = rpc.request("status", {}, 5000);
    const failed = expect(reply).rejects.toThrow("không trả lời lệnh status");
    await vi.advanceTimersByTimeAsync(5001);
    await failed;
  });

  it("passes events to listeners and not to requests", () => {
    const port = new FakePort();
    const rpc = new RpcClient(port);
    const seen: any[] = [];
    const off = rpc.onEvent((e) => seen.push(e));
    port.receive({ event: "progress", step_id: "s1", status: "done" });
    off();
    port.receive({ event: "progress", step_id: "s2", status: "done" });
    expect(seen).toEqual([{ event: "progress", step_id: "s1", status: "done" }]);
  });

  it("fails every pending request when the port drops, and refuses new ones", async () => {
    const port = new FakePort();
    const rpc = new RpcClient(port);
    const closed: string[] = [];
    rpc.onClose((reason) => closed.push(reason));
    const reply = rpc.request("status");
    port.drop();
    await expect(reply).rejects.toThrow("Mất kết nối");
    await expect(rpc.request("status")).rejects.toThrow("Mất kết nối");
    expect(rpc.closed).toBe(true);
    expect(closed).toEqual(["Mất kết nối với agent."]);
  });

  it("treats agent_disconnected as a close with the browser's reason", async () => {
    const port = new FakePort();
    const rpc = new RpcClient(port);
    const reply = rpc.request("status");
    port.receive({ event: "agent_disconnected", error: "Specified native messaging host not found." });
    await expect(reply).rejects.toThrow("native messaging host not found");
  });

  it("ignores junk messages", () => {
    const port = new FakePort();
    new RpcClient(port);
    expect(() => [null, 5, "x", { id: 99, ok: true }].forEach((m) => port.receive(m))).not.toThrow();
  });
});

describe("Relay", () => {
  function setup(options: { failConnect?: string } = {}) {
    const host = new FakePort();
    const recording: boolean[] = [];
    let connects = 0;
    const relay = new Relay(
      () => {
        connects++;
        if (options.failConnect) throw new Error(options.failConnect);
        return host;
      },
      (on) => recording.push(on),
      () => "Specified native messaging host not found.",
    );
    const panelA = new FakePort();
    const panelB = new FakePort();
    relay.attach(panelA);
    relay.attach(panelB);
    return { host, recording, relay, panelA, panelB, connects: () => connects };
  }

  it("connects to the agent only when a view first asks, and once", () => {
    const { host, panelA, panelB, connects } = setup();
    expect(connects()).toBe(0);
    panelA.receive({ id: 1, cmd: "status" });
    panelB.receive({ id: 1, cmd: "status" });
    expect(connects()).toBe(1);
    expect(host.sent.map((m) => m.cmd)).toEqual(["status", "status"]);
  });

  it("sends each reply back to the view that asked, even when both used the same id", () => {
    const { host, panelA, panelB } = setup();
    panelA.receive({ id: 1, cmd: "status" });
    panelB.receive({ id: 1, cmd: "snapshot" });
    const [toA, toB] = host.sent;
    host.receive({ id: toB.id, ok: true, screen: {} });
    host.receive({ id: toA.id, ok: true, bridge: "ready" });
    expect(panelA.sent).toEqual([{ id: 1, ok: true, bridge: "ready" }]);
    expect(panelB.sent).toEqual([{ id: 1, ok: true, screen: {} }]);
  });

  it("broadcasts the agent's events to every view", () => {
    const { host, panelA, panelB } = setup();
    panelA.receive({ id: 1, cmd: "status" });
    host.receive({ event: "waiting", kind: "approve", step_id: "s8" });
    expect(panelA.sent).toContainEqual({ event: "waiting", kind: "approve", step_id: "s8" });
    expect(panelB.sent).toContainEqual({ event: "waiting", kind: "approve", step_id: "s8" });
  });

  it("keeps the recording badge truthful", () => {
    const { host, recording, panelA } = setup();
    panelA.receive({ id: 1, cmd: "start" });
    host.receive({ id: host.sent[0].id, ok: true });
    panelA.receive({ id: 2, cmd: "stop" });
    host.receive({ id: host.sent[1].id, ok: true, events: [] });
    expect(recording).toEqual([true, false]);
  });

  it("does not show recording when start was refused", () => {
    const { host, recording, panelA } = setup();
    panelA.receive({ id: 1, cmd: "start" });
    host.receive({ id: host.sent[0].id, ok: false, error: "Đang ghi." });
    expect(recording).toEqual([]);
  });

  it("tells every view when the agent is not installed", () => {
    const { panelA, panelB, recording } = setup({ failConnect: "Specified native messaging host not found." });
    panelA.receive({ id: 1, cmd: "status" });
    const expected = { event: "agent_disconnected", error: "Specified native messaging host not found." };
    expect(panelA.sent).toEqual([expected]);
    expect(panelB.sent).toEqual([expected]);
    expect(recording).toEqual([false]);
  });

  it("tells every view when the agent goes away, and reconnects on the next request", () => {
    const { host, panelA, panelB, connects } = setup();
    panelA.receive({ id: 1, cmd: "status" });
    host.drop();
    expect(panelB.sent.at(-1)).toMatchObject({ event: "agent_disconnected" });
    panelA.receive({ id: 2, cmd: "status" });
    expect(connects()).toBe(2);
  });

  it("stops sending to a view that closed", () => {
    const { host, panelA, panelB } = setup();
    panelA.receive({ id: 1, cmd: "status" });
    panelB.drop();
    host.receive({ event: "progress", step_id: "s1", status: "done" });
    expect(panelB.sent).toEqual([]);
    expect(panelA.sent).toHaveLength(1);
  });
});
