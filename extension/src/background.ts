/**
 * Service worker: keeps the recording state, receives events from the pages, saves the finished recording
 * and shows the "REC" badge while recording. It only records the tab the GDV chose when pressing Ghi.
 */
import { actionCount, appendDraft, appendNavigate, idleRecording, newSessionId, type DraftEvent, type RecordingState } from "./shared/recording";
import { saveRecording } from "./shared/recordings-store";

const STATE_KEY = "rookie.rec";

async function load(): Promise<RecordingState> {
  const found = (await chrome.storage.session.get(STATE_KEY))[STATE_KEY];
  return (found as RecordingState | undefined) ?? idleRecording();
}

async function store(state: RecordingState): Promise<void> {
  await chrome.storage.session.set({ [STATE_KEY]: state });
  await chrome.action.setBadgeText({ text: state.recording ? "REC" : "" });
  if (state.recording) await chrome.action.setBadgeBackgroundColor({ color: "#c62828" });
}

// One change at a time, so two events that arrive together are both kept, in order.
let chain: Promise<unknown> = Promise.resolve();
function serial<T>(task: () => Promise<T>): Promise<T> {
  const next = chain.then(task, task);
  chain = next.catch(() => undefined);
  return next;
}

async function inject(tabId: number, frameId?: number): Promise<void> {
  try {
    await chrome.scripting.executeScript({
      target: frameId === undefined ? { tabId, allFrames: true } : { tabId, frameIds: [frameId] },
      files: ["content.js"],
    });
  } catch {
    // A page the browser does not let us into (or no permission for that site): nothing to record there.
  }
}

async function start(tabId: number, name: string): Promise<Record<string, unknown>> {
  const state = await load();
  if (state.recording) throw new Error("Đang ghi. Bấm Dừng ghi trước khi ghi lần mới.");
  const tab = await chrome.tabs.get(tabId);
  if (!tab.url || !/^https?:/.test(tab.url)) throw new Error("Mở trang web cần ghi ở thẻ đang chọn rồi bấm lại.");
  let next: RecordingState = { ...idleRecording(), recording: true, tabId, sessionId: newSessionId(), name, host: new URL(tab.url).host };
  next = appendNavigate(next, tab.url);
  await store(next);
  await inject(tabId);
  return { recording: true, host: next.host };
}

async function stop(): Promise<Record<string, unknown>> {
  const state = await load();
  if (!state.recording || state.tabId === null) throw new Error("Chưa bắt đầu ghi.");
  chrome.tabs.sendMessage(state.tabId, { type: "rookie-recording", recording: false }).catch(() => undefined);
  await store(idleRecording());
  if (actionCount(state.events) === 0) throw new Error("Chưa ghi được thao tác nào. Hãy thao tác trên trang sau khi bấm Bắt đầu ghi, rồi mới Dừng.");
  await saveRecording(chrome.storage.local, {
    session_id: state.sessionId ?? "",
    name: state.name,
    saved_at: new Date().toLocaleString("vi-VN"),
    host: state.host,
    uploaded: false,
    events: state.events,
  });
  return { session_id: state.sessionId, events: state.events.length, actions: actionCount(state.events) };
}

async function discard(): Promise<Record<string, unknown>> {
  const state = await load();
  if (state.tabId !== null) chrome.tabs.sendMessage(state.tabId, { type: "rookie-recording", recording: false }).catch(() => undefined);
  await store(idleRecording());
  return {};
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const run = async (): Promise<Record<string, unknown>> => {
    switch (message?.type) {
      case "rookie-hello": {
        const state = await load();
        return { recording: state.recording && sender.tab?.id === state.tabId };
      }
      case "rookie-event": {
        const state = await load();
        if (!state.recording || sender.tab?.id !== state.tabId) return {};
        await store(appendDraft(state, message.event as DraftEvent));
        return {};
      }
      case "rookie-state": {
        const state = await load();
        return { recording: state.recording, host: state.host, actions: actionCount(state.events), tabId: state.tabId };
      }
      case "rookie-start":
        return start(Number(message.tabId), String(message.name ?? ""));
      case "rookie-stop":
        return stop();
      case "rookie-discard":
        return discard();
      default:
        return { ignored: true };
    }
  };
  serial(run).then((reply) => sendResponse({ ok: true, ...reply }), (error: Error) => sendResponse({ ok: false, error: error.message }));
  return true;
});

// Moves between screens, and pages that load while recording (a frame that was not there when Ghi was pressed).
chrome.webNavigation.onCommitted.addListener((details) => {
  if (details.frameId !== 0) return;
  void serial(async () => {
    const state = await load();
    if (state.recording && state.tabId === details.tabId) await store(appendNavigate(state, details.url));
  });
});
for (const event of [chrome.webNavigation.onHistoryStateUpdated, chrome.webNavigation.onReferenceFragmentUpdated]) {
  event.addListener((details) => {
    if (details.frameId !== 0) return;
    void serial(async () => {
      const state = await load();
      if (state.recording && state.tabId === details.tabId) await store(appendNavigate(state, details.url));
    });
  });
}
chrome.webNavigation.onDOMContentLoaded.addListener((details) => {
  void serial(async () => {
    const state = await load();
    if (state.recording && state.tabId === details.tabId) await inject(details.tabId, details.frameId);
  });
});

void chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
void load().then((state) => store(state));
