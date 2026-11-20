// Rookie Agent: the admin page for flows (task 10.6; docs/design.md 13). Plain JS, no build, nothing from outside.
// The server checks every rule: each change is sent for a preview (POST …/edit/preview) and the canvas shows what the server returns.
// Text from the server is always put with textContent, never as HTML.
"use strict";

const $ = (id) => document.getElementById(id);
const RISK = { read: "Chỉ xem", write: "Ghi dữ liệu", money: "Liên quan tiền" };
const RISK_RANK = { read: 0, write: 1, money: 2 };
const MODE = { auto: "Tự làm", review: "Cho xem trước", approve: "Chờ Duyệt" };
const MODE_RANK = { auto: 0, review: 1, approve: 2 };
const STATUS = { draft: "Nháp", tested: "Đã chạy thử", approved: "Đã duyệt" };
const VIS = { private: "Riêng", unit: "Đơn vị", all: "Toàn ngân hàng" };
const ACTION = { goto: "Mở trang", click: "Bấm", fill: "Nhập", select: "Chọn", submit: "Gửi", read_value: "Đọc", wait_for: "Chờ",
  extract_table: "Đọc bảng", read_fields: "Đọc các ô", compare: "Đối chiếu", save: "Lưu" };
const RUN_STATUS = { finished: "Xong", failed: "Lỗi", stopped: "Đã dừng", waiting: "Đang chờ" };
const NODE_W = 190, NODE_H = 62, GAP_X = 50, GAP_Y = 70, TOP = 56;

const state = { me: null, mode: "off", rows: [], summary: {}, flow: null };

function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined && text !== null) e.textContent = String(text);
  if (cls) e.className = cls;
  return e;
}
function say(id, text, kind) { const box = $(id); box.textContent = text || ""; box.className = "msg" + (kind ? " " + kind : ""); }
function detailText(data) {
  if (!data) return "";
  const d = data.detail;
  if (Array.isArray(d)) return d.map((x) => (typeof x === "string" ? x : x.msg || JSON.stringify(x))).join("; ");
  return typeof d === "string" ? d : "";
}
async function api(method, path, body) {
  const options = { method, credentials: "same-origin", headers: {} };
  if (body !== undefined) { options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
  const reply = await fetch(path, options);
  let data = null;
  try { data = await reply.json(); } catch (e) { data = null; }
  if (reply.status === 401 && !path.startsWith("/auth/")) { showLogin(); }
  if (!reply.ok) throw new Error(detailText(data) || "Máy chủ trả lỗi " + reply.status);
  return data;
}
const enc = encodeURIComponent;

// ---- login ------------------------------------------------------------------------------------------------------------------

function showLogin() { $("appView").hidden = true; $("loginView").hidden = false; $("logout").hidden = true; $("whoName").textContent = ""; }

$("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("POST", "/auth/login", { username: $("loginUser").value, password: $("loginPass").value, client: "admin" });
    $("loginPass").value = "";
    await start();
  } catch (e) { $("loginPass").value = ""; say("loginMsg", e.message, "bad"); }
});
$("logout").onclick = async () => { try { await api("POST", "/auth/logout", {}); } catch (e) { /* the cookie is dropped anyway */ } showLogin(); };

function isAdmin() { return !!state.me && state.me.roles.includes("admin"); }
function canChange(meta) { return isAdmin() || (!!meta.owner && meta.owner === state.me.name); }
function isOwner(meta) { return !!meta.owner && meta.owner === state.me.name; }

async function start() {
  let me;
  // task 11.5: opened from the teller's own Rookie page: a one-time code signs in as the same person; ?flow= opens that flow
  const params = new URLSearchParams(location.search);
  if (params.get("code")) {
    try { await api("POST", "/auth/exchange", { code: params.get("code") }); } catch (e) { say("loginMsg", e.message, "bad"); }
    params.delete("code");
    history.replaceState(null, "", location.pathname + (params.toString() ? "?" + params.toString() : ""));
  }
  try { me = await api("GET", "/auth/me"); } catch (e) { showLogin(); return; }
  state.me = me.user; state.mode = me.mode;
  $("offBanner").hidden = me.mode !== "off";
  $("loginView").hidden = true; $("appView").hidden = false;
  $("whoName").textContent = me.user.display + (me.user.unit ? " · " + me.user.unit : "") + (isAdmin() ? " · quản trị" : "");
  $("logout").hidden = me.mode === "off";
  await loadList();
  const wanted = new URLSearchParams(location.search).get("flow");
  if (wanted && flowsById().some((f) => f.id === wanted)) await openFlow(wanted);
}

// ---- the list -----------------------------------------------------------------------------------------------------------------

async function loadList() {
  const [list, summary] = await Promise.all([api("GET", "/workflows"), api("GET", "/runs/summary")]);
  state.rows = list.workflows; state.summary = summary.flows || {};
  const owners = new Map(), units = new Set();
  for (const r of state.rows) { owners.set(r.owner || "", r.owner_display); if (r.unit) units.add(r.unit); }
  fillSelect($("fOwner"), "Mọi người tạo", [...owners].map(([k, v]) => [k, v]));
  fillSelect($("fUnit"), "Mọi đơn vị", [...units].sort().map((u) => [u, u]));
  drawList();
}
function fillSelect(select, first, pairs) {
  const keep = select.value; select.textContent = "";
  select.append(new Option(first, ""));
  for (const [value, text] of pairs) select.append(new Option(text, value));
  select.value = pairs.some(([v]) => v === keep) ? keep : "";
}
function flowsById() {
  const byId = new Map();
  for (const r of state.rows) {
    const f = byId.get(r.id) || { id: r.id, versions: [] };
    f.versions.push(r); byId.set(r.id, f);
  }
  for (const f of byId.values()) {
    f.versions.sort((a, b) => a.version - b.version);
    f.latest = f.versions[f.versions.length - 1];
    f.approved = [...f.versions].reverse().find((v) => v.status === "approved") || null;
  }
  return [...byId.values()];
}
function drawList() {
  const text = $("fText").value.trim().toLowerCase(), owner = $("fOwner").value, unit = $("fUnit").value;
  const status = $("fStatus").value, risk = $("fRisk").value;
  const flows = flowsById().filter((f) => {
    const l = f.latest;
    return (!text || (l.title || f.id).toLowerCase().includes(text)) && (!owner || (l.owner || "") === owner) && (!unit || l.unit === unit)
      && (!status || l.status === status) && (!risk || l.max_risk === risk);
  }).sort((a, b) => (b.latest.created_at || "").localeCompare(a.latest.created_at || ""));
  const box = $("flows"); box.textContent = "";
  $("flowCount").textContent = flows.length + " luồng";
  for (const f of flows) {
    const l = f.latest, runs = state.summary[f.id];
    const li = el("li"); li.dataset.id = f.id;
    if (state.flow && state.flow.id === f.id) li.classList.add("on");
    li.append(el("div", l.title || f.id, "t"), el("div", l.owner_display + (l.unit ? " · " + l.unit : "") + " · " + VIS[l.visibility], "m"));
    const badges = el("div", undefined, "badges");
    badges.append(el("span", "v" + l.version + " " + STATUS[l.status], "chip " + l.status));
    if (f.approved && f.approved !== l) badges.append(el("span", "đang dùng v" + f.approved.version, "chip approved"));
    badges.append(el("span", RISK[l.max_risk], "chip " + l.max_risk));
    if (runs) badges.append(el("span", runs.runs + " lần chạy" + (runs.failed ? " · " + Math.round(100 * runs.failed / runs.runs) + "% lỗi" : ""), "chip"));
    if (runs && runs.saved_s !== undefined) badges.append(el("span", "tiết kiệm ~" + (runs.saved_s >= 90 ? (runs.saved_s / 60).toFixed(1).replace(".", ",") + " phút" : Math.round(runs.saved_s) + " giây") + "/lần", "chip read"));
    const sadpt = runs && runs.sadpt;
    if (sadpt && sadpt.ui_changes) badges.append(el("span", "tự phục hồi " + Math.round(100 * sadpt.ui_recovered / sadpt.ui_changes) + "%", "chip read"));
    if (sadpt && sadpt.overreach) badges.append(el("span", "vượt quyền " + sadpt.overreach, "chip money"));
    li.append(badges);
    li.onclick = () => openFlow(f.id);
    box.append(li);
  }
}
for (const id of ["fText", "fOwner", "fUnit", "fStatus", "fRisk"]) $(id).addEventListener("input", drawList);

// ---- one flow -----------------------------------------------------------------------------------------------------------------

async function openFlow(id, version) {
  const f = flowsById().find((x) => x.id === id);
  if (!f) return;
  const v = version || f.latest.version;
  const [reply, layout] = await Promise.all([api("GET", `/workflows/${enc(id)}/versions/${v}`), api("GET", `/workflows/${enc(id)}/layout`)]);
  state.flow = { id, f, meta: f.latest, version: v, base: reply, shown: { workflow: reply.workflow, api: reply.api }, layout: layout.layout || {},
    ops: [], selected: null, adding: false };
  $("empty").hidden = true; $("flowView").hidden = false;
  $("flowTitle").textContent = reply.workflow.title || id;
  $("flowMeta").textContent = "Chủ luồng: " + f.latest.owner_display + (f.latest.unit ? " · " + f.latest.unit : "") + " · " + VIS[f.latest.visibility]
    + (f.latest.cloned_from ? " · sao từ " + f.latest.cloned_from : "") + " · " + (reply.workflow.engine === "ie" ? "Internet Explorer" : reply.workflow.engine);
  const sel = $("versionSel"); sel.textContent = "";
  for (const row of [...f.versions].reverse()) sel.append(new Option("v" + row.version + " · " + STATUS[row.status], row.version));
  sel.value = String(v);
  drawList(); drawFlow(); showTab(currentTab());
}
$("versionSel").onchange = () => { if (confirmDrop()) openFlow(state.flow.id, Number($("versionSel").value)); else $("versionSel").value = String(state.flow.version); };
function confirmDrop() { return !state.flow || !state.flow.ops.length || window.confirm("Bỏ các thay đổi chưa lưu?"); }

function editable() {
  const fl = state.flow;
  return !!fl && canChange(fl.meta) && fl.version === fl.f.latest.version;
}

// a canvas node: a group of API calls (a flow learned with API nodes) or a step
function nodesOf(workflow, apiNodes) {
  if (apiNodes) {
    const order = [], groups = new Map();
    for (const call of apiNodes) {
      if (!groups.has(call.group)) { groups.set(call.group, []); order.push(call.group); }
      groups.get(call.group).push(call);
    }
    return order.map((g) => {
      const calls = groups.get(g);
      const risk = calls.reduce((r, c) => (RISK_RANK[c.risk] > RISK_RANK[r] ? c.risk : r), "read");
      const mode = calls.reduce((m, c) => { const x = c.mode || (c.risk === "read" ? "auto" : "approve"); return MODE_RANK[x] > MODE_RANK[m] ? x : m; }, "auto");
      return { id: g, title: calls[0].group_label || calls[0].label, sub: calls.length + " lời gọi · " + calls[0].method, risk, mode, calls,
        added: calls.some((c) => c.added), masked: calls.reduce((n, c) => n + (c.masked || 0), 0),
        unresolved: [...new Set(calls.flatMap((c) => c.unresolved || []))], kind: calls[0].kind };
    });
  }
  return workflow.steps.map((s) => ({ id: s.id, title: (s.target && s.target.label) || ACTION[s.action] || s.action,
    sub: (ACTION[s.action] || s.action) + (s.value ? " · " + s.value : "") + (s.save_as ? " → " + s.save_as : ""), risk: s.risk, mode: s.mode, step: s }));
}
function dataEdges(apiNodes) {
  if (!apiNodes) return [];
  const groupOf = new Map(apiNodes.map((c) => [c.id, c.group])), seen = new Set(), edges = [];
  for (const c of apiNodes) for (const rule of Object.values(c.links || {})) {
    const from = groupOf.get(rule.from);
    const key = from + ">" + c.group;
    if (from && from !== c.group && !seen.has(key)) { seen.add(key); edges.push([from, c.group]); }
  }
  return edges;
}
function positionOf(id, index) {
  const p = state.flow.layout[id];
  if (p) return { x: p[0], y: p[1] };
  const wrap = document.querySelector(".canvasWrap");      // as many on a row as fit in the box
  const width = (wrap && wrap.clientWidth) || 800;
  const perRow = Math.max(1, Math.floor((width - 24) / (NODE_W + GAP_X)));
  return { x: 24 + (index % perRow) * (NODE_W + GAP_X), y: TOP + Math.floor(index / perRow) * (NODE_H + GAP_Y) };
}

const SVG = "http://www.w3.org/2000/svg";
function svg(tag, attrs, text) {
  const e = document.createElementNS(SVG, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text !== undefined) e.textContent = text;
  return e;
}
function clip(text, n) { text = String(text || ""); return text.length > n ? text.slice(0, n - 1) + "…" : text; }
const RISK_COLOR = { read: "#2f8f5b", write: "#b7791f", money: "#c0392b" };

function drawFlow() {
  const fl = state.flow, nodes = nodesOf(fl.shown.workflow, fl.shown.api), canvas = $("canvas");
  fl.nodes = nodes;
  canvas.textContent = "";
  const pos = new Map(nodes.map((n, i) => [n.id, positionOf(n.id, i)]));
  let width = 400, height = 300;
  for (const p of pos.values()) { width = Math.max(width, p.x + NODE_W + 30); height = Math.max(height, p.y + NODE_H + 30); }
  canvas.setAttribute("width", width); canvas.setAttribute("height", height);
  const defs = svg("defs"), marker = svg("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
  marker.append(svg("path", { d: "M0,0 L10,5 L0,10 z", fill: "#9aa3b2" })); defs.append(marker); canvas.append(defs);
  const curve = (a, b) => {
    const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2, x2 = b.x, y2 = b.y + NODE_H / 2;
    if (x2 > x1) return `M${x1},${y1} C${x1 + 30},${y1} ${x2 - 30},${y2} ${x2},${y2}`;
    const xa = a.x + NODE_W / 2, ya = a.y + NODE_H, xb = b.x + NODE_W / 2, yb = b.y;
    return `M${xa},${ya} C${xa},${ya + 30} ${xb},${yb - 30} ${xb},${yb}`;
  };
  for (let i = 0; i + 1 < nodes.length; i++) canvas.append(svg("path", { class: "edge", d: curve(pos.get(nodes[i].id), pos.get(nodes[i + 1].id)), "marker-end": "url(#arrow)" }));
  for (const [a, b] of dataEdges(fl.shown.api)) {
    const pa = pos.get(a), pb = pos.get(b);
    if (pa && pb) canvas.append(svg("path", { class: "edge data", d: `M${pa.x + NODE_W / 2},${pa.y} C${pa.x + NODE_W / 2},${pa.y - 40} ${pb.x + NODE_W / 2},${pb.y - 40} ${pb.x + NODE_W / 2},${pb.y}` }));
  }
  nodes.forEach((n, i) => {
    const p = pos.get(n.id);
    const g = svg("g", { class: "node" + (fl.selected === n.id ? " sel" : "") + (n.added ? " added" : ""), transform: `translate(${p.x},${p.y})`, tabindex: 0 });
    g.dataset.id = n.id;
    g.append(svg("rect", { class: "box", width: NODE_W, height: NODE_H, rx: 8 }));
    g.append(svg("rect", { width: 5, height: NODE_H, rx: 2, fill: RISK_COLOR[n.risk] }));
    g.append(svg("text", { x: 14, y: 20 }, (i + 1) + ". " + clip(n.title, 24)));
    g.append(svg("text", { x: 14, y: 38, class: "s" }, clip(n.sub, 30)));
    g.append(svg("text", { x: 14, y: 54, class: "s" }, RISK[n.risk] + (n.mode === "approve" ? " · ⏸ Duyệt" : n.mode === "review" ? " · cho xem" : "")
      + (n.unresolved && n.unresolved.length ? " · ⚠" : "")));
    g.addEventListener("pointerdown", (e) => startDrag(e, n.id, g));
    g.addEventListener("keydown", (e) => { if (e.key === "Enter") select(n.id); });
    canvas.append(g);
  });
  drawToolbar(); drawInspector(); drawInputs();
}

// drag to place a node; a short press is a click (select)
function startDrag(event, id, g) {
  const fl = state.flow, start = { x: event.clientX, y: event.clientY };
  const index = fl.nodes.findIndex((n) => n.id === id), origin = positionOf(id, index);
  let moved = false;
  g.setPointerCapture(event.pointerId);
  const move = (e) => {
    const dx = e.clientX - start.x, dy = e.clientY - start.y;
    if (!moved && Math.abs(dx) + Math.abs(dy) < 4) return;
    moved = true;
    const x = Math.max(0, Math.round((origin.x + dx) / 6) * 6), y = Math.max(0, Math.round((origin.y + dy) / 6) * 6);
    fl.layout[id] = [x, y];
    g.setAttribute("transform", `translate(${x},${y})`);
  };
  const up = async () => {
    g.removeEventListener("pointermove", move); g.removeEventListener("pointerup", up);
    if (!moved) { select(id); return; }
    drawFlow();
    if (canChange(fl.meta)) {
      try { await api("PUT", `/workflows/${enc(fl.id)}/layout`, { layout: fl.layout }); } catch (e) { say("editMsg", e.message, "bad"); }
    }
  };
  g.addEventListener("pointermove", move); g.addEventListener("pointerup", up);
}
function select(id) { state.flow.selected = id; state.flow.adding = false; drawFlow(); }

// ---- edits: kept as a list of operations, previewed by the server, saved as one new draft version ---------------------------

async function addOp(op) {
  const fl = state.flow;
  const ops = fl.ops.concat([op]);
  try {
    const preview = await api("POST", `/workflows/${enc(fl.id)}/versions/${fl.version}/edit/preview`, { ops });
    fl.ops = ops; fl.shown = { workflow: preview.workflow, api: preview.api };
    if (op.op === "delete") fl.selected = null;
    if (op.op === "add_http" && preview.api) { fl.selected = preview.api.find((c) => c.added && !fl.nodes.some((n) => n.id === c.group))?.group || fl.selected; fl.adding = false; }
    say("editMsg", "", "");
    drawFlow();
  } catch (e) { say("editMsg", e.message, "bad"); }
}
function drawToolbar() {
  const fl = state.flow, can = editable();
  $("addHttp").hidden = !can || !fl.shown.api;
  $("save").hidden = $("discard").hidden = !can || !fl.ops.length;
  $("pending").textContent = fl.ops.length ? fl.ops.length + " thay đổi chưa lưu" : "";
  $("readOnly").textContent = can ? "" : (!canChange(fl.meta) ? "Chỉ xem: bạn không phải chủ luồng." : "Đang xem bản cũ: chọn bản mới nhất để sửa.");
}
$("addHttp").onclick = () => { state.flow.adding = true; state.flow.selected = null; drawFlow(); };
$("discard").onclick = () => { const fl = state.flow; fl.ops = []; fl.shown = { workflow: fl.base.workflow, api: fl.base.api }; say("editMsg", ""); drawFlow(); };
$("save").onclick = async () => {
  const fl = state.flow;
  try {
    const saved = await api("POST", `/workflows/${enc(fl.id)}/versions/${fl.version}/edit`, { ops: fl.ops });
    await loadList();
    await openFlow(fl.id, saved.workflow.version);
    say("editMsg", "Đã lưu thành bản nháp v" + saved.workflow.version + ". Cần chạy thử trên bản sao ở máy GDV rồi người khác Duyệt mới dùng được.", "ok");
  } catch (e) { say("editMsg", e.message, "bad"); }
};

function field(label, input) { const wrap = el("div"); const l = el("label", label); wrap.append(l, input); return wrap; }
function input(value, placeholder) { const i = el("input"); i.value = value || ""; if (placeholder) i.placeholder = placeholder; return i; }
function selectOf(options, value, minRank, rank) {
  const s = el("select");
  for (const [k, text] of Object.entries(options)) { const o = new Option(text, k); o.disabled = rank[k] < minRank; s.append(o); }
  s.value = value; return s;
}

function drawInspector() {
  const fl = state.flow, box = $("inspector"), can = editable();
  box.textContent = "";
  if (fl.adding) return drawAddForm(box);
  const n = fl.nodes.find((x) => x.id === fl.selected);
  if (!n) { box.append(el("p", "Bấm vào một nút để xem và sửa. Kéo nút để sắp chỗ.", "sub")); return; }
  box.append(el("h2", n.title));
  const name = input(n.title); name.disabled = !can;
  const rename = el("button", "Đổi tên"); rename.disabled = !can;
  rename.onclick = () => addOp({ op: "label", node: n.id, label: name.value });
  box.append(field("Tên nút", name), rename);
  const risk = selectOf(RISK, n.risk, RISK_RANK[n.risk], RISK_RANK); risk.disabled = !can;
  risk.onchange = () => addOp({ op: "risk", node: n.id, risk: risk.value });
  box.append(field("Mức rủi ro (chỉ nâng lên)", risk));
  const mode = selectOf(MODE, n.mode, MODE_RANK[n.mode], MODE_RANK); mode.disabled = !can;
  mode.onchange = () => addOp({ op: "mode", node: n.id, mode: mode.value });
  box.append(field("Mức kiểm soát (chỉ nâng lên)", mode));
  if (n.mode !== "approve") {
    const gate = el("button", "⏸ Thêm bước Duyệt trước khi làm nút này"); gate.disabled = !can;
    gate.onclick = () => addOp({ op: "mode", node: n.id, mode: "approve" }); box.append(gate);
  }
  const index = fl.nodes.findIndex((x) => x.id === n.id), order = fl.nodes.map((x) => x.id);
  const moves = el("div", undefined, "row");
  const earlier = el("button", "◀ Lên trước"), later = el("button", "Ra sau ▶"), del = el("button", "Xoá nút", "danger");
  earlier.disabled = !can || index === 0; later.disabled = !can || index === order.length - 1; del.disabled = !can;
  const swap = (a, b) => { const o = order.slice(); [o[a], o[b]] = [o[b], o[a]]; addOp({ op: "reorder", order: o }); };
  earlier.onclick = () => swap(index, index - 1); later.onclick = () => swap(index, index + 1);
  del.onclick = () => { if (window.confirm("Xoá nút «" + n.title + "»?")) addOp({ op: "delete", node: n.id }); };
  moves.append(earlier, later, del); box.append(moves);
  if (n.unresolved && n.unresolved.length) box.append(el("div", "⚠ Chưa biết lấy từ đâu: " + n.unresolved.join(", ") + ". Nút này sẽ không chạy được.", "warn"));
  if (n.calls) {
    box.append(el("label", "Các lời gọi"));
    const list = el("ul", undefined, "calls");
    for (const c of n.calls) {
      const li = el("li"); li.append(el("div", c.method + " " + c.url));
      if (c.body) li.append(el("div", "body: " + clip(c.body, 300)));
      if (c.masked) li.append(el("div", "••• là phần chỉ nằm trên máy GDV: không sửa mẫu ở đây được.", "sub"));
      else if (can) {
        const editBtn = el("button", "Sửa mẫu"); editBtn.onclick = () => drawCallForm(box, c); li.append(editBtn);
      }
      list.append(li);
    }
    box.append(list);
  } else if (n.step) {
    box.append(el("div", (ACTION[n.step.action] || n.step.action) + (n.step.value ? " · giá trị: " + n.step.value : ""), "sub"));
  }
}
function drawCallForm(box, call) {
  box.textContent = "";
  box.append(el("h2", "Sửa mẫu lời gọi"));
  const method = selectOf({ GET: "GET", POST: "POST", PUT: "PUT", DELETE: "DELETE" }, call.method, 0, { GET: 0, POST: 0, PUT: 0, DELETE: 0 });
  const url = input(call.url), body = el("textarea"); body.rows = 5; body.value = call.body || "";
  box.append(field("Method", method), field("Địa chỉ", url), field("Body (ô nhập viết ⟦tên⟧)", body));
  const ok = el("button", "Áp dụng", "primary"), back = el("button", "Quay lại");
  ok.onclick = () => addOp({ op: "edit_http", node: call.id, method: method.value, url: url.value, body: body.value });
  back.onclick = () => drawInspector();
  box.append(el("div", undefined, "row")); box.lastChild.append(ok, back);
}
function drawAddForm(box) {
  const fl = state.flow;
  box.append(el("h2", "Thêm nút API"));
  box.append(el("p", "Rủi ro do luật gán theo tên và địa chỉ. Ô nhập viết ⟦tên⟧, không điền số tài khoản, tên khách thật.", "sub"));
  const label = input("", "Ví dụ: Tải sao kê"), method = selectOf({ GET: "GET", POST: "POST" }, "GET", 0, { GET: 0, POST: 0 });
  const url = input("", "http://…/duong-dan?tu=⟦tu_ngay⟧"), body = el("textarea"); body.rows = 4;
  const after = el("select"); after.append(new Option("Đầu luồng", ""));
  for (const n of fl.nodes) after.append(new Option("Sau «" + clip(n.title, 30) + "»", n.id));
  after.value = fl.nodes.length ? fl.nodes[fl.nodes.length - 1].id : "";
  box.append(field("Tên nút", label), field("Method", method), field("Địa chỉ", url), field("Body", body), field("Vị trí", after));
  const ok = el("button", "Thêm", "primary"), cancel = el("button", "Thôi");
  ok.onclick = () => addOp({ op: "add_http", label: label.value, method: method.value, url: url.value, body: body.value, after: after.value || null });
  cancel.onclick = () => { fl.adding = false; drawInspector(); };
  const row = el("div", undefined, "row"); row.append(ok, cancel); box.append(row);
  const names = fl.shown.workflow.inputs.map((i) => "⟦" + i.name + "⟧").join(" ");
  if (names) box.append(el("div", "Ô nhập của luồng: " + names, "sub"));
}
function drawInputs() {
  const fl = state.flow, body = $("inputs"), can = editable();
  body.textContent = "";
  for (const item of fl.shown.workflow.inputs) {
    const tr = el("tr"), label = input(item.label || ""); label.disabled = !can;
    const td = el("td"); td.append(label);
    const btn = el("button", "Đổi nhãn"); btn.disabled = !can;
    btn.onclick = () => addOp({ op: "input_label", name: item.name, label: label.value });
    const tdb = el("td"); tdb.append(btn);
    tr.append(el("td", item.name), td, el("td", item.type), tdb);
    body.append(tr);
  }
  if (!fl.shown.workflow.inputs.length) { const tr = el("tr"); const td = el("td", "Luồng không có ô nhập.", "sub"); td.colSpan = 4; tr.append(td); body.append(tr); }
}

// ---- tabs -------------------------------------------------------------------------------------------------------------------

function currentTab() { const on = document.querySelector(".tabs button.on"); return on ? on.dataset.tab : "canvas"; }
function showTab(name) {
  for (const b of document.querySelectorAll(".tabs button")) b.classList.toggle("on", b.dataset.tab === name);
  for (const p of document.querySelectorAll("[data-panel]")) p.hidden = p.dataset.panel !== name;
  if (name === "versions") drawVersions();
  if (name === "runs") drawRuns();
  if (name === "share") drawShare();
}
for (const b of document.querySelectorAll(".tabs button")) b.onclick = () => showTab(b.dataset.tab);

async function drawVersions() {
  const fl = state.flow, body = $("versions");
  body.textContent = ""; $("diff").textContent = ""; $("diffTitle").hidden = true; say("versionMsg", "");
  for (const row of [...fl.f.versions].reverse()) {
    const tr = el("tr"), who = el("td", "…"), actions = el("td");
    const at = row.created_at ? new Date(row.created_at).toLocaleString("vi-VN") : "";
    tr.append(el("td", "v" + row.version), el("td", STATUS[row.status]), el("td", at), who, actions);
    body.append(tr);
    api("GET", `/workflows/${enc(fl.id)}/versions/${row.version}/edit`).then((r) => {
      who.textContent = r.edit ? r.edit.edited_by + " (sửa từ v" + r.edit.base_version + ")" : "Học từ bản ghi";
      if (row.status === "tested" && canChange(fl.meta)) {
        const self = r.edit && r.edit.edited_by === state.me.name && state.mode !== "off";
        const approve = el("button", "Duyệt bản này", "primary"); approve.disabled = self;
        if (self) approve.title = "Người sửa bản này không tự duyệt được.";
        approve.onclick = async () => {
          try { await api("POST", `/workflows/${enc(fl.id)}/versions/${row.version}/status`, { status: "approved" }); await loadList(); await openFlow(fl.id, row.version); showTab("versions"); }
          catch (e) { say("versionMsg", e.message, "bad"); }
        };
        actions.prepend(approve);
      }
    }).catch(() => { who.textContent = "?"; });
    if (row.status === "draft") actions.append(el("span", "Chờ chạy thử trên bản sao ở máy GDV ", "sub"));
    if (row.version > 1) { const cmp = el("button", "So với v" + (row.version - 1)); cmp.onclick = () => diff(row.version - 1, row.version); actions.append(cmp); }
    if (row.version < fl.f.latest.version && canChange(fl.meta)) {
      const back = el("button", "Quay về bản này");
      back.onclick = async () => {
        try {
          const from = row.version;
          const made = await api("POST", `/workflows/${enc(fl.id)}/versions/${from}/restore`, {});
          await loadList(); await openFlow(fl.id, made.workflow.version); showTab("versions");
          say("versionMsg", "Đã tạo bản " + made.workflow.version + " giống v" + from + ". Bản này chờ Duyệt rồi mới được dùng.", "ok");
        } catch (e) { say("versionMsg", e.message, "bad"); }
      };
      actions.append(back);
    }
  }
}
async function diff(a, b) {
  const fl = state.flow;
  const [x, y] = await Promise.all([api("GET", `/workflows/${enc(fl.id)}/versions/${a}`), api("GET", `/workflows/${enc(fl.id)}/versions/${b}`)]);
  const before = nodesOf(x.workflow, x.api), after = nodesOf(y.workflow, y.api);
  const old = new Map(before.map((n) => [n.id, n])), now = new Map(after.map((n) => [n.id, n]));
  const lines = [];
  for (const n of after) if (!old.has(n.id)) lines.push("Thêm nút «" + n.title + "» (" + RISK[n.risk] + ")");
  for (const n of before) if (!now.has(n.id)) lines.push("Xoá nút «" + n.title + "»");
  for (const n of after) {
    const o = old.get(n.id); if (!o) continue;
    if (o.title !== n.title) lines.push("Đổi tên «" + o.title + "» thành «" + n.title + "»");
    if (o.risk !== n.risk) lines.push("«" + n.title + "»: rủi ro " + RISK[o.risk] + " → " + RISK[n.risk]);
    if (o.mode !== n.mode) lines.push("«" + n.title + "»: kiểm soát " + MODE[o.mode] + " → " + MODE[n.mode]);
    if (o.calls && n.calls && JSON.stringify(o.calls.map((c) => [c.method, c.url, c.body])) !== JSON.stringify(n.calls.map((c) => [c.method, c.url, c.body])))
      lines.push("«" + n.title + "»: đổi mẫu lời gọi");
  }
  const keep = after.map((n) => n.id).filter((id) => old.has(id)), was = before.map((n) => n.id).filter((id) => now.has(id));
  if (JSON.stringify(keep) !== JSON.stringify(was)) lines.push("Đổi thứ tự các nút");
  const inputsBefore = new Map(x.workflow.inputs.map((i) => [i.name, i.label]));
  for (const i of y.workflow.inputs) if (inputsBefore.has(i.name) && inputsBefore.get(i.name) !== i.label) lines.push("Ô nhập " + i.name + ": nhãn «" + (inputsBefore.get(i.name) || "") + "» → «" + (i.label || "") + "»");
  $("diffTitle").hidden = false; $("diffTitle").textContent = "Khác nhau giữa v" + a + " và v" + b;
  const box = $("diff"); box.textContent = "";
  for (const line of lines.length ? lines : ["Không khác gì về các nút (có thể chỉ đổi trạng thái)."]) box.append(el("li", line));
}

function drawSadpt(s) {
  const box = $("sadpt");
  box.textContent = "";
  if (!s) { box.hidden = true; return; }
  box.hidden = false;
  const rate = s.ui_changes ? Math.round(100 * s.ui_recovered / s.ui_changes) + "% (" + s.ui_recovered + "/" + s.ui_changes + ")" : "chưa có";
  const cards = [
    ["Tự phục hồi khi chỉ đổi giao diện", rate, false],
    ["Bước phải ghi lại", String(s.steps_retaught), false],
    ["Dừng đúng ở thay đổi nghiệp vụ", String(s.business_stops) + " lần", false],
    ["Hành động vượt quyền", String(s.overreach), s.overreach > 0],
  ];
  for (const [label, value, bad] of cards) {
    const card = el("div", undefined, bad ? "card bad" : "card");
    card.append(el("div", label, "k"), el("div", value, "n"));
    box.append(card);
  }
}

async function drawRuns() {
  const fl = state.flow, body = $("runs");
  body.textContent = ""; $("runsEmpty").textContent = "";
  try {
    const reply = await api("GET", `/workflows/${enc(fl.id)}/runs`);
    drawSadpt(reply.sadpt);
    const runs = reply.runs;
    for (const r of runs) {
      const approvals = (r.decisions || []).filter((d) => d.approved).length;
      const tr = el("tr");
      tr.append(el("td", r.time), el("td", r.by.display), el("td", r.by.unit), el("td", r.version ? "v" + r.version : ""),
        el("td", { simulate: "Gọi API", screen: "Trên màn hình", twin: "Bản sao (thử)" }[r.mode] || r.mode),
        el("td", RUN_STATUS[r.status] || r.status), el("td", r.seconds), el("td", approvals ? approvals + " lần" : ""));
      body.append(tr);
    }
    if (!runs.length) $("runsEmpty").textContent = "Chưa có lần chạy nào được gửi lên.";
    drawAdapt(runs);
  } catch (e) { drawSadpt(null); $("runsEmpty").textContent = e.message; }
}

const SAW_WORD = { not_found: "không thấy", low_confidence: "chưa chắc", ambiguous: "nhiều ô giống nhau", unexpected: "chưa từng thấy", missing: "chưa hiện", contract_changed: "đổi dạng trả lời" };
const CHANGE_WORD = { technical: "kỹ thuật", business: "nghiệp vụ", unknown: "chưa rõ" };
const ACTION_WORD = { reresolve: "tự tìm lại", ask: "hỏi" };
const OUTCOME_WORD = { done: "xong", postcheck_failed: "hậu kiểm không đạt", stopped: "đã dừng", asked: "đã hỏi" };

function drawAdapt(runs) {
  const body = $("adaptLog");
  body.textContent = ""; $("adaptEmpty").textContent = "";
  const rows = [];
  for (const r of runs) for (const a of r.adaptations || []) rows.push({ time: r.time, row: a });
  if (!rows.length) { $("adaptEmpty").textContent = "Chưa có quyết định thích nghi nào."; return; }
  for (const item of rows) {
    const a = item.row, tr = el("tr");
    tr.append(el("td", item.time), el("td", a.step_id), el("td", SAW_WORD[a.saw] || a.saw), el("td", CHANGE_WORD[a.change] || a.change),
      el("td", ACTION_WORD[a.action] || a.action), el("td", OUTCOME_WORD[a.outcome] || a.outcome));
    body.append(tr);
  }
}

async function drawShare() {
  const fl = state.flow, owner = isOwner(fl.meta);
  say("shareMsg", ""); say("cloneMsg", ""); say("ownerMsg", "");
  const list = $("sharePreview"); list.textContent = "";
  try {
    const p = await api("GET", `/workflows/${enc(fl.id)}/share-preview`);
    for (const s of p.steps) list.append(el("li", s.label + " · " + RISK[s.risk] + " · " + MODE[s.mode]));
    $("shareInputs").textContent = p.inputs.length ? "Ô nhập: " + p.inputs.map((i) => i.label + " (" + i.name + ")").join(", ") : "Không có ô nhập.";
    for (const r of document.querySelectorAll("input[name=vis]")) r.checked = r.value === p.visibility;
  } catch (e) { say("shareMsg", e.message, "bad"); }
  $("shareBox").hidden = !owner;
  $("shareNote").textContent = owner ? "" : "Chỉ chủ luồng (" + fl.meta.owner_display + ") mới chia sẻ được luồng này.";
  $("shareConfirm").checked = false;
  $("ownerBox").hidden = !isAdmin();
}
$("shareBtn").onclick = async () => {
  const fl = state.flow, chosen = document.querySelector("input[name=vis]:checked");
  if (!chosen) return say("shareMsg", "Chọn ai được thấy.", "bad");
  try {
    await api("POST", `/workflows/${enc(fl.id)}/share`, { visibility: chosen.value, confirm: $("shareConfirm").checked });
    await loadList(); say("shareMsg", "Đã lưu: " + VIS[chosen.value] + ".", "ok");
  } catch (e) { say("shareMsg", e.message, "bad"); }
};
$("cloneBtn").onclick = async () => {
  const fl = state.flow;
  try {
    const title = $("cloneTitle").value.trim();
    const made = await api("POST", `/workflows/${enc(fl.id)}/clone`, title ? { title } : {});
    await loadList(); await openFlow(made.workflow.id);
    say("editMsg", "Đã sao chép thành luồng của bạn (bản nháp).", "ok"); showTab("canvas");
  } catch (e) { say("cloneMsg", e.message, "bad"); }
};
$("ownerBtn").onclick = async () => {
  const fl = state.flow;
  try {
    await api("POST", `/workflows/${enc(fl.id)}/owner`, { owner: $("ownerName").value.trim(), owner_display: $("ownerDisplay").value.trim(), unit: $("ownerUnit").value.trim() });
    await loadList(); await openFlow(fl.id, fl.version); showTab("share"); say("ownerMsg", "Đã gán chủ luồng.", "ok");
  } catch (e) { say("ownerMsg", e.message, "bad"); }
};

let resizing = null;
window.addEventListener("resize", () => { clearTimeout(resizing); resizing = setTimeout(() => { if (state.flow && currentTab() === "canvas") drawFlow(); }, 200); });
window.addEventListener("beforeunload", (e) => { if (state.flow && state.flow.ops.length) { e.preventDefault(); e.returnValue = ""; } });
start();
