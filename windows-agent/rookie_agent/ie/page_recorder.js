/* Rookie Agent: recorder placed into a page of Internet Explorer (and into each of its frames).
 *
 * Old JavaScript only (ES3): the pages are in quirks mode, where there is no JSON, no addEventListener,
 * no trim, no forEach. Keep this file ASCII.
 *
 * It listens to what the teller does and appends one line of JSON per action to window.__rkq. The agent
 * takes the lines with window.__rkTake() every fraction of a second. It listens only while window.__rkRec
 * is true (set by the agent on Ghi, cleared on Dung ghi).
 *
 * Passwords: an input of type password or hidden, or whose name/id looks like a password, OTP or PIN, produces
 * no line at all and its value is never read.
 */
(function () {
  try {
  // In run mode (the agent drives the page) nothing is recorded: the recorder's own functions are only the helpers of the runner.
  if (window.__rkOn) { window.__rkBusy = new Date().getTime(); window.__rkRec = !window.__rkRunMode; if (window.__rkEnsureErr) { window.__rkEnsureErr(); } if (window.__rkAttach && !window.__rkRunMode) { window.__rkAttach(); } window.__rkBusy = 0; return; }
  window.__rkBusy = new Date().getTime();   // while our own code runs, an error of it is ours: it is not handed to the page's own error handler
  window.__rkOn = true;
  window.__rkRec = !window.__rkRunMode;
  window.__rkq = "";
  var doc = document;
  // Everything the agent calls from outside runs inside this: whatever goes wrong is caught here and kept as __rkErr, and never reaches the page.
  function external(name, fn) {
    return function () {
      var r = "";
      window.__rkBusy = new Date().getTime();
      try { r = fn.apply(null, arguments); } catch (eX) { window.__rkErr = name + ": " + (eX && eX.message ? eX.message : eX); r = ""; }
      window.__rkBusy = 0;
      return r;
    };
  }
  // The agent's look, every fraction of a second. It is the ONLY thing the agent runs in a page once the recorder is in, and it reads
  // nothing of the page's elements: a call from outside can arrive while the page's own script is paused (a dialog, a request that
  // waits), and reading a field then is reading it in the middle of the page's work. The events still waiting are read by our own
  // timer, which runs only when the page's script has finished. Here: lines left by an old page, our error handler kept in front of
  // the page's, a listener a frame refused tried again, the lines handed over.
  window.__rkTake = external("take", function () {
    var s;
    restoreLines();
    try { if (window.__rkEnsureErr) { window.__rkEnsureErr(); } } catch (eE) {}
    try { if (window.__rkAttach) { window.__rkAttach(); } } catch (eA) {}
    try { if (pending.length && !drainTimer) { drainTimer = window.setTimeout(drain, 0); } } catch (eT) {}
    s = window.__rkq;
    window.__rkq = "";
    if (s) { try { if (String(doc.cookie || "").indexOf(KEEP) >= 0) { doc.cookie = KEEP + "; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT"; } } catch (e) {} }
    return s;
  });

  // A press that sends the page away (Dang nhap, Luu) unloads it before the agent's next look, and the line with it.
  // So lines not yet taken are kept in a session cookie when the page unloads, and the next page of the same tab
  // takes them back. The cookie holds only what the queue holds (never a password: those make no line).
  // Only on unload, when the page really goes: IE also fires beforeunload for a link href="javascript:..." (GWT pages are full of
  // them) and the page stays; a cookie written then went to the bank's server with the page's next request. Small (whole lines,
  // at most KEEP_MAX characters once encoded), so it never crowds the page's own cookies.
  var KEEP = "__rkkeep=", KEEP_MAX = 2000, FORM_MAX = 16000;
  // Gate 8: a form the teller sent (Enter or its submit button) is a request too, and not an XHR one: when the page leaves because of
  // it, its action, method and fields make one "form" line. A password field is never read: it stands as *** and the request is then
  // known as one that cannot be sent again. The next document of the frame says where the browser went ("nav", at its start).
  var leavingForm = null, leavingAt = 0;
  function formLine() {
    var f = leavingForm, parts = [], i, x, g, ty, n, v;
    if (!f || new Date().getTime() - leavingAt > 10000) { return ""; }
    leavingForm = null;
    try {
      for (i = 0; i < f.elements.length; i++) {
        x = f.elements[i]; g = tag(x);
        if (!TYPED[g] || g === "BUTTON") { continue; }
        n = get(x, "name"); if (!n) { continue; }
        try { if (x.disabled) { continue; } } catch (eD) {}
        ty = typeOf(x);
        if (ty === "submit" || ty === "image" || ty === "button" || ty === "reset" || ty === "file") { continue; }
        if ((ty === "checkbox" || ty === "radio") && !x.checked) { continue; }
        // a hidden field is what the browser sends anyway (a customer number, a page token), not something the teller typed
        v = (ty === "password" || (ty !== "hidden" && isSecret(x))) ? "***" : (g === "SELECT" ? String(optValue(x) === null ? "" : optValue(x)) : String(x.value));
        parts.push(encodeURIComponent(n) + "=" + encodeURIComponent(v));
      }
      v = parts.join("&");
      try { window.top.__rkFormAt = new Date().getTime(); } catch (eTop) {}    // for formGo: the page that leaves may be another frame than this one
      return "{" + '"uid":"f' + new Date().getTime() + "-" + Math.floor(Math.random() * 1000000000) + '","t":' + new Date().getTime() + ',"kind":"form","frame":' + str(ownPath()) + ',"method":' + str(String(f.method || "GET").toUpperCase()) +
        ',"url":' + str(String(f.action || doc.location.href)) + ',"target":' + str(String(f.target || "")) + ',"req":' + str(v.slice(0, FORM_MAX)) + (v.length > FORM_MAX ? ',"cut":true' : "") + "}\n";
    } catch (eF) { return ""; }
  }
  // The page starts to leave a moment after a form was sent: a sign that the form really went (a page's own script may stop it), also when
  // the answer is a download and no new document comes. Only a line in memory; nothing is written to the page.
  // the moment of the press, taken at once: the page starts to leave (beforeunload) before our timer makes the form line
  function markForm() { try { window.top.__rkFormAt = new Date().getTime(); } catch (eMf) {} }
  function formGo() {
    var at = 0;
    try { at = window.top.__rkFormAt || 0; } catch (eAt) {}
    try {
      if (window.__rkRec && at && new Date().getTime() - at < 3000) {
        window.top.__rkFormAt = 0;
        window.__rkq += "{" + '"uid":"g' + new Date().getTime() + "-" + Math.floor(Math.random() * 1000000000) + '","t":' + new Date().getTime() + ',"kind":"formgo","frame":' + str(ownPath()) + "}\n";
      }
    } catch (eGo) {}
  }
  try { if (!window.__rkOnly) { if (window.attachEvent) { window.attachEvent("onbeforeunload", formGo); } else if (window.addEventListener) { window.addEventListener("beforeunload", formGo, false); } } } catch (eBu) {}
  function keepLines() {
    var s, enc, cut, sent = "";
    try { if (window.__rkDrain) { window.__rkDrain(); } } catch (eD) {}    // events still waiting to be read are lines too
    try { flushDirty(); } catch (eDirty) {}
    flushFocused();   // a value chosen or typed in the field that has the focus, when the page is leaving, is a line too
    try { if (window.__rkRec) { sent = formLine(); } } catch (eFl) {}
    s = String(window.__rkq).replace(/[^\n]*"kind":"ajax"[^\n]*\n/g, "");
    if (!s && !sent) { return; }
    enc = encodeURIComponent(s);
    while (s && enc.length > KEEP_MAX) {                                   // the newest whole lines only
      cut = s.indexOf("\n");
      if (cut < 0 || cut >= s.length - 1) { s = ""; break; }
      s = s.slice(cut + 1);
      enc = encodeURIComponent(s);
    }
    s += sent;                                                             // the form sent is kept whole (it is not counted in the limit)
    // Never in a cookie: a cookie goes to the bank's server with every request of the next screen (on TouchPoint the server then
    // answered with an error and the page showed "Failed"). The lines wait on the top window, which a frame's change leaves in place;
    // when the whole tab changes page they are lost, and the agent's last poll has taken nearly all of them anyway.
    try {
      if (window.top && window.top != window) { window.top.__rkCarry = String(window.top.__rkCarry || "") + s; }
      else if (String(window.name).indexOf(NAME_MARK) !== 0) { window.name = NAME_MARK + String(window.name).length + ":" + window.name + s; }   // the whole tab leaves: the window's name stays in the browser, its old value is put back at once on the next page
    } catch (e) {}
  }
  var NAME_MARK = "__rkcarry:";
  function restoreLines() {
    var m, i, parts, c, rows, fresh, now, j, when;
    try {
      m = window.top && window.top.__rkCarry;
      if (m) { window.top.__rkCarry = ""; }
      c = String(window.top.name);
      if (c.indexOf(NAME_MARK) === 0) {
        i = c.indexOf(":", NAME_MARK.length); j = parseInt(c.slice(NAME_MARK.length, i), 10);
        window.top.name = c.substr(i + 1, j);
        m = String(m || "") + c.slice(i + 1 + j);
      }
      if (m) {
        rows = String(m).split("\n"); fresh = ""; now = new Date().getTime();
        for (j = 0; j < rows.length; j++) {
          when = /"t":(\d+)/.exec(rows[j]);
          if (when && now - parseInt(when[1], 10) <= 30000) { fresh += rows[j] + "\n"; }
        }
        if (fresh) { window.__rkq = fresh + window.__rkq; }
      }
    } catch (eTop) {}
    try {   // an old build's cookie still on this PC: removed, never read

      parts = String(doc.cookie || "").split(";");
      for (i = 0; i < parts.length; i++) {
        c = parts[i].replace(/^\s+/, "");
        if (c.indexOf(KEEP) === 0) {
          doc.cookie = KEEP + "; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
          return;
        }
      }
    } catch (e) {}
  }
  restoreLines();
  // Gate 8: where this document came from, once, when the recorder first enters it (the agent keeps only those that come after a press)
  try {
    if (window.__rkRec) {
      window.__rkq += "{" + '"uid":"n' + new Date().getTime() + "-" + Math.floor(Math.random() * 1000000000) + '","t":' + new Date().getTime() + ',"kind":"nav","frame":' + str(framePath(window)) + ',"url":' + str(String(doc.location.href)) +
        ',"title":' + str(String(doc.title || "")) + "}\n";
    }
  } catch (eNav) {}
  window.__rkKeep = keepLines;
  window.__rkRestore = restoreLines;
  // Each attach on its own, inside try: a window that is being unloaded or rebuilt can refuse one ("Failed"), and that must never stop the rest.
  try { if (window.__rkOnly && ("," + window.__rkOnly + ",").indexOf(",unload,") < 0) { /* left out on purpose */ } else if (window.attachEvent) { window.attachEvent("onunload", keepLines); } else if (window.addEventListener) { window.addEventListener("unload", keepLines, false); } } catch (eU2) { window.__rkErr = "attach unload: " + (eU2 && eU2.message ? eU2.message : eU2); }
  var SECRET = /pass|pwd|otp|pin(?![a-z])|secret|mat.?khau/i;

  function esc(value) {
    var s = String(value === null || value === undefined ? "" : value), out = "", i, c, h;
    for (i = 0; i < s.length; i++) {
      c = s.charCodeAt(i);
      if (c === 34) { out += '\\"'; }
      else if (c === 92) { out += "\\\\"; }
      else if (c < 32 || c > 126) { h = c.toString(16); out += "\\u" + "0000".slice(h.length) + h; }
      else { out += s.charAt(i); }
    }
    return out;
  }
  function str(value) { return value === null || value === undefined ? "null" : '"' + esc(value) + '"'; }
  function clean(text) {
    var s = String(text || "").replace(/[\r\n\t ]+/g, " ").replace(/\s+/g, " ").replace(/^\s+|\s+$/g, "");
    s = s.replace(/[:*\s]+$/, "");
    return s.length > 60 ? s.slice(0, 60) : s;
  }
  // Reading a property of an element the page has just removed or rebuilt can throw a COM error ("Failed"): such a read is "no value".
  function get(el, name) { try { return el[name]; } catch (eGet) { return undefined; } }
  // What the recorder remembers about an element (the value before, whether a key was pressed, the last list seen, a table of data) is kept
  // in a list of its own: nothing is written onto the page's own elements and nothing is read from them to tell them apart (no uniqueID,
  // which IE has to assign on the first read). An element is found again by comparing the references.
  var STATE = [], STATE_MAX = 400;
  function sfind(el) {
    var i;
    for (i = STATE.length - 1; i >= 0; i--) { try { if (STATE[i].el == el) { return STATE[i]; } } catch (eF) {} }
    return null;
  }
  function sget(el, key) { var f = sfind(el); return f ? f[key] : undefined; }
  function sset(el, key, value) {
    var f = sfind(el);
    if (!f) { f = { el: el }; STATE.push(f); if (STATE.length > STATE_MAX) { STATE.shift(); } }
    f[key] = value;
  }
  function tag(el) { var g = ""; try { g = el && el.tagName ? String(el.tagName).toUpperCase() : ""; } catch (eTag) {} return g; }
  // `type` is read only where it is the kind of a control. On other elements it is not harmless: on TouchPoint's tabs, VML shapes
  // (v:roundrect), it names the shape's type, and reading it while the page was building its tabs ended in "Failed" in vmlTabs.js.
  var TYPED = { INPUT: 1, BUTTON: 1, SELECT: 1, TEXTAREA: 1 };
  function typeOf(el) { var t = ""; if (!TYPED[tag(el)]) { return ""; } try { t = String(el.type || "").toLowerCase(); } catch (e) {} return t; }

  function framePath(w) {
    var parts = [], guard = 0, p, name, i, n;
    while (guard++ < 10) {
      try { p = w.parent; } catch (e) { break; }
      if (!p || p == w) { break; }    // == : in document mode 5 two references to the same window are not === 
      name = "";
      try { name = w.name; } catch (e2) {}
      if (!name) {
        try { n = p.frames.length; for (i = 0; i < n; i++) { if (p.frames[i] == w) { name = "#" + i; break; } } } catch (e3) {}
      }
      parts.unshift(name || "#?");
      w = p;
    }
    return parts.length ? parts.join("/") : "top";
  }
  // "frame=*|..." is asked by the runner when the frame of the recording is not there any more (its name or place changed): every frame
  // answers for itself and the agent acts only when exactly one element in one frame matches.
  function sameFrame(wanted, own) { return wanted === own || wanted === "*"; }
  // Where this document sits does not change while it lives: found once (fewer reads of the other frames), unless a frame was unreadable.
  var ownPathKnown = null;
  function ownPath() {
    var p;
    if (ownPathKnown !== null) { return ownPathKnown; }
    p = framePath(window);
    if (p.indexOf("#?") < 0) { ownPathKnown = p; }
    return p;
  }

  function isSecret(el) {
    var t = typeOf(el);
    return t === "password" || t === "hidden" || t === "file" || SECRET.test(String(get(el, "name") || "")) || SECRET.test(String(get(el, "id") || ""));
  }

  function labelOf(el) {
    var t = "", id = get(el, "id"), ls, i, cell, prev;
    try {
      if (id) {
        ls = doc.getElementsByTagName("label");
        for (i = 0; i < ls.length; i++) { if (ls[i].htmlFor === id) { t = ls[i].innerText; break; } }
      }
      if (!t) {
        cell = el.parentNode;
        while (cell && tag(cell) !== "TD" && tag(cell) !== "TH") { cell = cell.parentNode; }
        if (cell) {
          prev = cell.previousSibling;
          while (prev && prev.nodeType !== 1) { prev = prev.previousSibling; }
          if (prev) { t = prev.innerText; }
        }
      }
    } catch (e) {}
    if (!clean(t)) { t = get(el, "title") || get(el, "alt") || get(el, "name") || get(el, "id") || ""; }
    return clean(t);
  }

  // A row of a list of data (accounts, customers) is named by its position, never by its text: the text is the
  // customer's. Buttons, links and the tabs of a strip keep their text, which is the name of the screen's own controls.
  function dataRowLabel(el) {
    var row = el, table, depth = 0, text, g = tag(el);
    if (g === "BUTTON" || g === "A" || g === "INPUT") { return ""; }
    while (row && depth++ < 8 && tag(row) !== "TR") { row = row.parentNode; }
    if (!row || tag(row) !== "TR") { return ""; }
    table = row.parentNode;
    while (table && tag(table) !== "TABLE") { table = table.parentNode; }
    if (!table || table.rows.length < 3 || row.cells.length < 2) { return ""; }
    try { text = String(row.innerText || ""); } catch (e) { text = ""; }
    if (row.cells.length < 3 && !/\d{3}/.test(text)) { return ""; }
    return "dòng " + (row.rowIndex + 1);
  }

  function actionLabel(el) {
    var t = "", row = dataRowLabel(el);
    if (row) { return row; }
    try {
      var g = tag(el);
      if (g === "INPUT") { t = el.value || el.title || el.alt || el.id; }
      else if (g === "TR") {            // a row of a list: its cells, separated (innerText may run them together)
        var cells = el.cells, k, parts = [];
        for (k = 0; k < cells.length && k < 8; k++) { parts.push(cells[k].innerText); }
        t = parts.join(" ");
      }
      else {
        t = el.innerText || "";
        // A big area (a whole block of the form) is not named by the text inside it: that is a jumble of the labels of its fields.
        if (String(t).length > 40 && el.getElementsByTagName("*").length > 6) { t = ""; }
        t = t || el.title || el.alt || el.id || el.name;
      }
    } catch (e) {}
    return clean(t);
  }

  function position(el) {
    var all, i;
    try {
      all = doc.getElementsByTagName(tag(el));
      for (i = 0; i < all.length; i++) { if (all[i] == el) { return i; } }
    } catch (e) {}
    return -1;
  }

  var uidCount = 0;
  function emit(kind, el, value, label, extra) {
    uidCount++;
    var line = "{" +
      '"uid":"' + new Date().getTime() + "-" + Math.floor(Math.random() * 1000000000) + "-" + uidCount + '"' +
      ',"t":' + new Date().getTime() +
      ',"kind":"' + kind + '"' +
      ',"frame":' + str(ownPath()) +
      ',"title":' + str(clean(doc.title)) +
      ',"tag":' + str(tag(el).toLowerCase()) +
      ',"type":' + str(typeOf(el)) +
      ',"id":' + str(get(el, "id")) +
      ',"name":' + str(get(el, "name")) +
      ',"label":' + str(label) +
      ',"pos":' + position(el) +
      ',"value":' + str(value) +
      (extra || "") +
      "}\n";
    window.__rkq += line;
  }

  function valueOf(el) {
    try {
      if (tag(el) === "SELECT") {
        return el.selectedIndex >= 0 ? el.options[el.selectedIndex].text : "";
      }
      return TYPED[tag(el)] ? el.value : "";   // value is the field's own only on controls; never read on a shape or a block
    } catch (e) { return ""; }
  }

  // A choice list: the value of the option chosen (the same in every language of the screen) and the options themselves.
  function optValue(el) {
    try { if (tag(el) === "SELECT" && el.selectedIndex >= 0) { return el.options[el.selectedIndex].value; } } catch (e) {}
    return null;
  }
  function optionsJson(el) {
    var out = [], i, n = 0;
    try { n = el.options.length; if (n > 50) { n = 50; } } catch (e) {}
    for (i = 0; i < n; i++) {
      try { out.push('{"v":' + str(el.options[i].value) + ',"t":' + str(clean(el.options[i].text)) + "}"); } catch (e2) {}
    }
    return "[" + out.join(",") + "]";
  }
  // What a list shows when the page is ready, also for a list the teller never touches (the page's own default). A page script
  // may set the default after onload, so it is taken again a moment later; a list that has not changed since is not repeated.
  function snapshot() {
    var sels, i, el, sig;
    if (!window.__rkRec) { return; }
    try { sels = doc.getElementsByTagName("select"); } catch (e) { return; }
    for (i = 0; i < sels.length; i++) {
      el = sels[i];
      if (isSecret(el)) { continue; }
      sig = String(optValue(el)) + "|" + optionsJson(el);
      if (sget(el, "snap") === sig) { continue; }
      sset(el, "snap", sig);
      emit("snap", el, valueOf(el), labelOf(el), ',"ctl":true,"optv":' + str(optValue(el)) + ',"opts":' + optionsJson(el));
    }
  }
  function snapshotLater() { try { snapshot(); } catch (e) {} }

  // ---- The requests the page makes (task 4.35). XMLHttpRequest and ActiveXObject("Microsoft.XMLHTTP") are replaced by a thin
  // stand-in that talks to the real object and reports method, address, status, time, what was sent and what came back. In document
  // mode 5 (TouchPoint) an ActiveX object accepts no extra property, so the stand-in is a plain object with the same interface.
  // The lines it makes stay in the agent's memory: they are never put in the cookie that carries lines across a page change.
  // The first thing that goes wrong inside OUR part of a request (never the page's own error) is reported with its stage and message, and
  // the page gets its own objects back: from then on this page is left alone. The stand-ins still alive only forward.
  var Native0 = window.XMLHttpRequest, Active0 = window.ActiveXObject;
  function ajaxFailed(stage, e) {
    var text = "";
    try { text = String(e && e.message ? e.message : e).slice(0, 200); } catch (e6) {}
    if (window.__rkAjaxOff) { return; }
    window.__rkAjaxOff = true;
    try { window.XMLHttpRequest = Native0; } catch (e7) {}
    try { window.ActiveXObject = Active0; } catch (e8) {}
    window.__rkAjax = "off:" + stage;
    toConsole("request recorder stepped back (" + stage + "): " + text);
    try {
      uidCount++;
      window.__rkq += "{" + '"uid":"' + new Date().getTime() + "-" + Math.floor(Math.random() * 1000000000) + "-" + uidCount + '"' +
        ',"t":' + new Date().getTime() + ',"kind":"ajaxerr","frame":' + str(ownPath()) + ',"host":' + str(String(window.location.hostname)) + ',"stage":' + str(stage) + ',"error":' + str(text) + "}\n";
    } catch (e9) {}
  }
  var AJAX_REQ = 16000, AJAX_RES = 100000, AJAX_QUEUE_MAX = 2000000;   // a whole answer: a later request may take a value from it (Gate 8)
  // An answer that is a file (a report as PDF, a statement as Excel; docs/design.md 6.4) is told by its headers only: an attachment, or a
  // content type that is a document or a picture. Its bytes and its text are never read here: only its type, its size and a pattern of its
  // name (digits and words masked) are reported. The agent fetches the bytes itself over COM when a flow is run.
  var FILE_TYPE = /^(application\/(pdf|x-pdf|octet-stream|zip|x-zip-compressed|msword|rtf|excel|x-excel|x-msexcel|force-download|download|x-download|vnd\..+)|binary\/octet-stream|text\/csv|image\/.+)$/;
  function header(x, name) { var v = ""; try { v = x.getResponseHeader(name); } catch (eHd) {} return v === null || v === undefined ? "" : String(v); }
  function isFileHeaders(ct, cd) {
    var kind = String(ct).split(";")[0].replace(/^\s+|\s+$/g, "").toLowerCase();
    if (/attachment/i.test(String(cd))) { return true; }
    return FILE_TYPE.test(kind) && !/\+(json|xml)$/.test(kind);
  }
  function namePattern(cd) {
    var m = /filename\*?\s*=\s*(?:[\w\-]*'[^']*')?"?([^";]*)/i.exec(String(cd)), f, dot, ext, base;
    if (!m) { return ""; }
    f = m[1]; dot = f.lastIndexOf(".");
    ext = dot >= 0 ? f.slice(dot + 1) : ""; base = dot >= 0 ? f.slice(0, dot) : f;
    base = base.replace(/\d+/g, "#").replace(/[^#_\-. ]+/g, "A");
    return (base + (/^[A-Za-z0-9]{1,5}$/.test(ext) ? "." + ext.toLowerCase() : "")).slice(0, 80);
  }
  function fileFacts(x) {
    var ct, cd, size = 0, st = 0;
    try { st = x.status; } catch (eSt) {}
    if (st >= 400) { return null; }
    ct = header(x, "Content-Type"); cd = header(x, "Content-Disposition");
    if (!isFileHeaders(ct, cd)) { return null; }
    try { size = new VBArray(x.responseBody).ubound(1) + 1; } catch (eSz) {}
    if (!size) { size = parseInt(header(x, "Content-Length"), 10) || 0; }
    return { ctype: String(ct).split(";")[0].replace(/^\s+|\s+$/g, "").toLowerCase().slice(0, 80), size: size, name: namePattern(cd) };
  }
  var SECRET_HEADER = /cookie|pass|secret/i;   // an Authorization or token header stays in memory like a token in a body (6.4): its value is never written, only where it comes from
  function emitAjax(rec) {
    if (window.__rkAjaxOff || !window.__rkRec || String(window.__rkq).length > AJAX_QUEUE_MAX) { return; }
    var line;
    uidCount++;
    line = "{" +
      '"uid":"' + new Date().getTime() + "-" + Math.floor(Math.random() * 1000000000) + "-" + uidCount + '"' +
      ',"t":' + rec.t0 + ',"kind":"ajax","frame":' + str(ownPath()) + ',"title":' + str(clean(doc.title)) +
      ',"method":' + str(rec.method) + ',"url":' + str(rec.url) + ',"status":' + (rec.status > 0 ? rec.status : 0) +
      ',"ms":' + rec.ms + ',"async":' + (rec.async ? "true" : "false") +
      ',"req":' + str(rec.req) + ',"res":' + str(rec.file ? "" : rec.res) + ',"hdr":' + str(rec.hdr || "") + (rec.cut ? ',"cut":true' : "") +
      (rec.file ? ',"file":{"ctype":' + str(rec.file.ctype) + ',"size":' + (Number(rec.file.size) || 0) + ',"name":' + str(rec.file.name) + "}" : "") + "}\n";
    // The press that sent the request may still wait in the queue (a local answer can come before our timer): the line waits behind it.
    if (pending.length) { pending.push({ name: "ajax", line: line, teller: true }); return; }
    window.__rkq += line;
  }
  // A password, PIN or OTP that travels in a request body is never kept, not even in memory: its value is replaced before the line is made.
  // A token (session, anti-forgery) is not the teller's secret: it stays in memory so the agent can find which earlier answer gave it
  // (Gate 8); what is written to disk is only where it comes from, or *** when that is not known.
  var SECRET_KEY = /((?:pass(?:word|wd|code)?|pwd|otp|pin|matkhau)[a-z_]*["']?\s*[:=]\s*)("(?:[^"\\]|\\.)*"|'[^']*'|[^&,}\s]*)/gi;
  function hideSecrets(text) {
    try { return String(text).replace(SECRET_KEY, '$1"***"'); } catch (e) { return ""; }
  }
  // The last bodies the page sent, per path, in the page's memory only (never written, never sent): a run that does not sign in takes from
  // them the session value the page is using now (Gate 8). Passwords are already hidden. Remembered whether or not the teller records.
  var LAST_PATHS = 30, LAST_BODIES = 3;
  function pathOf(url) {
    var u = String(url), at = u.search(/[?#]/), dir;
    if (at >= 0) { u = u.slice(0, at); }
    u = u.replace(/^[A-Za-z][A-Za-z0-9+.\-]*:\/\/[^\/]*/, "");
    if (u.charAt(0) !== "/") { dir = String(window.location.pathname); u = dir.slice(0, dir.lastIndexOf("/") + 1) + u; }
    return u;
  }
  function rememberReq(rec) {
    var map, key, list, n = 0, k;
    if (!rec.req) { return; }
    map = window.__rkLastReq;
    if (!map) { map = window.__rkLastReq = {}; window.__rkLastReqN = 0; }
    key = pathOf(rec.url);
    list = map[key];
    if (!list) {
      if (window.__rkLastReqN >= LAST_PATHS) { return; }
      window.__rkLastReqN++; list = map[key] = [];
    }
    list.push(rec.req);
    if (list.length > LAST_BODIES) { list.shift(); }
  }
  function lastReq(value) {
    var map = window.__rkLastReq, list, out = [], i;
    if (!map) { return ""; }
    list = map[String(value)];
    if (!list) { return ""; }
    for (i = 0; i < list.length; i++) { out.push(str(list[i])); }
    return '{"frame":' + str(framePath(window)) + ',"bodies":[' + out.join(",") + "]}";
  }
  function makeStandIn(real) {
    var p = { readyState: 0, status: 0, statusText: "", responseText: "", responseXML: null, onreadystatechange: null, onload: null, onerror: null, ontimeout: null, onabort: null, timeout: 0, withCredentials: false, response: "", responseType: "" }, rec = { async: true, done: false };
    function copy() {
      try { p.readyState = real.readyState; } catch (e1) {}
      try { p.status = real.status; p.statusText = real.statusText; } catch (e2) {}
      if (p.readyState === 4) {
        try {
          rec.file = fileFacts(real);   // a file answer: its text is not read; a page that wants the bytes gets responseBody
          if (rec.file) { p.responseText = ""; p.response = ""; try { p.responseBody = real.responseBody; p.ResponseBody = p.responseBody; } catch (eB) {} }
          else { p.responseText = real.responseText; p.response = p.responseText; }
        } catch (e3) {}
      }
      grabXml();
    }
    // MSXML's responseXML is always an object (with parseError), at every state, even before the answer: a page may read it early.
    function grabXml() {
      try { var x = real.responseXML; if (x !== undefined) { p.responseXML = x; } } catch (e4) {}
      mirror();
    }
    // An ActiveX object does not care about upper or lower case (inXMLHTTP.ResponseText, .Status); a plain object does. Both spellings are kept equal.
    function mirror() {
      p.ReadyState = p.readyState; p.Status = p.status; p.StatusText = p.statusText;
      p.ResponseText = p.responseText; p.ResponseXML = p.responseXML;
    }
    function finish() {
      if (rec.done) { return; }
      rec.done = true;
      try {
        if (window.__rkTestFail) { throw new Error("forced by the test"); }
        rec.status = p.status;
        rec.ms = new Date().getTime() - rec.t0;
        rec.res = typeof p.responseText === "string" && !rec.file ? p.responseText.slice(0, AJAX_RES) : "";
        rememberReq(rec);
        emitAjax(rec);
      } catch (e5) { ajaxFailed("finish", e5); }
    }
    window.__rkAxT = new Date().getTime();
    p.open = function (method, url, isAsync, user, password) {
      window.__rkAxT = new Date().getTime();
      rec = { async: isAsync !== false, done: false, method: String(method), url: String(url), t0: new Date().getTime(), req: "", res: "", status: 0, ms: 0 };
      p.readyState = 0; p.status = 0; p.statusText = ""; p.responseText = ""; p.responseXML = null; p.response = "";   // a reused object starts clean, as the real one does
      mirror();
      if (arguments.length >= 5) { real.open(method, url, isAsync, user, password); }
      else if (arguments.length === 4) { real.open(method, url, isAsync, user); }
      else if (arguments.length === 3) { real.open(method, url, isAsync); }
      else { real.open(method, url); }
      grabXml();
    };
    p.setRequestHeader = function (name, value) {
      real.setRequestHeader(name, value);
      // Gate 7: the headers the page set (GWT needs its own to answer); one that carries a secret is never kept, not even its name's value
      try { if (!SECRET_HEADER.test(String(name))) { rec.hdr = (rec.hdr || "") + String(name) + ":" + String(value) + "\n"; } } catch (eH) {}
    };
    p.getResponseHeader = function (name) { return real.getResponseHeader(name); };
    p.getAllResponseHeaders = function () { return real.getAllResponseHeaders(); };
    p.overrideMimeType = function (type) { if (real.overrideMimeType) { real.overrideMimeType(type); } };
    p.abort = function () { rec.done = true; real.abort(); copy(); };
    p.send = function (body) {
      var sent = typeof body === "string" ? body.slice(0, AJAX_REQ) : (body === null || body === undefined ? "" : "[object]");
      rec.cut = (typeof body === "string" && body.length > AJAX_REQ) || sent === "[object]";
      rec.req = hideSecrets(sent);
      rec.t0 = new Date().getTime();
      real.onreadystatechange = function () {
        window.__rkAxT = new Date().getTime();
        copy();
        if (real.readyState === 4) { finish(); }
        var handler = p.onreadystatechange || p.onReadyStateChange || p.OnReadyStateChange;
        if (typeof handler === "function") { handler.call(p); }
        if (real.readyState === 4 && typeof p.onload === "function") { p.onload(); }
      };
      if (arguments.length === 0) { real.send(); } else { real.send(body); }
      grabXml();
      if (!rec.async) { copy(); finish(); }
    };
    p.Open = p.open; p.Send = p.send; p.Abort = p.abort; p.SetRequestHeader = p.setRequestHeader; p.GetResponseHeader = p.getResponseHeader;
    p.GetAllResponseHeaders = p.getAllResponseHeaders; p.OverrideMimeType = p.overrideMimeType; mirror();
    return p;
  }
  function hookRequests() {
    var Native = window.XMLHttpRequest, Active = window.ActiveXObject, how = [];
    if (window.__rkNoXhr || window.__rkAjaxHooked) { return; }
    window.__rkAjaxHooked = true;
    try {   // does this page's request object look like the one the stand-in copies? if not, the page is left alone
      if (Native) { var probe = new Native(); if (!probe.open || !probe.send) { window.__rkAjax = "skip:members"; return; } }
    } catch (e0a) { window.__rkAjax = "skip:probe"; return; }
    try {
      if (Native) { window.XMLHttpRequest = function () { return makeStandIn(new Native()); }; how.push("xhr"); }
    } catch (e1) {}
    try {
      if (Active) {
        window.ActiveXObject = function (id) {
          var made = new Active(id);
          return /XMLHTTP/i.test(String(id)) ? makeStandIn(made) : made;
        };
        how.push("activex");
      }
    } catch (e2) {}
    window.__rkAjax = how.join("+") || "none";
  }
  // ---- The script errors of the page itself (what IE shows only as a yellow icon): message, file and line go to the agent, and to the
  // console when this mode has one. The error is never swallowed: the page's own handler still runs. Capped, so a page that fails in a
  // loop does not flood the queue.
  var jsErrCount = 0;
  function toConsole(text) {
    try { if (window.console && window.console.error) { window.console.error("[Rookie] " + text); } } catch (eC) {}
  }
  function reportJsError(message, url, line) {
    var text = "", file = "";
    if (jsErrCount >= 20 || !window.__rkRec) { return; }
    jsErrCount++;
    try { text = String(message).slice(0, 200); } catch (eM) {}
    try { file = String(url).split("?")[0].split("/").pop(); if (!file) { file = "(trang hoặc script sinh ra)"; } } catch (eF) {}
    uidCount++;
    window.__rkq += "{" + '"uid":"' + new Date().getTime() + "-" + Math.floor(Math.random() * 1000000000) + "-" + uidCount + '"' +
      ',"t":' + new Date().getTime() + ',"kind":"jserror","frame":' + str(ownPath()) + ',"host":' + str(String(window.location.hostname)) +
      ',"message":' + str(text) + ',"file":' + str(file) + ',"line":' + (isNaN(Number(line)) ? 0 : Number(line)) +
      ',"hooked":' + (window.__rkAjaxHooked && !window.__rkAjaxOff ? "true" : "false") +
      ',"since_ms":' + (window.__rkAxT ? new Date().getTime() - window.__rkAxT : -1) + "}\n";
  }
  // The recorder judges itself: a script error of the page right after one of our stand-ins worked (2 s) may be our doing, so the
  // page gets its own objects back at once. Pages often assign window.onerror themselves later: every injection puts ours back in front
  // of theirs (theirs still runs).
  var beforeJs = null;
  function ourOnError(message, url, line) {
    try {
      if (window.__rkBusy && new Date().getTime() - window.__rkBusy < 3000) {   // raised by our own code: kept for the panel, not handed to the page
        window.__rkErr = "inside the recorder: " + String(message).slice(0, 120) + " (line " + line + ")";
        toConsole(window.__rkErr);
        return true;
      }
    } catch (eB) {}
    try {
      if (window.__rkAjaxHooked && !window.__rkAjaxOff && new Date().getTime() - (window.__rkAxT || 0) < 2000) { ajaxFailed("pageerror", String(message) + " @" + String(url).split("/").pop() + ":" + line); }
    } catch (eW) {}
    try { reportJsError(message, url, line); } catch (eJ) {}
    // The page's own handler gets exactly what IE gave (every argument, window as this). One that is not a JScript function (a
    // VBScript GetRef) is still called.
    if (beforeJs === null || beforeJs === undefined) { return false; }
    if (typeof beforeJs === "function") { return beforeJs.apply(window, arguments); }
    try { return beforeJs(message, url, line); } catch (eO) { return false; }
  }
  // Only when the page has put in a handler of its own after ours: then ours goes in front again (the page's still runs).
  window.__rkEnsureErr = function () {
    try { if (window.onerror !== ourOnError) { beforeJs = window.onerror; window.onerror = ourOnError; } } catch (eJs) {}
  };
  window.__rkEnsureErr();
  window.__rkAjax = "off";
  try { hookRequests(); } catch (e0) {}
  // window.open(url) of a page or of a file (a report as PDF): the call is reported (method GET, the url as the page gave it, the window name)
  // and then made as the page meant. Put in with the request hook only, so a page where the teller did not ask for requests is left alone;
  // if putting it in fails the page keeps its own window.open. The function is kept apart and called plainly (a host method of old IE has no .apply).
  var openReal = null;
  function openLine(url, name) {
    var u = String(url === null || url === undefined ? "" : url);
    if (!window.__rkRec || !u || /^(javascript|about):/i.test(u)) { return; }
    uidCount++;
    window.__rkq += "{" + '"uid":"o' + new Date().getTime() + "-" + Math.floor(Math.random() * 1000000000) + "-" + uidCount + '","t":' + new Date().getTime() + ',"kind":"open","frame":' + str(ownPath()) +
      ',"method":"GET","url":' + str(u) + ',"target":' + str(String(name === null || name === undefined ? "" : name)) + "}\n";
  }
  function hookOpen() {
    if (window.__rkNoXhr || window.__rkOpenHooked || !window.open) { return; }
    openReal = window.open;
    window.open = function (url, name, features, replace) {
      try { openLine(url, name); } catch (eO) {}
      if (arguments.length >= 4) { return openReal(url, name, features, replace); }
      if (arguments.length === 3) { return openReal(url, name, features); }
      if (arguments.length === 2) { return openReal(url, name); }
      if (arguments.length === 1) { return openReal(url); }
      return openReal();
    };
    window.__rkOpenHooked = true;
  }
  try { hookOpen(); } catch (eHo) { try { if (openReal) { window.open = openReal; } } catch (eHo2) {} }

  // ---- The runner (tasks 4.38 to 4.40): find an element by the selectors of a step and act on it. The agent calls
  // window.__rkOp(op, selectors, value): selectors are separated by a line break, most stable first, as the recorder wrote them
  // ("frame=desktopFrame/rhidden|id=btnOk"). The answer is a JSON text. Nothing is guessed: no element, or more than one, is an error.
  var OP_TAGS = { INPUT: 1, SELECT: 1, TEXTAREA: 1, BUTTON: 1, A: 1, TD: 1, TR: 1, SPAN: 1, IMG: 1, DIV: 1, LABEL: 1, B: 1, FONT: 1 };
  function resolveSpec(spec) {
    var out = [], all, i, el, value, m, lab;
    try {
      if (spec.indexOf("id=") === 0) {
        value = spec.slice(3); all = doc.getElementsByTagName("*");
        for (i = 0; i < all.length; i++) { if (String(all[i].id) === value) { out.push(all[i]); } }       // every one: ids repeat
      } else if (spec.indexOf("name=") === 0) {
        value = spec.slice(5); all = doc.getElementsByTagName("*");
        for (i = 0; i < all.length; i++) { if (String(all[i].name) === value) { out.push(all[i]); } }
      } else if (spec.indexOf("label=") === 0) {
        value = spec.slice(6); all = doc.getElementsByTagName("*");
        for (i = 0; i < all.length; i++) {
          el = all[i];
          if (!OP_TAGS[tag(el)] || isSecret(el)) { continue; }
          lab = isField(el) ? labelOf(el) : actionLabel(el);
          if (lab === value) { out.push(el); }
        }
      } else if (spec.indexOf("src=") === 0) {           // the one element the agent chose after weighing every selector (task 6.1)
        el = doc.all[parseInt(spec.slice(4), 10)]; if (el) { out.push(el); }
      } else {
        m = /^([a-z0-9]+)\[(\d+)\]$/.exec(spec);
        if (m) { all = doc.getElementsByTagName(m[1]); el = all[parseInt(m[2], 10)]; if (el) { out.push(el); } }
      }
    } catch (e) {}
    return out;
  }
  function jsonOk(extra) { return '{"ok":true' + (extra || "") + "}"; }
  function jsonErr(code, extra) { return '{"ok":false,"error":' + str(code) + (extra || "") + "}"; }
  function submitOf(el) {
    var f = null, i, x;
    try { f = el.form; } catch (e) {}
    if (!f) { return null; }
    try {
      for (i = 0; i < f.elements.length; i++) {
        x = f.elements[i];
        if ((tag(x) === "INPUT" && (typeOf(x) === "submit" || typeOf(x) === "image")) || (tag(x) === "BUTTON" && typeOf(x) !== "button" && typeOf(x) !== "reset")) { return x; }
      }
    } catch (e2) {}
    return null;
  }
  // After the value is set, the page hears what a person's typing makes: keys, input, change, then leaving the field. Pages such
  // as TouchPoint unlock «Tìm kiếm» on keyup or on blur; with "change" alone the button stays locked.
  function fireOne(el, name, code) {
    var d = el.ownerDocument, ev;
    try {
      if (el.dispatchEvent && d.createEvent) {                                 // IE9 standards mode: listeners added by addEventListener
        ev = d.createEvent("HTMLEvents"); ev.initEvent(name, true, true);
        try { ev.keyCode = code; } catch (e0) {}
        el.dispatchEvent(ev);
      } else {
        ev = d.createEventObject(); ev.keyCode = code;
        el.fireEvent("on" + name, ev);
      }
    } catch (e) {}
  }
  function typedLikeAPerson(el, value) {
    var s = String(value), code = s.length ? s.charCodeAt(s.length - 1) : 0, names = ["keydown", "keypress", "input", "keyup", "change", "blur"], i;
    for (i = 0; i < names.length; i++) { fireOne(el, names[i], code); }
  }
  function act(op, el, value) {
    var g = tag(el), found = -1, i, b, f, text, list = [];
    try {
      if (op === "exists") { return jsonOk(); }
      if (op === "read") {
        text = (g === "SELECT" || g === "INPUT" || g === "TEXTAREA") ? String(valueOf(el)) : cellText(el);
        return jsonOk(',"value":' + str(text));
      }
      if (el.disabled) { return jsonErr("disabled"); }
      if (op === "click") { el.click(); return jsonOk(); }
      if (op === "fill") {
        if (isSecret(el)) { return jsonErr("secret"); }                       // a password is typed by the teller, never by the agent
        if (el.readOnly) { return jsonErr("readonly"); }
        try { el.focus(); } catch (e1) {}
        el.value = value;
        typedLikeAPerson(el, value);
        return jsonOk(',"value":' + str(String(el.value)));
      }
      if (op === "select") {
        if (g !== "SELECT") { return jsonErr("not_select"); }
        for (i = 0; i < el.options.length; i++) { if (String(el.options[i].value) === value) { found = i; break; } }
        if (found < 0) { for (i = 0; i < el.options.length; i++) { if (clean(el.options[i].text) === clean(value)) { found = i; break; } } }
        if (found < 0) {
          for (i = 0; i < el.options.length && i < 50; i++) { list.push(str(clean(el.options[i].text))); }
          return jsonErr("no_option", ',"options":[' + list.join(",") + "]");
        }
        if (el.selectedIndex !== found) {
          el.selectedIndex = found;
          try { el.fireEvent("onchange"); } catch (e3) {}
        }
        return jsonOk(',"value":' + str(String(el.options[el.selectedIndex].value)) + ',"text":' + str(clean(el.options[el.selectedIndex].text)));
      }
      if (op === "submit") {                                                    // Enter in a field: what the browser does is click the default button
        b = submitOf(el);
        if (b) { b.click(); return jsonOk(',"how":"button"'); }
        f = el.form;
        if (!f) { return jsonErr("no_form"); }
        f.submit();
        return jsonOk(',"how":"form"');
      }
    } catch (e) { return jsonErr("script", ',"detail":' + str(e && e.message ? e.message : e)); }
    return jsonErr("unknown_op");
  }
  // Task 6.1: every selector of this frame looked up, each with the elements it matches (by their place in document.all); the agent
  // weighs them (locate.py) and acts on one element only. Nothing is done to the page.
  function probeAll(sels, own) {
    var i, j, s, cut, spec, kind, hits, ids, out = [], seen = {}, els = [], k;
    for (i = 0; i < sels.length; i++) {
      s = sels[i]; cut = s.indexOf("|");
      if (cut < 0 || s.indexOf("frame=") !== 0 || !sameFrame(s.slice(6, cut), own)) { continue; }
      spec = s.slice(cut + 1);
      kind = spec.indexOf("id=") === 0 ? "id" : spec.indexOf("name=") === 0 ? "name" : spec.indexOf("label=") === 0 ? "label" : "pos";
      hits = resolveSpec(spec); ids = [];
      for (j = 0; j < hits.length; j++) {
        try { k = hits[j].sourceIndex; } catch (eS) { continue; }
        ids.push(k);
        if (!seen[k]) { seen[k] = true; els.push('"' + k + '":' + (isField(hits[j]) ? "1" : "0")); }
      }
      out.push('{"kind":"' + kind + '","m":[' + ids.join(",") + "]}");
    }
    return '{"frame":' + str(own) + ',"probes":[' + out.join(",") + '],"fields":{' + els.join(",") + "}}";
  }
  // Task 6.2: the selectors a step would get for this element now (as the recorder writes them; never a value).
  function selectorsOf(el, own) {
    var out = [], g = tag(el), id = get(el, "id"), name = get(el, "name"), lab = isField(el) ? labelOf(el) : actionLabel(el), p = "frame=" + own + "|";
    if (id) { out.push(p + "id=" + id); }
    if (name) { out.push(p + "name=" + name); }
    if (lab) { out.push(p + "label=" + lab); }
    out.push(p + g.toLowerCase() + "[" + position(el) + "]");
    return out;
  }
  function words(t) { return String(t || "").toLowerCase().replace(/[^a-z0-9À-ỹ]+/g, " ").replace(/^\s+|\s+$/g, "").split(" "); }
  // Up to 3 look-alikes for a step the agent could not decide on: first what its selectors still match, then the fields (or buttons)
  // whose label shares a word with the learned label. Read only.
  function suggest(sels, own, want) {
    var i, j, s, cut, hits, score = [], list = [], learned = "", cand, all, el, lw, w, k, out = [], any = false;
    function ok(e) { if (isSecret(e)) { return false; } return want === "field" ? isField(e) : want === "press" ? !isField(e) : true; }
    function add(e, pts) {
      var n; try { n = e.sourceIndex; } catch (eS) { return; }
      for (k = 0; k < list.length; k++) { if (list[k].n === n) { list[k].pts += pts; return; } }
      list.push({ n: n, el: e, pts: pts });
    }
    for (i = 0; i < sels.length; i++) {
      s = sels[i]; cut = s.indexOf("|");
      if (cut < 0 || s.indexOf("frame=") !== 0 || !sameFrame(s.slice(6, cut), own)) { continue; }
      any = true;
      if (s.slice(cut + 1).indexOf("label=") === 0) { learned = s.slice(cut + 7); }
      hits = resolveSpec(s.slice(cut + 1));
      for (j = 0; j < hits.length; j++) { if (ok(hits[j])) { add(hits[j], 10); } }
    }
    if (!any) { return ""; }
    lw = words(learned);
    if (learned) {
      all = doc.getElementsByTagName("*");
      for (i = 0; i < all.length && i < 5000; i++) {
        el = all[i];
        if (!OP_TAGS[tag(el)] || !ok(el)) { continue; }
        w = words(isField(el) ? labelOf(el) : actionLabel(el)); k = 0;
        for (j = 0; j < w.length; j++) { if (w[j].length > 1 && ("," + lw.join(",") + ",").indexOf("," + w[j] + ",") >= 0) { k++; } }
        if (k) { add(el, k); }
      }
    }
    list.sort(function (a, b) { return b.pts - a.pts; });
    for (i = 0; i < list.length && i < 3; i++) {
      cand = list[i].el;
      out.push('{"src":' + str("frame=" + own + "|src=" + list[i].n) + ',"tag":' + str(tag(cand).toLowerCase()) +
        ',"label":' + str(isField(cand) ? labelOf(cand) : actionLabel(cand)) + ',"selectors":' + jsonStrings(selectorsOf(cand, own)) + "}");
    }
    return '{"frame":' + str(own) + ',"candidates":[' + out.join(",") + "]}";
  }
  // Task 6.4: what this frame's screen is made of: the kind and the label of each field and button (never a value).
  function fingerprint(own) {
    var tags = ["input", "select", "textarea", "button"], i, j, all, el, t, out = [];
    for (i = 0; i < tags.length; i++) {
      all = doc.getElementsByTagName(tags[i]);
      for (j = 0; j < all.length && out.length < 300; j++) {
        el = all[j]; t = typeOf(el);
        if (t === "hidden") { continue; }
        out.push(str(tag(el).toLowerCase() + (t ? ":" + t : "") + "|" + (isField(el) ? labelOf(el) : actionLabel(el))));
      }
    }
    return '{"frame":' + str(own) + ',"items":[' + out.join(",") + "]}";
  }
  // The look-alikes are shown to the teller with a colour on the page itself (runtimeStyle: the page's own style is not touched).
  var marked = [];
  function markAll(sels, own) {
    var i, s, cut, el;
    for (i = 0; i < sels.length; i++) {
      s = sels[i]; cut = s.indexOf("|");
      if (cut < 0 || s.slice(6, cut) !== own || s.indexOf("|src=") < 0) { continue; }
      el = doc.all[parseInt(s.slice(s.indexOf("|src=") + 5), 10)];
      if (el) { try { el.runtimeStyle.backgroundColor = ["#ffd54f", "#81d4fa", "#c5e1a5"][marked.length % 3]; marked.push(el); } catch (eM) {} }
    }
    return "";
  }
  function unmarkAll() {
    var i;
    for (i = 0; i < marked.length; i++) { try { marked[i].runtimeStyle.backgroundColor = ""; } catch (eU) {} }
    marked = [];
    return "";
  }
  // ---- Gate 7: a learned request sent again from this frame, in the teller's own session (the page's cookies go with it, none is read).
  // "send" starts it and answers at once with an id; "sendres" gives the answer when it has come. Nothing on the screen is touched.
  var SEND_MAX = 200000, sending = {}, sendCount = 0;
  function newXhr() {
    try { if (Native0) { return new Native0(); } } catch (e1) {}
    try { if (window.XMLHttpRequest) { return new window.XMLHttpRequest(); } } catch (e2) {}
    return new ActiveXObject("Msxml2.XMLHTTP");
  }
  function sendNow(own, value) {
    var parts = String(value).split("\u0001"), x, id, rec, lines, i, at, method;
    if (parts.length < 5 || parts[0] !== own) { return ""; }
    sendCount++;
    id = "q" + new Date().getTime() + "-" + sendCount;
    rec = { done: false, status: 0, ms: 0, text: "", error: "", t0: new Date().getTime() };
    sending[id] = rec;
    try {
      x = newXhr(); method = String(parts[1]).toUpperCase();
      x.open(method, parts[2], true);
      lines = parts[3] ? parts[3].split("\n") : [];
      for (i = 0; i < lines.length; i++) { at = lines[i].indexOf(":"); if (at > 0) { x.setRequestHeader(lines[i].slice(0, at), lines[i].slice(at + 1)); } }
      x.onreadystatechange = function () {
        if (x.readyState !== 4 || rec.done) { return; }
        rec.done = true; rec.ms = new Date().getTime() - rec.t0;
        try { rec.status = x.status; } catch (e3) {}
        // A file answer (told by its headers) is not read as text: the request object is kept and the agent reads its bytes (window.__rkFileX).
        try { if (isFileHeaders(header(x, "Content-Type"), header(x, "Content-Disposition")) && !(rec.status >= 400)) {
          rec.file = true; rec.ctype = header(x, "Content-Type"); rec.disp = header(x, "Content-Disposition"); rec.len = parseInt(header(x, "Content-Length"), 10) || 0; rec.x = x;
          return;
        } } catch (eF) {}
        try { rec.text = String(x.responseText).slice(0, SEND_MAX); } catch (e4) {}
      };
      x.send(method === "GET" || method === "HEAD" ? null : parts[4]);
    } catch (e) { rec.done = true; rec.error = String(e && e.message ? e.message : e).slice(0, 200); }
    return '{"frame":' + str(own) + ',"id":' + str(id) + "}";
  }
  function sendResult(id) {
    var rec = sending[String(id)];
    if (!rec) { return ""; }
    if (!rec.done) { return '{"id":' + str(String(id)) + ',"done":false}'; }
    delete sending[String(id)];
    if (rec.file) {
      keptFiles[String(id)] = rec.x; keptOrder.push(String(id));
      while (keptOrder.length > 5) { delete keptFiles[keptOrder.shift()]; }
      return '{"id":' + str(String(id)) + ',"done":true,"status":' + (rec.status || 0) + ',"ms":' + rec.ms + ',"text":"","error":"","file":true,"ctype":' + str(rec.ctype) +
        ',"disp":' + str(rec.disp) + ',"len":' + (rec.len || 0) + "}";
    }
    return '{"id":' + str(String(id)) + ',"done":true,"status":' + (rec.status || 0) + ',"ms":' + rec.ms + ',"text":' + str(rec.text) + ',"error":' + str(rec.error) + "}";
  }
  // The request object of a file answer waits here (at most 5) until the agent has read its bytes over COM and drops it.
  var keptFiles = {}, keptOrder = [];
  window.__rkFileX = function (id, drop) {
    try {
      if (drop) { delete keptFiles[String(id)]; return ""; }
      return keptFiles[String(id)] || null;
    } catch (eK) { return null; }
  };
  window.__rkOp = function (op, selText, value) {
    var sels = String(selText).split("\n"), own = framePath(window), i, s, cut, hits, found = null, rank = -1;
    if (op === "send") { return sendNow(own, value); }
    if (op === "sendres") { return sendResult(value); }
    if (op === "lastreq") { return lastReq(value); }
    if (op === "probe") { return probeAll(sels, own); }
    if (op === "suggest") { return suggest(sels, own, String(value || "any")); }
    if (op === "fingerprint") { return fingerprint(own); }
    if (op === "mark") { return markAll(sels, own); }
    if (op === "unmark") { return unmarkAll(); }
    for (i = 0; i < sels.length; i++) {
      s = sels[i]; cut = s.indexOf("|");
      if (cut < 0 || s.indexOf("frame=") !== 0 || !sameFrame(s.slice(6, cut), own)) { continue; }
      hits = resolveSpec(s.slice(cut + 1));
      if (hits.length) { found = hits; rank = i; break; }
    }
    if (op === "find") { return '{"frame":' + str(own) + ',"count":' + (found ? found.length : 0) + ',"rank":' + rank + "}"; }
    if (!found) { return jsonErr("not_found"); }
    if (found.length > 1) { return jsonErr("ambiguous", ',"count":' + found.length); }
    return act(String(op), found[0], String(value === null || value === undefined ? "" : value));
  };

  // ---- What the screen shows (tasks 4.31, 4.32): the tables of data, the label-value pairs and the messages of this page. The agent
  // asks for it with window.__rkRead() after an action. A password or hidden field is never read. Values stay in the agent's memory.
  var READ_ROWS = 50, READ_COLS = 20, READ_CELL = 200;
  var MSG_HINT = /err|msg|mess|alert|warn|status|thong|bao|loi/i;
  var ERROR_TEXT = /l\u1ED7i|error|fail|exception|denied|invalid|kh\u00F4ng th\u00E0nh c\u00F4ng|kh\u00F4ng t\u00ECm th\u1EA5y|khong tim thay|kh\u00F4ng h\u1EE3p l\u1EC7|t\u1EEB ch\u1ED1i/i;
  var MSG_TAGS = { DIV: 1, SPAN: 1, TD: 1, P: 1, FONT: 1, B: 1, LABEL: 1, STRONG: 1, H1: 1, H2: 1, H3: 1, H4: 1 };

  function cellText(c) {
    var t = "";
    try { t = c.innerText; } catch (e) {}
    t = String(t === null || t === undefined ? "" : t).replace(/[\r\n\t ]+/g, " ").replace(/^\s+|\s+$/g, "");
    return t.length > READ_CELL ? t.slice(0, READ_CELL) : t;
  }
  function visibleBox(el) { try { return el.offsetWidth > 0 && el.offsetHeight > 0; } catch (e) { return true; } }
  function countControls(el) {
    try { return el.getElementsByTagName("input").length + el.getElementsByTagName("select").length + el.getElementsByTagName("textarea").length; }
    catch (e) { return 0; }
  }
  function hasTh(row) {
    var i;
    try { for (i = 0; i < row.cells.length; i++) { if (tag(row.cells[i]) === "TH") { return true; } } } catch (e) {}
    return false;
  }
  function jsonStrings(list) {
    var out = [], i;
    for (i = 0; i < list.length; i++) { out.push(str(list[i])); }
    return "[" + out.join(",") + "]";
  }
  function readTables() {
    var tbls = doc.getElementsByTagName("table"), out = [], i, j, k, t, rows, width, same, body, row, cells, cols, heads, cellsTotal, rowsJson, n;
    for (i = 0; i < tbls.length && out.length < 10; i++) {
      t = tbls[i];
      try {
        if (t.getElementsByTagName("table").length > 0) { continue; }          // a layout table that holds other tables
        rows = t.rows;
        if (!rows || rows.length < 2) { continue; }
        width = rows[0].cells.length;
        if (width < 2) { continue; }
        same = 0; cellsTotal = 0;
        for (j = 0; j < rows.length; j++) { if (rows[j].cells.length === width) { same++; } cellsTotal += rows[j].cells.length; }
        if (same < rows.length * 0.7) { continue; }
        if (countControls(t) * 4 >= cellsTotal) { continue; }                  // a form laid out in a table
        if (!hasTh(rows[0]) && rows.length < 3) { continue; }                  // two rows without a header: label and value, read as fields
        sset(t, "data", true);
        cols = width > READ_COLS ? READ_COLS : width;
        heads = [];
        for (k = 0; k < cols; k++) { heads.push(cellText(rows[0].cells[k])); }
        body = []; n = 0;
        for (j = 1; j < rows.length; j++) {
          cells = rows[j].cells; row = [];
          for (k = 0; k < cols && k < cells.length; k++) { row.push(cellText(cells[k])); }
          if (row.join("") === "") { continue; }
          n++;
          if (body.length < READ_ROWS) { body.push(jsonStrings(row)); }
        }
        rowsJson = "[" + body.join(",") + "]";
        out.push('{"id":' + str(t.id || "") + ',"headers":' + jsonStrings(heads) + ',"rows":' + rowsJson + ',"row_count":' + n + "}");
      } catch (e) {}
    }
    return "[" + out.join(",") + "]";
  }
  function controlText(cell) {
    var ctl, i, g, ty;
    try {
      ctl = cell.getElementsByTagName("input");
      for (i = 0; i < ctl.length; i++) { if (isSecret(ctl[i])) { return null; } }
      ctl = cell.getElementsByTagName("select");
      if (ctl.length) { return isSecret(ctl[0]) ? null : String(valueOf(ctl[0])); }
      ctl = cell.getElementsByTagName("textarea");
      if (ctl.length) { return isSecret(ctl[0]) ? null : String(ctl[0].value); }
      ctl = cell.getElementsByTagName("input");
      for (i = 0; i < ctl.length; i++) {
        ty = typeOf(ctl[i]);
        if (ty === "text" || ty === "") { return String(ctl[i].value); }
      }
    } catch (e) { return null; }
    return cellText(cell);
  }
  function readFields() {
    var rows = doc.getElementsByTagName("tr"), out = [], i, tr, cells, label, v, p;
    for (i = 0; i < rows.length && out.length < 60; i++) {
      tr = rows[i];
      try {
        p = tr.parentNode;
        while (p && tag(p) !== "TABLE") { p = p.parentNode; }
        if (p && sget(p, "data")) { continue; }                                      // a row of a table of data is not a pair
        cells = tr.cells;
        if (cells.length !== 2) { continue; }
        if (cells[0].getElementsByTagName("table").length || cells[1].getElementsByTagName("table").length) { continue; }
        label = cellText(cells[0]).replace(/\s*:\s*$/, "");
        if (!label || label.length > 40) { continue; }
        v = controlText(cells[1]);
        if (v === null) { continue; }
        out.push('{"label":' + str(label) + ',"value":' + str(v.length > READ_CELL ? v.slice(0, READ_CELL) : v) + "}");
      } catch (e) {}
    }
    return "[" + out.join(",") + "]";
  }
  function readMessages() {
    var all = doc.getElementsByTagName("*"), out = [], seen = {}, i, el, g, text;
    for (i = 0; i < all.length && out.length < 5; i++) {
      el = all[i];
      try {
        g = tag(el);
        if (!MSG_TAGS[g]) { continue; }
        if (!MSG_HINT.test(String(el.className || "") + " " + String(el.id || ""))) { continue; }
        if (el.getElementsByTagName("table").length) { continue; }
        text = cellText(el);
        if (!text || text.length > 300 || seen[text] || !visibleBox(el)) { continue; }
        seen[text] = true;
        out.push('{"level":' + str(ERROR_TEXT.test(text) ? "error" : "info") + ',"text":' + str(text) + "}");
      } catch (e) {}
    }
    return "[" + out.join(",") + "]";
  }
  window.__rkRead = function () {
    if (window.__rkTestReadFail) { throw new Error("forced read failure"); }
    var head = '{"frame":' + str(framePath(window)) + ',"title":' + str(clean(get(doc, "title")));
    try { return head + ',"tables":' + readTables() + ',"fields":' + readFields() + ',"messages":' + readMessages() + "}"; }
    catch (e) { return head + ',"tables":[],"fields":[],"messages":[],"error":' + str(e && e.message ? e.message : e) + "}"; }
  };

  // Anything a teller can press, whatever its tag: a button, a link, a check box; a tab, a menu item, a row of a list
  // (hand cursor, or its own click handler). Text that cannot be pressed is not an action. When the whole chain of
  // ancestors shows the hand cursor (it is inherited), the outermost of them is the thing pressed.
  var PLAIN_FIELD = { TEXTAREA: 1, SELECT: 1, OPTION: 1 };
  function handCursor(el) {
    var c = "";
    try { c = String(el.currentStyle.cursor || "").toLowerCase(); } catch (e) {}
    return c === "pointer" || c === "hand";
  }
  function actionable(el) {
    var depth = 0, g, t, found = null, parent;
    while (el && depth++ < 10) {
      g = tag(el);
      t = typeOf(el);
      if (g === "BODY" || g === "HTML") { break; }
      if (PLAIN_FIELD[g] || (g === "INPUT" && (t === "text" || t === "password" || t === "" || t === "file"))) { return null; }
      if (g === "BUTTON" || g === "A") { return el; }
      if (g === "INPUT" && (t === "button" || t === "submit" || t === "image" || t === "reset" || t === "checkbox" || t === "radio")) { return el; }
      if (el.onclick || handCursor(el)) {
        found = el;
        parent = el.parentNode;
        if (!parent || !(parent.onclick || handCursor(parent)) || tag(parent) === "BODY") { return found; }
      }
      el = el.parentNode;
    }
    return found;
  }

  function isField(el) {
    var g = tag(el), t;
    if (g === "TEXTAREA" || g === "SELECT") { return true; }
    if (g !== "INPUT") { return false; }
    t = typeOf(el);
    return t !== "button" && t !== "submit" && t !== "image" && t !== "reset" && t !== "checkbox" && t !== "radio";
  }

  function flushField(el) {
    var now, base;
    if (!isField(el) || isSecret(el)) { return false; }
    now = valueOf(el);
    base = sget(el, "v");
    // No focusin was seen: the field already had the focus when recording began (a login page puts the cursor in the user
    // field). Its value before was unknown; for a text field it is taken as empty, so what the teller typed is not lost.
    // Not for a field the page's own script put the cursor in (and may have filled): unless the teller typed in it, its value is the page's.
    if (base === undefined && tag(el) !== "SELECT" && (!sget(el, "pf") || sget(el, "c"))) { base = ""; }
    if (base !== undefined && base !== now) {
      emit(tag(el) === "SELECT" ? "select" : "input", el, now, labelOf(el), ',"before":' + str(base) + ',"optv":' + str(optValue(el)));
      sset(el, "v", now);
      return true;
    }
    return false;
  }

  // A page that reloads its frame the moment a value is chosen (a language list that refreshes the role list) is gone before the
  // field loses the focus, so the blur that saves the value never comes. The change itself saves it, and so does the page leaving.
  function flushFocused() {
    var a = null;
    if (!window.__rkRec) { return; }
    try { a = doc.activeElement; } catch (e) {}
    if (a && isField(a) && !isSecret(a)) { try { flushField(a); } catch (e2) {} }
  }
  function onChange(ev) {
    var e = ev || window.event, el = e ? (e.srcElement || e.target) : null;
    if (!window.__rkRec || !el || !isField(el) || isSecret(el)) { return; }
    flushField(el);
  }

  // Each handler takes the event as an argument when the browser gives one, else window.event (old IE).
  // Everything the teller presses is recorded; nothing is left out because a rule did not foresee it. What is preferred is
  // the thing that is meant to be pressed (actionable); when there is none, the element itself is recorded (a cell, an image,
  // a label) with ctl:false, so the model that designs the workflow can decide what it means. A click into a text field is
  // not a click: the focus that follows records it.
  function isPlainFieldEl(el) {
    var g = tag(el), t = typeOf(el);
    return !!PLAIN_FIELD[g] || (g === "INPUT" && (t === "text" || t === "password" || t === "" || t === "file"));
  }
  function clickLike(kind, ev) {
    var e, target, el, ctl = true, g;
    if (!window.__rkRec) { return; }
    e = ev || window.event;
    target = e ? (e.srcElement || e.target) : null;
    if (!target || isPlainFieldEl(target)) { return; }
    el = actionable(target);
    if (!el) {
      g = tag(target);
      if (g === "BODY" || g === "HTML" || !g) { return; }
      el = target;
      ctl = false;
    }
    if (isSecret(el)) { return; }
    // Enter in a field of a form makes the browser click the submit button of THAT form: that click is part of the Enter, not an
    // action of the teller (replaying both would send the form twice). A click on any other button is the teller's.
    if (window.__rkEnter && window.__rkEnterForm && new Date().getTime() - window.__rkEnter < 400 && (typeOf(el) === "submit" || typeOf(el) === "image")) {
      try { if (el.form == window.__rkEnterForm) { return; } } catch (eClick) {}
    }
    emit(kind, el, null, actionLabel(el), ',"ctl":' + (ctl ? "true" : "false"));
    if (typeOf(el) === "submit" || typeOf(el) === "image") { try { leavingForm = el.form; leavingAt = new Date().getTime(); markForm(); laterForm(); } catch (eLf) {} }
  }
  // A form sent into a frame (target=...) leaves this page in place: its line is made by our own timer, once the page's script has
  // finished (never in the middle of it). A page that leaves first makes it on unload (keepLines).
  function laterForm() {
    try { window.setTimeout(function () { var s = ""; try { if (window.__rkRec) { s = formLine(); } } catch (e1) {} if (s) { window.__rkq += s; } }, 0); } catch (e2) {}
  }
  function onClick(ev) { clickLike("click", ev); }
  function onDblClick(ev) { clickLike("dblclick", ev); }
  function onFocusIn(ev) {
    var e = ev || window.event, el = e ? (e.srcElement || e.target) : null;
    if (!window.__rkRec || !el || !isField(el) || isSecret(el)) { return; }
    try { sset(el, "v", valueOf(el)); sset(el, "c", false); } catch (eF) {}
    emit("focus", el, null, labelOf(el), ',"ctl":true' + (tag(el) === "SELECT" ? ',"optv":' + str(optValue(el)) + ',"opts":' + optionsJson(el) : ""));
  }
  function onFocusOut(ev) {
    var e = ev || window.event, el = e ? (e.srcElement || e.target) : null;
    if (!window.__rkRec || !el) { return; }
    flushField(el);
    if (isField(el) && !isSecret(el)) { emit("blur", el, null, labelOf(el), ',"ctl":true'); }
  }
  // Only the class of a key is recorded, never the character. Typing is one "char" event per visit to a field; the value
  // comes later, from the change.
  function keyClass(code) {
    if (code === 13) { return "enter"; }
    if (code === 9) { return "tab"; }
    if (code === 27) { return "escape"; }
    if (code >= 112 && code <= 123) { return "function"; }
    if (code >= 37 && code <= 40) { return "arrow"; }
    if (code === 16 || code === 17 || code === 18) { return ""; }
    return "char";
  }
  function onKeyDown(ev) {
    var e = ev || window.event, el = e ? (e.srcElement || e.target) : null, kc, field;
    if (!window.__rkRec || !el) { return; }
    if (e.keyCode === 13) {
      if (tag(el) === "INPUT" && isField(el) && !isSecret(el)) {
        flushField(el);                       // the typed value first, then the Enter that sends it
        window.__rkEnter = new Date().getTime();
        try { window.__rkEnterForm = el.form; leavingForm = el.form; leavingAt = new Date().getTime(); markForm(); laterForm(); } catch (eForm) { window.__rkEnterForm = null; }
        emit("submit", el, null, labelOf(el));
        return;
      }
      if (tag(el) === "INPUT" && typeOf(el) === "password") {
        window.__rkEnter = new Date().getTime();
        try { window.__rkEnterForm = el.form; } catch (eForm) { window.__rkEnterForm = null; }
        emit("submit", el, null, labelOf(el)); // Enter in a password field: the action is kept, the value never read
        return;
      }
    }
    if (isSecret(el)) { return; }
    kc = keyClass(e.keyCode);
    if (!kc) { return; }
    field = isField(el);
    if (kc === "char") {
      if (!field || sget(el, "c")) { return; }
      sset(el, "c", true);
    }
    emit("key", el, null, field ? labelOf(el) : actionLabel(el), ',"ctl":' + (field ? "true" : "false") + ',"keyclass":"' + kc + '"');
  }

  // Which element the failing event was about (tag, id or name only), so an error says where it happened.
  function whereIs(ev) {
    var el = null, out = "";
    try { el = (ev || window.event); el = el ? (el.srcElement || el.target) : null; } catch (eW1) {}
    if (!el) { return "no element"; }
    out = tag(el).toLowerCase() || "?";
    out += "#" + String(get(el, "id") || get(el, "name") || "");
    return out;
  }
  // Diagnosis only (window.__rkBody): a field listener does just one kind of reading and records nothing, to find which reading upsets a page.
  function probe(kind, ev) {
    var e = ev || window.event, el = e ? (e.srcElement || e.target) : null;
    if (!el) { return; }
    if (kind === "prop") { el.uniqueID; valueOf(el); typeOf(el); isSecret(el); }
    else if (kind === "uid") { el.uniqueID; }
    else if (kind === "value") { valueOf(el); }
    else if (kind === "meta") { typeOf(el); isSecret(el); }
    else if (kind === "label") { labelOf(el); }
    else if (kind === "place") { position(el); framePath(window); clean(get(doc, "title")); }
  }
  // While an event of the page is being dispatched, the recorder touches NOTHING of the page: it only keeps the element and the key. The
  // reading (value, label, position) is done a moment later, in the order the events came, by our own timer, when the page has finished
  // with the event. (On TouchPoint, reading a field inside its own focus/change event, which the page's script was making at that moment,
  // ended in a script error of the page: a read in the middle of the page's own work.) The page leaving drains the queue first.
  //
  // A focus or change no press of the teller led to (the page's own script moved the cursor or filled a field, as TouchPoint does when
  // its answer comes) is not read at all, not even later: the teller's press is a mouse button going down or a key, at most GATE_MS
  // before. Of such an event only one thing is kept, without reading the element: that the field the teller was in has lost the cursor
  // (its value is read at the teller's next press), or that the page put the cursor in a field (its value is the page's, not typed).
  var pending = [], drainTimer = null, lastPress = 0, GATE_MS = 800;
  function onPress() { lastPress = new Date().getTime(); }      // mouse button down: the time only, nothing of the event or the element
  function pageMade(item) {
    var f;
    if (!window.__rkRec || !item.el) { return; }
    if (item.name === "focusin") { if (sget(item.el, "v") === undefined) { sset(item.el, "pf", true); } return; }
    f = sfind(item.el);
    if (f && (f.v !== undefined || f.c)) { f.dirty = true; }
  }
  // Fields the teller was in that lost the cursor by the page's doing: their value is read now (a press of the teller, or the page leaving).
  function flushDirty() {
    var i, f;
    if (!window.__rkRec) { return; }
    for (i = 0; i < STATE.length; i++) {
      f = STATE[i];
      if (f.dirty) { f.dirty = false; try { flushField(f.el); } catch (eD) {} }
    }
  }
  function runOne(item) {
    var ev = { srcElement: item.el, target: item.el, keyCode: item.kc };
    if (item.line) { window.__rkq += item.line; return; }   // a line already made (a request): its place in the order only
    try {
      if (window.__rkTestHandlerFail) { throw new Error("forced handler failure"); }
      if (!item.teller) { pageMade(item); return; }
      flushDirty();
      item.fn(ev);
    } catch (e) {
      window.__rkErr = item.name + ": " + (e && e.message ? e.message : e) + " [" + whereIs(ev) + "]";
      toConsole(window.__rkErr);
    }
  }
  function drain() {
    var item, guard = 0;
    drainTimer = null;
    while (pending.length && guard++ < 500) { item = pending.shift(); runOne(item); }
  }
  window.__rkDrain = drain;
  function guarded(name, fn) {
    return function (ev) {
      var e = null, el = null, kc = 0, now = new Date().getTime(), teller = name === "click" || name === "dblclick" || name === "keydown";
      try { e = ev || window.event; el = e ? (e.srcElement || e.target) : null; if (name === "keydown" && e) { kc = e.keyCode; } } catch (eQ) {}
      if (window.__rkBody && (name === "focusin" || name === "focusout" || name === "change")) {   // diagnosis only: the reading is done inside the event
        try { probe(window.__rkBody, ev); } catch (eP) {}
        return;
      }
      if (teller) { lastPress = now; if (name !== "dblclick") { markForm(); } } else { teller = now - lastPress <= GATE_MS; }   // a press: if the page then leaves (beforeunload), it may be a form sent (see formGo)
      pending.push({ name: name, fn: fn, el: el, kc: kc, teller: teller });
      if (!drainTimer) { try { drainTimer = window.setTimeout(drain, 0); } catch (eT) { drain(); } }
    };
  }
  window.__rkHandlers = { click: onClick, dblclick: onDblClick, focusin: onFocusIn, focusout: onFocusOut, keydown: onKeyDown }; // for tests
  // Old IE (quirks, document mode 5..8) has attachEvent only; IE9+ in standards mode has addEventListener only.
  // focusin/focusout are used because they bubble; with addEventListener the capture phase is used as well.
  var LISTENERS = [["click", guarded("click", onClick)], ["dblclick", guarded("dblclick", onDblClick)], ["change", guarded("change", onChange)],
                   ["focusin", guarded("focusin", onFocusIn)], ["focusout", guarded("focusout", onFocusOut)], ["keydown", guarded("keydown", onKeyDown)],
                   ["mousedown", onPress]];
  // For finding which listener upsets a page: ROOKIE_IE_LISTEN="none" or a list such as "click,keydown" (set before the agent starts)
  // puts in only those. Not set: all of them, as always. The mouse-down listener goes with the field and click listeners it serves.
  function allowed(name) {
    var o = window.__rkOnly;
    if (o && name === "mousedown") { return allowed("focusin") || allowed("focusout") || allowed("change") || allowed("click") || ("," + o + ",").indexOf(",mousedown,") >= 0; }
    return !o || ("," + o + ",").indexOf("," + name + ",") >= 0;
  }
  var done = {}, loadDone = false;
  // Each listener is put in on its own, inside try: a frame that is being rebuilt can refuse one ("Failed") and the others must still go in.
  // What is refused is tried again at the next look (window.__rkTake calls window.__rkAttach), until all are in.
  function attachAll() {
    var i, name, handler, all = true;
    for (i = 0; i < LISTENERS.length; i++) {
      name = LISTENERS[i][0]; handler = window.__rkEmpty ? function () {} : LISTENERS[i][1];   // __rkEmpty (diagnosis only): the listener is there, and does nothing
      if (done[name]) { continue; }
      if (!allowed(name)) { done[name] = true; continue; }
      try {
        if (doc.attachEvent) { doc.attachEvent("on" + name, handler); window.__rkAttached = "attachEvent"; done[name] = true; }
        else if (doc.addEventListener) { doc.addEventListener(name, handler, true); window.__rkAttached = "addEventListener"; done[name] = true; }
        else { all = false; }
      } catch (eL) { all = false; window.__rkErr = "attach " + name + ": " + (eL && eL.message ? eL.message : eL); }
    }
    if (!allowed("load")) { loadDone = true; }
    if (!loadDone) {
      try {
        if (window.attachEvent) { window.attachEvent("onload", snapshotLater); loadDone = true; }
        else if (window.addEventListener) { window.addEventListener("load", snapshotLater, false); loadDone = true; }
      } catch (eW) { all = false; window.__rkErr = "attach load: " + (eW && eW.message ? eW.message : eW); }
    }
    if (window.__rkOnly && window.__rkAttached === "none") { window.__rkAttached = "off"; }   // left out on purpose: the panel must not take it for a failure
    window.__rkAttachedAll = all && loadDone;
  }
  window.__rkAttach = function () { if (!window.__rkAttachedAll) { attachAll(); } };
  // The field that has the focus right now (recording starts on a page that is already loaded): its value is the baseline.
  try {
    var focused = doc.activeElement;
    if (focused && isField(focused) && !isSecret(focused) && sget(focused, "v") === undefined) { sset(focused, "v", valueOf(focused)); }
  } catch (e0) {}
  window.__rkAttached = "none";
  snapshotLater();
  try { window.setTimeout(snapshotLater, 1500); } catch (e3) {}
  attachAll();
  window.__rkRead = external("read", window.__rkRead);
  window.__rkOp = external("op", window.__rkOp);
  window.__rkRestore = external("restore", restoreLines);
  window.__rkBusy = 0;
  } catch (eInit) {
    try { window.__rkBusy = 0; window.__rkErr = "init: " + (eInit && eInit.message ? eInit.message : eInit); } catch (eI2) {}
  }
})();
