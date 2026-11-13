import { chromium, expect, test, type BrowserContext, type Page } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { MOCK_SITE_URL } from "../playwright.config";

const here = path.dirname(fileURLToPath(import.meta.url));
const extensionDir = path.resolve(here, "..", "..", "..", "extension", "dist");
const CIFS = ["00189091", "00224175", "00374087"]; // synthetic customers of the mock site (SEED = 42)

let context: BrowserContext;
let extensionId = "";

test.beforeAll(async () => {
  expect(fs.existsSync(path.join(extensionDir, "manifest.json")), "run `npm run build` in extension/ first").toBe(true);
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "rookie-ext-"));
  context = await chromium.launchPersistentContext(profile, {
    channel: "chromium",
    headless: true,
    args: [`--disable-extensions-except=${extensionDir}`, `--load-extension=${extensionDir}`],
  });
  let [worker] = context.serviceWorkers();
  if (!worker) worker = await context.waitForEvent("serviceworker");
  extensionId = new URL(worker.url()).host;
});

test.afterAll(async () => {
  await context.close();
});

async function login(site: Page): Promise<void> {
  await site.goto(`${MOCK_SITE_URL}/login`);
  await site.fill("#username", "gdv01");
  await site.fill("#password", "demo-only-1234");
  await site.click("#btn-login");
  await site.waitForURL("**/baocao/cuoingay");
}

/** The side panel, opened as a tab and pointed at the page to record (a real panel follows the active tab). */
async function openPanel(site: Page): Promise<Page> {
  const panel = await context.newPage();
  await panel.goto(`chrome-extension://${extensionId}/sidepanel.html`);
  const url = site.url();
  const tabId = await panel.evaluate(async (wanted) => (await chrome.tabs.query({ url: wanted.split("?")[0] }))[0]?.id, url);
  expect(tabId).toBeTruthy();
  await panel.goto(`chrome-extension://${extensionId}/sidepanel.html?tab=${tabId}`);
  return panel;
}

async function savedEvents(panel: Page): Promise<any[][]> {
  const stored = await panel.evaluate(async () => (await chrome.storage.local.get("rookie.recordings"))["rookie.recordings"] ?? []);
  return stored.map((item: any) => item.events);
}

test("records three CIF look-ups, keeps no customer number, and learns the steps", async () => {
  const site = await context.newPage();
  await login(site);
  await site.goto(`${MOCK_SITE_URL}/cif`);
  const panel = await openPanel(site);

  for (const [index, cif] of CIFS.entries()) {
    await site.goto(`${MOCK_SITE_URL}/cif`);
    await panel.fill("#rname", `lần ${index + 1}`);
    await panel.click("#record");
    await expect(panel.locator("#recstate")).toContainText("Đang ghi");
    await site.fill("#cif-query", cif);
    await site.press("#cif-query", "Tab"); // leaving the field is what commits the value
    await site.click("#btn-cif-search");
    await expect(site.locator("#tbl-cif tbody tr").first()).toBeVisible();
    await panel.click("#record");
    await expect(panel.locator("#recmsg")).toContainText("Đã ghi 2 thao tác");
  }

  await expect(panel.locator("#recordings .rec")).toHaveCount(3);
  const text = await panel.locator("#recordings").innerText();
  expect(text).toContain("Nhập vào «Số CIF hoặc CCCD»");
  expect(text).toContain("Bấm «Tra cứu CIF»");

  const stored = JSON.stringify(await savedEvents(panel));
  for (const cif of CIFS) expect(stored).not.toContain(cif);

  await panel.fill("#title", "Tra cứu CIF thử trên web");
  await panel.click("#learn");
  await expect(panel.locator("#learnmsg")).toContainText("Đã học việc", { timeout: 20000 });
  await expect(panel.locator("#learnmsg")).toContainText("Số CIF hoặc CCCD");
  await expect(panel.locator("#learnmsg")).toContainText("Tra cứu CIF");
});

test("follows the teller across a page change and never keeps a password or the user name", async () => {
  const site = await context.newPage();
  await site.goto(`${MOCK_SITE_URL}/logout`);
  await site.goto(`${MOCK_SITE_URL}/login`);
  const panel = await openPanel(site);

  await panel.click("#record");
  await expect(panel.locator("#recstate")).toContainText("Đang ghi");
  await site.fill("#username", "gdv01");
  await site.fill("#password", "demo-only-1234");
  await site.press("#password", "Tab");
  await site.click("#btn-login");
  await site.waitForURL("**/baocao/cuoingay");
  await site.getByLabel("Ngày báo cáo").fill("2026-11-12");
  await site.getByLabel("Ngày báo cáo").press("Tab"); // after the page change: the script must have been put in again
  await panel.click("#record");
  await expect(panel.locator("#recmsg")).toContainText("Đã ghi");

  const events = (await savedEvents(panel))[0] ?? [];
  const stored = JSON.stringify(events);
  expect(stored).not.toContain("demo-only-1234");
  expect(stored).not.toContain("gdv01");
  expect(events.map((event: any) => event.type)).toContain("navigate");
  const date = events.find((event: any) => event.type === "input" && event.target?.label === "Ngày báo cáo");
  expect(date?.value).toBe("2026-11-12");
  expect(events.some((event: any) => event.url === "/baocao/cuoingay")).toBe(true);
});

test("does not record while the teller has not pressed Ghi", async () => {
  const site = await context.newPage();
  await site.goto(`${MOCK_SITE_URL}/cif`);
  await site.fill("#cif-query", CIFS[0]!);
  await site.click("#btn-cif-search");
  const panel = await openPanel(site);
  const state = await panel.evaluate(async () => (await chrome.runtime.sendMessage({ type: "rookie-state" })));
  expect(state).toMatchObject({ ok: true, recording: false, actions: 0 });
});
