// Task 10.8: the admin page end to end, with logins on (ROOKIE_AUTH=dev, synthetic data only).
// A GDV learns a flow; the admin adds a node on the canvas and saves a draft; the PC's twin run makes it «đã chạy thử»;
// the admin cannot approve their own edit; the owner can; someone of another unit does not see the flow.
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { ADMIN_URL } from "../playwright.config";

function javaSession(id: string) {
  const rows: [string, string, string, string, string | null][] = [
    ["input", "Mock TPSS - Khách hàng (CIF)", "Số CIF hoặc CCCD", "text", "cif_number"],
    ["click", "Mock TPSS - Khách hàng (CIF)", "Tra cứu CIF", "push button", null],
  ];
  return rows.map(([type, url, label, tag, valueClass], seq) => ({
    schema_version: 1, engine: "java", session_id: id, seq, ts: "2026-11-19T09:15:03.000Z", type, url,
    target: { selectors: [`role=${tag}[name='${label}']`, `path=frame/a[${seq + 1}]`], label, tag },
    value: null, value_class: valueClass, api_calls: [],
  }));
}

const NODES = [
  { id: "a1", step_id: null, group: "g1", group_label: "Mở màn hình", label: "Mở màn hình → GET /tp/token", kind: "xhr", via: "xhr", method: "GET",
    url: "http://tp.local/tp/token?method=getToken", headers: "", body: "", links: {}, risk: "read", complete: true, unresolved: [], ms: 40, masked: 0 },
  { id: "a2", step_id: "s2", group: "g2", group_label: "Tra cứu", label: "Tra cứu → POST /tp/rpc", kind: "xhr", via: "xhr", method: "POST",
    url: "http://tp.local/tp/rpc", headers: "Authorization: Bearer ⟦l1⟧", body: "7|0|4|com.fis.tp.Service|find|⟦so_cif_hoac_cccd⟧|•••|",
    links: { l1: { from: "a1", whole: true } }, risk: "read", complete: true, unresolved: [], ms: 90, masked: 1 },
];

async function token(request: APIRequestContext, name: string) {
  const reply = await request.post(`${ADMIN_URL}/auth/login`, { data: { username: name, password: name, client: "agent" } });
  expect(reply.ok()).toBeTruthy();
  return { Authorization: "Bearer " + (await reply.json()).token };
}

async function login(page: Page, name: string) {
  await page.goto(`${ADMIN_URL}/admin/`);
  await page.fill("#loginUser", name);
  await page.fill("#loginPass", name);
  await page.click("#loginForm button");
  await expect(page.locator("#appView")).toBeVisible();
}

test("an admin edits a flow, cannot approve the edit, the owner approves it, another unit does not see it", async ({ browser, request }) => {
  const gdv1 = await token(request, "gdv1");
  const stamp = Date.now();
  const ids = [0, 1, 2].map((i) => `e2e-${stamp}-${i}`);
  for (const id of ids) {
    const sent = await request.post(`${ADMIN_URL}/sessions`, { headers: gdv1, data: { schema_version: 1, engine: "java", session_id: id, events: javaSession(id) } });
    expect(sent.status()).toBe(201);
  }
  const title = `Sao kê e2e ${stamp}`;
  const learned = await request.post(`${ADMIN_URL}/workflows/learn`, { headers: gdv1, data: { title, session_ids: ids } });
  expect(learned.status()).toBe(201);
  const flowId = (await learned.json()).workflow.id;
  expect((await request.put(`${ADMIN_URL}/workflows/${flowId}/versions/1/api`, { headers: gdv1, data: { api: NODES } })).ok()).toBeTruthy();

  // the admin adds a node on the canvas and saves a draft
  const admin = await browser.newPage();
  await login(admin, "quantri");
  await admin.click(`#flows li >> text=${title}`);
  await expect(admin.locator("#canvas g.node")).toHaveCount(2);
  await admin.click("#addHttp");
  await admin.fill("#inspector input >> nth=0", "Tải sao kê");
  await admin.fill("#inspector input >> nth=1", "http://tp.local/tp/statement?cif=⟦so_cif_hoac_cccd⟧");
  await admin.click("#inspector button.primary");
  await expect(admin.locator("#canvas g.node")).toHaveCount(3);
  await expect(admin.locator("#pending")).toHaveText("1 thay đổi chưa lưu");
  await admin.click("#save");
  await expect(admin.locator("#editMsg")).toContainText("bản nháp v2");

  // a template with data is refused, in words
  await admin.click("#addHttp");
  await admin.fill("#inspector input >> nth=0", "Xem");
  await admin.fill("#inspector input >> nth=1", "http://tp.local/tp/x?cif=0012345678");
  await admin.click("#inspector button.primary");
  await expect(admin.locator("#editMsg")).toContainText("giống dữ liệu");

  // the PC tried v2 on the twin (as «Chạy thử bản này» does)
  expect((await request.post(`${ADMIN_URL}/workflows/${flowId}/versions/2/test-runs`, { headers: gdv1, data: { status: "finished" } })).ok()).toBeTruthy();
  expect((await request.post(`${ADMIN_URL}/workflows/${flowId}/versions/2/status`, { headers: gdv1, data: { status: "tested" } })).ok()).toBeTruthy();

  // the admin edited v2: Duyệt is not theirs to press
  await admin.reload();
  await admin.click(`#flows li >> text=${title}`);
  await admin.click(".tabs button[data-tab=versions]");
  await expect(admin.locator("#versions button", { hasText: "Duyệt bản này" })).toBeDisabled();

  // the owner approves it
  const ownerContext = await browser.newContext();
  const owner = await ownerContext.newPage();
  await login(owner, "gdv1");
  await owner.click(`#flows li >> text=${title}`);
  await owner.click(".tabs button[data-tab=versions]");
  await owner.click("#versions button >> text=Duyệt bản này");
  await expect(owner.locator("#flows li.on")).toContainText("Đã duyệt");

  // someone of another unit does not see it
  const otherContext = await browser.newContext();
  const other = await otherContext.newPage();
  await login(other, "gdv2");
  await expect(other.locator("#flows li", { hasText: title })).toHaveCount(0);
});
