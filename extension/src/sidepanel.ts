/** The side panel: Ghi (record) and Học (learn). Plain business words only; no ids or selectors. */
import { friendlyStep, MODE_WORDS, RISK_WORDS } from "./shared/event-words";
import { deleteRecording, listRecordings, markUploaded, type SavedRecording } from "./shared/recordings-store";
import { ServerApi, ServerError } from "./shared/server-api";

const $ = <T extends HTMLElement = HTMLElement>(id: string): T => document.getElementById(id) as T;
const DEFAULT_SERVER = "http://localhost:8000";
const SETTINGS_KEY = "rookie.settings";

function el<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, className?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function say(target: string, text: string, kind: "ok" | "bad" = "ok"): void {
  const box = $(target);
  box.textContent = "";
  if (text) box.append(el("div", text, `msg ${kind}`));
}

async function background<T = Record<string, any>>(message: Record<string, unknown>): Promise<T> {
  const reply = await chrome.runtime.sendMessage(message);
  if (!reply?.ok) throw new Error(reply?.error ?? "Không nhận được trả lời từ extension.");
  return reply as T;
}

/** The tab to record: `?tab=ID` (used by tests), else the active tab of the window. */
async function targetTab(): Promise<chrome.tabs.Tab> {
  const wanted = Number(new URLSearchParams(location.search).get("tab"));
  if (wanted) return chrome.tabs.get(wanted);
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab) throw new Error("Không thấy thẻ trình duyệt nào đang mở.");
  return tab;
}

async function allowSite(url: string): Promise<void> {
  const origin = new URL(url).origin + "/*";
  const granted = await chrome.permissions.request({ origins: [origin] });
  if (!granted) throw new Error("Cần cho phép extension ghi trên trang này. Bấm lại và chọn Cho phép.");
}

let recording = false;

function showState(state: { recording: boolean; host?: string; actions?: number }): void {
  recording = state.recording;
  const button = $<HTMLButtonElement>("record");
  button.textContent = recording ? "Dừng ghi" : "Bắt đầu ghi";
  button.className = recording ? "stop" : "primary";
  const info = $("recstate");
  info.textContent = "";
  if (recording) {
    info.append(el("span", undefined, "recdot"), document.createTextNode(`Đang ghi · ${state.actions ?? 0} thao tác`));
  }
  $("host").textContent = recording ? (state.host ?? "") : "";
}

async function refreshState(): Promise<void> {
  try {
    showState(await background({ type: "rookie-state" }));
  } catch {
    /* the worker is starting up */
  }
}

async function renderRecordings(): Promise<void> {
  const box = $("recordings");
  box.textContent = "";
  for (const item of await listRecordings(chrome.storage.local)) {
    const row = el("div", undefined, "rec");
    const pick = el("input");
    pick.type = "checkbox";
    pick.dataset.id = item.session_id;
    pick.checked = !item.uploaded;
    const body = el("div", undefined, "body");
    body.append(el("div", `${item.name || "Bản ghi"} — ${item.saved_at}`));
    if (item.uploaded) body.append(el("div", "Đã gửi lên máy chủ", "detail"));
    const steps = el("ol", undefined, "steps");
    for (const event of item.events) {
      steps.append(el("li", friendlyStep(event.type, event.target?.label, event.url)));
    }
    body.append(steps);
    const typed = item.events.filter((event) => event.type === "input");
    body.append(el("div", `${typed.length} ô đã nhập, giá trị được lưu: ${typed.filter((event) => event.value !== null).length}`, "detail"));
    const remove = el("button", "Xóa");
    remove.onclick = async () => {
      await deleteRecording(chrome.storage.local, item.session_id);
      void renderRecordings();
    };
    row.append(pick, body, remove);
    box.append(row);
  }
}

$("record").onclick = async () => {
  const button = $<HTMLButtonElement>("record");
  button.disabled = true;
  say("recmsg", "");
  try {
    if (!recording) {
      const tab = await targetTab();
      if (!tab.url || !/^https?:/.test(tab.url) || tab.id === undefined) throw new Error("Mở trang web cần ghi ở thẻ đang chọn rồi bấm lại.");
      await allowSite(tab.url);
      await background({ type: "rookie-start", tabId: tab.id, name: $<HTMLInputElement>("rname").value });
      await refreshState();
    } else {
      const result = await background<{ actions: number }>({ type: "rookie-stop" });
      $<HTMLInputElement>("rname").value = "";
      showState({ recording: false });
      say("recmsg", `Đã ghi ${result.actions} thao tác.`);
      await renderRecordings();
    }
  } catch (error) {
    say("recmsg", (error as Error).message, "bad");
  }
  button.disabled = false;
};

async function checkServer(): Promise<ServerApi | null> {
  const url = $<HTMLInputElement>("server").value.trim() || DEFAULT_SERVER;
  try {
    const origin = new URL(url).origin + "/*";
    if (!(await chrome.permissions.contains({ origins: [origin] })) && !(await chrome.permissions.request({ origins: [origin] }))) {
      throw new ServerError("Cần cho phép extension kết nối tới máy chủ này.");
    }
    const api = new ServerApi(url);
    await api.health();
    await chrome.storage.local.set({ [SETTINGS_KEY]: { server: url } });
    say("servermsg", "Kết nối được máy chủ.");
    return api;
  } catch (error) {
    say("servermsg", error instanceof TypeError ? "Địa chỉ máy chủ chưa đúng." : (error as Error).message, "bad");
    return null;
  }
}
$("serverCheck").onclick = () => void checkServer();

$("learn").onclick = async () => {
  const picked = Array.from(document.querySelectorAll<HTMLInputElement>("#recordings input[type=checkbox]:checked")).map((box) => box.dataset.id ?? "");
  const title = $<HTMLInputElement>("title").value.trim();
  const button = $<HTMLButtonElement>("learn");
  if (picked.length < 2) return say("learnmsg", "Chọn ít nhất 2 bản ghi của cùng một việc. Nên ghi 3 lần.", "bad");
  if (!title) return say("learnmsg", "Đặt tên cho việc này, ví dụ: Vấn tin tài khoản.", "bad");
  button.disabled = true;
  say("learnmsg", "Đang học...");
  try {
    const api = await checkServer();
    if (!api) {
      say("learnmsg", "");
      button.disabled = false;
      return;
    }
    const all = await listRecordings(chrome.storage.local);
    const chosen = all.filter((item: SavedRecording) => picked.includes(item.session_id));
    for (const item of chosen) await api.postSession(item.session_id, "web", item.events);
    await markUploaded(chrome.storage.local, picked);
    const reply = await api.learn(title, picked);
    const box = $("learnmsg");
    box.textContent = "";
    const msg = el("div", undefined, "msg ok");
    msg.append(el("div", `Đã học việc «${reply.workflow.title ?? title}». Agent hiểu các bước sau:`));
    const steps = el("ol", undefined, "steps");
    for (const step of reply.workflow.steps) {
      const item = el("li", friendlyStep(step.action, step.target?.label, step.url));
      item.append(el("div", `Mức rủi ro: ${RISK_WORDS[step.risk] ?? step.risk}. Khi chạy: ${MODE_WORDS[step.mode] ?? step.mode}.`, "detail"));
      steps.append(item);
    }
    msg.append(steps);
    const names = reply.workflow.inputs.map((input) => input.label || input.name);
    msg.append(el("div", names.length ? `Thông tin thay đổi mỗi lần: ${names.join(", ")}` : "Không có thông tin nào thay đổi giữa các lần ghi.", "detail"));
    for (const warning of reply.warnings) msg.append(el("div", `Lưu ý: ${warning}`, "detail"));
    box.append(msg);
    await renderRecordings();
  } catch (error) {
    say("learnmsg", (error as Error).message, "bad");
  }
  button.disabled = false;
};

chrome.storage.onChanged.addListener((_changes, area) => {
  if (area === "session") void refreshState();
});

void (async () => {
  const saved = (await chrome.storage.local.get(SETTINGS_KEY))[SETTINGS_KEY] as { server?: string } | undefined;
  $<HTMLInputElement>("server").value = saved?.server ?? DEFAULT_SERVER;
  await refreshState();
  await renderRecordings();
  // The server starts with Windows; say at once whether it is reachable, without asking for any permission.
  const origin = new URL($<HTMLInputElement>("server").value).origin + "/*";
  if (await chrome.permissions.contains({ origins: [origin] })) void checkServer();
})();
