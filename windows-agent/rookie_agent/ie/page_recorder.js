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
  if (window.__rkOn) { window.__rkRec = true; return; }
  window.__rkOn = true;
  window.__rkRec = true;
  window.__rkq = "";
  window.__rkTake = function () { var s = window.__rkq; window.__rkq = ""; return s; };

  var doc = document;
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
  function tag(el) { return el && el.tagName ? String(el.tagName).toUpperCase() : ""; }
  function typeOf(el) { var t = ""; try { t = String(el.type || "").toLowerCase(); } catch (e) {} return t; }

  function framePath(w) {
    var parts = [], guard = 0, p, name, i, n;
    while (guard++ < 10) {
      try { p = w.parent; } catch (e) { break; }
      if (!p || p === w) { break; }
      name = "";
      try { name = w.name; } catch (e2) {}
      if (!name) {
        try { n = p.frames.length; for (i = 0; i < n; i++) { if (p.frames[i] === w) { name = "#" + i; break; } } } catch (e3) {}
      }
      parts.unshift(name || "#?");
      w = p;
    }
    return parts.length ? parts.join("/") : "top";
  }

  function isSecret(el) {
    var t = typeOf(el);
    return t === "password" || t === "hidden" || t === "file" || SECRET.test(String(el.name || "")) || SECRET.test(String(el.id || ""));
  }

  function labelOf(el) {
    var t = "", id = el.id, ls, i, cell, prev;
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
    if (!clean(t)) { t = el.title || el.alt || el.name || el.id || ""; }
    return clean(t);
  }

  function actionLabel(el) {
    var t = "";
    try {
      var g = tag(el);
      if (g === "INPUT") { t = el.value || el.title || el.alt || el.id; }
      else if (g === "TR") {            // a row of a list: its cells, separated (innerText may run them together)
        var cells = el.cells, k, parts = [];
        for (k = 0; k < cells.length && k < 8; k++) { parts.push(cells[k].innerText); }
        t = parts.join(" ");
      }
      else { t = el.innerText || el.title || el.alt || el.id || el.name; }
    } catch (e) {}
    return clean(t);
  }

  function position(el) {
    var all, i;
    try {
      all = doc.getElementsByTagName(tag(el));
      for (i = 0; i < all.length; i++) { if (all[i] === el) { return i; } }
    } catch (e) {}
    return -1;
  }

  function emit(kind, el, value, label) {
    var line = "{" +
      '"t":' + new Date().getTime() +
      ',"kind":"' + kind + '"' +
      ',"frame":' + str(framePath(window)) +
      ',"title":' + str(clean(doc.title)) +
      ',"tag":' + str(tag(el).toLowerCase()) +
      ',"type":' + str(typeOf(el)) +
      ',"id":' + str(el.id) +
      ',"name":' + str(el.name) +
      ',"label":' + str(label) +
      ',"pos":' + position(el) +
      ',"value":' + str(value) +
      "}\n";
    window.__rkq += line;
  }

  function valueOf(el) {
    try {
      if (tag(el) === "SELECT") {
        return el.selectedIndex >= 0 ? el.options[el.selectedIndex].text : "";
      }
      return el.value;
    } catch (e) { return ""; }
  }

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
    var g = tag(el), t = typeOf(el);
    if (g === "TEXTAREA" || g === "SELECT") { return true; }
    return g === "INPUT" && t !== "button" && t !== "submit" && t !== "image" && t !== "reset" && t !== "checkbox" && t !== "radio";
  }

  function flushField(el) {
    var now;
    if (!isField(el) || isSecret(el)) { return false; }
    now = valueOf(el);
    if (el.__rkv !== undefined && el.__rkv !== now) {
      emit(tag(el) === "SELECT" ? "select" : "input", el, now, labelOf(el));
      el.__rkv = now;
      return true;
    }
    return false;
  }

  // Each handler takes the event as an argument when the browser gives one, else window.event (old IE).
  function onClick(ev) {
    var e, el;
    if (!window.__rkRec) { return; }
    e = ev || window.event;
    el = actionable(e ? e.srcElement : null);
    if (!el || isSecret(el)) { return; }
    emit("click", el, null, actionLabel(el));
  }
  function onFocusIn(ev) {
    var e = ev || window.event, el = e ? e.srcElement : null;
    if (!window.__rkRec || !el || !isField(el) || isSecret(el)) { return; }
    el.__rkv = valueOf(el);
  }
  function onFocusOut(ev) {
    var e = ev || window.event, el = e ? e.srcElement : null;
    if (!window.__rkRec || !el) { return; }
    flushField(el);
  }
  function onKeyDown(ev) {
    var e = ev || window.event, el = e ? e.srcElement : null;
    if (!window.__rkRec || !el || e.keyCode !== 13) { return; }
    if (tag(el) === "INPUT" && isField(el) && !isSecret(el)) {
      flushField(el);                       // the typed value first, then the Enter that sends it
      emit("submit", el, null, labelOf(el));
    } else if (tag(el) === "INPUT" && typeOf(el) === "password") {
      emit("submit", el, null, labelOf(el)); // Enter in a password field: the action is kept, the value never read
    }
  }

  function guarded(name, fn) {
    return function (ev) {
      try { fn(ev); } catch (e) { window.__rkErr = name + ": " + (e && e.message ? e.message : e); }
    };
  }
  window.__rkHandlers = { click: onClick, focusin: onFocusIn, focusout: onFocusOut, keydown: onKeyDown }; // for tests
  doc.attachEvent("onclick", guarded("click", onClick));
  doc.attachEvent("onfocusin", guarded("focusin", onFocusIn));
  doc.attachEvent("onfocusout", guarded("focusout", onFocusOut));
  doc.attachEvent("onkeydown", guarded("keydown", onKeyDown));
})();
