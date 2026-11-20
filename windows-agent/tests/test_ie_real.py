"""The IE recorder on a REAL Internet Explorer window (a change to the IE path only counts as done when this passes).

It opens its own IE window (title "RookieE2E ...") on a small local site shaped like TouchPoint (a login page, then a page with
nested iframes and a frameset whose frame `rhidden` holds the role form), drives it through COM like a teller, and checks what the
real bridge and session recorded. It never touches another IE window and never ends a process: it only quits its own window.
It brings its own window to the front, so run it when you are not typing elsewhere.

    $env:ROOKIE_REAL_IE = "1"; pytest tests/test_ie_real.py
"""

import contextlib
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from rookie_agent.ie.bridge import IeBridge
from rookie_agent.ie.session import IeSession

DRIVE = str(Path(__file__).with_name("ie_real_drive.ps1"))
pytestmark = pytest.mark.skipif(sys.platform != "win32" or os.environ.get("ROOKIE_REAL_IE") != "1",
                                reason="Chạy trên IE thật: đặt ROOKIE_REAL_IE=1")

LOGIN = b"""<html><head><title>RookieE2E Login</title></head><body onload="document.getElementById('txtUser').focus()">
<form action="/role" method="post"><table><tr><td id="lblUser">User name</td><td><input type="text" id="txtUser" name="txtUser"></td></tr>
<tr><td>Password</td><td><input type="password" id="txtPw" name="txtPw"></td></tr></table>
<input type="submit" id="btnLogin" value="Login"></form></body></html>"""
TOP = b"""<html><head><title>RookieE2E Role</title></head><body>
<iframe name="__gwt_historyFrame" src="/blank" style="width:0;height:0"></iframe>
<iframe name="desktopFrame" src="/desktop" style="width:100%;height:500px"></iframe></body></html>"""
DESKTOP = (b'<html><frameset rows="30,*,30,0,0"><frame name="toolbar" src="/blank"><frame name="rtop" src="/blank">'
           b'<frame name="rbottom" src="/blank"><frame name="rhidden" src="/rhidden"><frame name="fiApplet" src="/blank"></frameset></html>')
RHIDDEN = b"""<html><body><form><select id="cboLanguages" name="cboLanguages" onchange="location.href='/rhidden2'"><option value="en">EN</option><option value="vi">VI</option></select>
<select id="currentRole" name="currentRole"><option value="gdv">GDV</option><option value="ksv">KSV</option></select>
<script>setTimeout(function(){document.getElementById('currentRole').value='ksv';},500);</script>
<button id="btnSelect" type="button" onclick="location.href='/blank'">OK</button></form></body></html>"""
RHIDDEN2 = RHIDDEN.replace(b" onchange=\"location.href='/rhidden2'\"", b"")  # the same screen after the reload
BLANK = b"<html><body><button id=\"btnLogoff\" type=\"button\" onclick=\"top.location.href='/'\">LOGOFF</button></body></html>"
SEARCH_TOP = (b'<html><head><title>RookieE2E Search</title></head><frameset rows="40,*"><frame name="rtop" src="/clock">'
              b'<frame name="main" src="/searchform"></frameset></html>')
CLOCK = b"""<html><body><div id="clk" class="status"></div>
<script>setInterval(function(){document.getElementById('clk').innerHTML = 'time ' + new Date().getTime();}, 150);</script></body></html>"""
SEARCH_FORM = b"""<html><body><table><tr><td>So tai khoan:</td><td><input type="text" id="txtAcct"></td></tr></table>
<input type="text" id="txtCopy" name="txtCopy"><input type="button" id="btnFind" value="TIM KIEM" onclick="find()"><div id="result"></div>
<script>function find(){
 var v = document.getElementById('txtAcct').value;
 if (v == 'NONE') { document.getElementById('result').innerHTML = '<div class="errMsg">Khong tim thay khach hang</div>'; return; }
 document.getElementById('result').innerHTML = '<table id="grid"><tr><th>So TK</th><th>Loai</th><th>So du</th></tr><tr><td>' + v + '</td><td>DDA</td><td>5.000</td></tr><tr><td>9002</td><td>SAV</td><td>7.000</td></tr></table>';
}</script></body></html>"""
AJAX = b"""<html><head><title>RookieE2E Ajax</title></head><body>
<input type="button" id="btnNative" value="native" onclick="callNative()">
<input type="button" id="btnActive" value="active" onclick="callActive()">
<input type="button" id="btnFail" value="fail" onclick="callFail()">
<input type="button" id="btnPw" value="pw" onclick="callPw()">
<div id="out"></div>
<script>
function show(t) { document.getElementById('out').innerHTML = t; }
function callNative() {
  var x = new XMLHttpRequest();
  x.open('POST', '/api/find?acct=0123456789', true);
  x.setRequestHeader('Content-Type', 'application/json');
  x.onreadystatechange = function () { if (x.readyState == 4) { show('native ' + x.status + ' ' + x.responseText); } };
  x.send('{"account":"0123456789"}');
}
function callActive() {
  var x = new ActiveXObject('Microsoft.XMLHTTP');
  x.open('GET', '/api/ping', false);
  x.send(null);
  show('active ' + x.status + ' ' + x.responseText);
}
function callPw() {
  var x = new XMLHttpRequest();
  x.open('POST', '/api/find?login=1', true);
  x.onreadystatechange = function () { if (x.readyState == 4) { show('pw ' + x.status); } };
  x.send('{"user":"teller01","password":"S3cretPw","pin":"4321"}&pwd=Another1&keep=yes');
}
function callFail() {
  var x = new XMLHttpRequest();
  x.open('GET', '/api/fail', true);
  x.onreadystatechange = function () { if (x.readyState == 4) { show('fail ' + x.status); } };
  x.send(null);
}
</script></body></html>"""
FORM = b"""<html><head><title>RookieE2E Form</title></head><body>
<table><tr><td>So tai khoan:</td><td><input type="text" id="txtAcct" name="txtAcct"></td></tr>
<tr><td>Loai:</td><td><select id="cboKind" name="cboKind"><option value="d">DDA</option><option value="s">SAV</option></select></td></tr>
<tr><td>Mat khau:</td><td><input type="password" id="txtPw" name="txtPw"></td></tr>
<tr><td>Khoa:</td><td><input type="text" id="txtLocked" disabled value="x"></td></tr></table>
<form id="f1" onsubmit="document.getElementById('res').innerHTML = 'submitted ' + document.getElementById('txtQ').value; return false;">
<input type="text" id="txtQ" name="txtQ"><input type="submit" id="btnQ" value="Gui"></form>
<input type="button" id="btnGo" value="Chay" onclick="document.getElementById('res').innerHTML = 'went ' + document.getElementById('txtAcct').value + ' ' + document.getElementById('cboKind').value;">
<input type="button" id="dup" value="A"><input type="button" id="dup" value="B">
<input type="text" id="txtCif" onkeyup="document.getElementById('btnFind').disabled = this.value.length == 0;">
<input type="button" id="btnFind" value="Tim" disabled onclick="document.getElementById('res').innerHTML = 'found ' + document.getElementById('txtCif').value;">
<input type="text" id="txtCif2" onblur="document.getElementById('btnFind2').disabled = false;">
<input type="button" id="btnFind2" value="Tim2" disabled onclick="document.getElementById('res').innerHTML = 'found2';">
<div id="res"></div><span id="lblNote">Ghi chu cua trang</span>
<script>document.getElementById('cboKind').onchange = function () { document.getElementById('res').innerHTML = 'kind changed'; };</script>
</body></html>"""
AJAXNAV = b"""<html><head><title>RookieE2E Nav</title></head><body>
<input type="button" id="btnNav" value="nav" onclick="location.href='/ajax2'"></body></html>"""
AJAX2 = AJAX.replace(b"</script></body>", b"callNative();</script></body>")       # the next screen asks the server as soon as it loads
OPENER = b"""<html><head><title>RookieE2E Opener</title></head><body>
<input type="button" id="btnOpen" value="open" onclick="window.open('/ajaxtab')"></body></html>"""
AJAXTAB = AJAX.replace(b"RookieE2E Ajax", b"RookieE2E Tab2")
SLOW = b"<html><head><title>RookieE2E Slow</title></head><body><div>first part</div><script src=\"/slow.js\"></script><input type=\"text\" id=\"txtLate\"></body></html>"
# A link of the GWT kind (href="javascript:..."): IE fires beforeunload for it although the page stays. What the link runs records
# the cookies the page's next request would carry.
JSLINK = (b'<html><head><title>RookieE2E Link</title></head><body><input type="text" id="txtQ" name="txtQ">'
          b'<a id="lnkFind" href="javascript:window.__ck=String(document.cookie);void(0)">TIM KIEM</a></body></html>')
CIFAPP = b"""<html><head><title>RookieE2E Cif</title></head><body>
<input type="button" id="btnOpen" value="Xem" onclick="openScreen()">
<input type="text" id="txtCif" name="txtCif">
<input type="button" id="btnFind" value="Search" onclick="find()">
<form id="fDetail" method="post" action="/api/detail" target="resf"><input type="hidden" id="kh" name="kh" value=""><input type="submit" id="btnDetail" value="Xem chi tiet"></form>
<div id="res"></div><iframe name="resf" id="resf" src="/blank"></iframe>
<script>
var tok = "";
function xhr() { return window.XMLHttpRequest ? new XMLHttpRequest() : new ActiveXObject('Msxml2.XMLHTTP'); }
function openScreen() { var x = xhr(); x.open('GET', '/api/init', true); x.onreadystatechange = function () { if (x.readyState == 4) { tok = x.responseText.split('"tok":"')[1].split('"')[0]; } }; x.send(null); }
function find() {
  var x = xhr(); x.open('POST', '/api/cif2', true); x.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
  x.onreadystatechange = function () { if (x.readyState == 4) { document.getElementById('res').innerHTML = x.responseText; document.getElementById('kh').value = x.responseText.split('"kh":"')[1].split('"')[0]; } };
  x.send('cif=' + document.getElementById('txtCif').value + '&xsrf=' + tok);
}
</script></body></html>"""
SESSAPP = b"""<html><head><title>RookieE2E Sess</title></head><body>
<form id="fLogin" onsubmit="login(null); return false;"><input type="text" id="txtUser" name="txtUser"><input type="password" id="txtPw" name="txtPw"><input type="submit" id="btnLogin" value="Login"></form>
<input type="button" id="btnRole" value="Role" onclick="document.getElementById('res').innerHTML = 'role'">
<input type="button" id="btnOpen" value="Xem" onclick="openScreen()">
<input type="text" id="txtCif" name="txtCif">
<input type="button" id="btnFind" value="Search" onclick="find()">
<div id="res"></div>
<script>
var sid = "", tok = "";
function xhr() { return window.XMLHttpRequest ? new XMLHttpRequest() : new ActiveXObject('Msxml2.XMLHTTP'); }
function login(then) { var x = xhr(); x.open('POST', '/api/login', true); x.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
  x.onreadystatechange = function () { if (x.readyState == 4) { sid = x.responseText.split('"sid":"')[1].split('"')[0]; if (then) { then(); } } }; x.send('user=teller01'); }
function openScreen() { var x = xhr(); x.open('POST', '/api/open', true); x.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
  x.onreadystatechange = function () { if (x.readyState == 4 && x.status == 200) { tok = x.responseText.split('"tok":"')[1].split('"')[0]; } }; x.send('sid=' + sid + '&screen=1'); }
function again() { login(openScreen); }   // the session ended and the page signed in again by itself, then opened its screen
function find() { var x = xhr(); x.open('POST', '/api/s2', true); x.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
  x.onreadystatechange = function () { if (x.readyState == 4) { document.getElementById('res').innerHTML = x.responseText; } };
  x.send('cif=' + document.getElementById('txtCif').value + '&tok=' + tok); }
</script></body></html>"""
TOKAPP = b"""<html><head><title>RookieE2E Tok</title></head><body>
<input type="text" id="txtCif" name="txtCif">
<input type="button" id="btnFind" value="Search" onclick="find()">
<div id="res"></div>
<script>
function xhr() { return window.XMLHttpRequest ? new XMLHttpRequest() : new ActiveXObject('Msxml2.XMLHTTP'); }
// two calls for one service, as TouchPoint does: a token service first (a fresh bearer token each time), then the service with it
function find() {
  var cif = document.getElementById('txtCif').value;
  var t = xhr(); t.open('POST', '/api/gettoken?method=getToken&claims=QWJjfHxkZWZ8fA==', true);
  t.onreadystatechange = function () {
    if (t.readyState != 4) { return; }
    var jwt = t.responseText.replace(/^\\s+|\\s+$/g, '');
    var x = xhr(); x.open('POST', '/api/svc', true);
    x.setRequestHeader('Authorization', 'Bearer ' + jwt);
    x.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded;text/xml;charset=utf-8');
    x.setRequestHeader('MACHINE_NAME', 'PC7');
    x.onreadystatechange = function () { if (x.readyState == 4) { document.getElementById('res').innerHTML = x.status + ' ' + x.responseText; } };
    x.send('methodName=find&xml=' + cif);
  };
  t.send('');
}
</script></body></html>"""
# A report exported as a PDF, delivered the three ways a site may: (a) a request of the page, (b) a form sent to the same window, (c) window.open of the file.
# The label is «Xuất báo cáo» (written as entities: this file keeps the pages in ASCII bytes).
PDF_BYTES = b"%PDF-1.4\nRKPDFMARK 0123456789 NGUYEN VAN A\n" + bytes(range(256)) * 8 + b"\r\n\x00\xff\r%%EOF"
EXPORT = b"""<html><head><title>RookieE2E Export</title></head><body>
<table><tr><td>Tu ngay:</td><td><input type="text" id="txtFrom" name="txtFrom"></td></tr></table>
<input type="button" id="btnXhr" value="Xu&#7845;t b&aacute;o c&aacute;o" onclick="exportXhr()">
<form id="fExp" method="post" action="/api/exportform"><input type="hidden" name="kind" value="pdf"><input type="text" id="txtFrom2" name="txtFrom2">
<input type="submit" id="btnForm" value="Xu&#7845;t b&aacute;o c&aacute;o"></form>
<input type="button" id="btnWin" value="Xu&#7845;t b&aacute;o c&aacute;o" onclick="exportWin()">
<div id="res"></div>
<script>
function xhr() { return window.XMLHttpRequest ? new XMLHttpRequest() : new ActiveXObject('Msxml2.XMLHTTP'); }
function exportXhr() {
  var x = xhr(); x.open('POST', '/api/export', true); x.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
  x.onreadystatechange = function () { if (x.readyState == 4) { document.getElementById('res').innerHTML = 'exported ' + x.status; } };
  x.send('from=' + document.getElementById('txtFrom').value + '&fmt=pdf');
}
function exportWin() { window.open('/api/exportpdf?from=' + document.getElementById('txtFrom').value + '&fmt=pdf', '_blank'); }
</script></body></html>"""
# A button whose own script makes the page wait (a dialog): here alert is a stand-in that makes a request, so the order of the lines shows whether the press was recorded first.
WAITING = b"""<html><head><title>RookieE2E Waiting</title></head><body>
<table><tr><td><input type="checkbox" id="chkRow"></td><td>Row 1</td></tr></table>
<input type="button" id="btnWait" value="In b&aacute;o n&#7907;/c&oacute;" onclick="waitCall()">
<script>
window.alert = function () {
  var x = window.XMLHttpRequest ? new XMLHttpRequest() : new ActiveXObject('Msxml2.XMLHTTP');
  x.open('GET', '/api/mark', false); x.send('');
};
function waitCall() { alert('x'); }
</script></body></html>"""
# The page a dialog shows (here a modeless dialog opened by a host program: IE would not open one from a hidden window): it asks for a file a moment after it is loaded.
DLGVIEWER = b"""<html><head><title>RookieE2E Dialog</title></head><body>viewing<script>
window.setTimeout(function () {
  var x = window.XMLHttpRequest ? new XMLHttpRequest() : new ActiveXObject('Msxml2.XMLHTTP'); x.open('GET', '/api/exportpdf?from=dlg&fmt=pdf', true); x.send('');
}, 3000);
window.setTimeout(function () { window.close(); }, 9000);</script></body></html>"""
# the page calls showModalDialog: for a report and for its own message box (the stand-in does nothing; the recorder's hook around it reports the address)
DLGCALL = b"""<html><head><title>RookieE2E Dlgcall</title></head><body>
<input type="button" id="btnRpt" value="rpt" onclick="showModalDialog('/viewReport.jsp?x=1', null, 'dialogWidth:300px')">
<input type="button" id="btnMsg" value="msg" onclick="showModalDialog('/touchpoint/utilities/dlgMessageBox.jsp?language=vi', null, 'dialogWidth:300px')">
<script>window.showModalDialog = function () { return null; };</script></body></html>"""
PAGES = {"/dlgcall": DLGCALL, "/touchpoint/utilities/dlgMessageBox.jsp": DLGVIEWER, "/dlgviewer": DLGVIEWER, "/waiting": WAITING, "/export": EXPORT, "/tokapp": TOKAPP, "/sessapp": SESSAPP, "/cifapp": CIFAPP, "/jslink": JSLINK, "/slowpage": SLOW, "/opener": OPENER, "/ajaxtab": AJAXTAB, "/ajaxnav": AJAXNAV, "/ajax2": AJAX2, "/form": FORM, "/ajax": AJAX, "/search": SEARCH_TOP, "/clock": CLOCK, "/searchform": SEARCH_FORM, "/desktop": DESKTOP, "/rhidden": RHIDDEN, "/rhidden2": RHIDDEN2, "/blank": BLANK}


class Handler(BaseHTTPRequestHandler):
    def _send(self, body):
        self.send_response(200); self.send_header("Content-Type", "text/html")
        self.send_header("X-UA-Compatible", "IE=" + os.environ.get("RK_DOCMODE", "5"))   # document mode 5 like TouchPoint: no addEventListener, attachEvent only
        self.end_headers(); self.wfile.write(body)

    token, seen = "", []
    sid = ""
    jwt, jwts = "", 0

    def do_GET(self):
        if self.path.startswith("/api/init"):     # Gate 8: the screen opening gives a new anti-forgery token each time
            Handler.token = "T%d" % int(time.time() * 1000)
            self._json(('{"tok":"%s"}' % Handler.token).encode("utf-8"))
            return
        if self.path.startswith("/api/fail"):
            self.send_response(500); self.send_header("Content-Type", "text/plain"); self.end_headers(); self.wfile.write(b"server error")
            return
        if self.path.startswith("/api/mark"):     # the page tells what its recorder held at the moment its script began to wait
            Handler.seen.append(self.path)
            self._json(b"{}")
            return
        if self.path.startswith("/api/ping"):
            self._json(b'{"pong":true,"name":"NGUYEN VAN A"}')
            return
        if self.path.startswith("/api/exportpdf"):    # (c) a file url opened by window.open
            Handler.seen.append("win:" + self.path.split("from=", 1)[-1].split("&")[0])
            self._pdf()
            return
        if self.path.startswith("/slow.js"):      # a script the page waits for: until it comes, the document is not "complete"
            time.sleep(3.5)
            self.send_response(200); self.send_header("Content-Type", "application/javascript"); self.end_headers(); self.wfile.write(b"window.__slow = 1;")
            return
        if self.path.startswith("/ajax2"):
            time.sleep(2.5)     # a slow next screen: the tab is between two pages for a while
        self._send(PAGES.get(self.path, LOGIN))

    def _pdf(self, attachment=False):
        self.send_response(200); self.send_header("Content-Type", "application/pdf"); self.send_header("Content-Length", str(len(PDF_BYTES)))
        if attachment:
            self.send_header("Content-Disposition", 'attachment; filename="BaoCao_20261119.pdf"')
        self.end_headers(); self.wfile.write(PDF_BYTES)

    def _json(self, body):
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        if self.path.startswith("/api/export"):       # (a) a request of the page, (b) a form posted: both answer the PDF
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")
            Handler.seen.append(("form:" if self.path.startswith("/api/exportform") else "xhr:") + body)
            self._pdf(attachment=self.path.startswith("/api/exportform"))
            return
        if self.path.startswith("/api/gettoken"):   # a bare token, fresh each time; only the newest one is accepted by the service
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            Handler.jwts += 1
            Handler.jwt = "eyJhbGciOiJIUzI1NiJ9.eyJleHAiOiI%d.c2ln%d" % (int(time.time() * 1000), Handler.jwts)
            self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers(); self.wfile.write(("\n" + Handler.jwt + "\n").encode("utf-8"))
            return
        if self.path.startswith("/api/svc"):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")
            if self.headers.get("Authorization") != "Bearer " + Handler.jwt or self.headers.get("MACHINE_NAME") != "PC7":
                self.send_response(401); self.end_headers(); return
            Handler.seen.append(body.split("xml=", 1)[-1])
            self._json(('{"ok":true,"cif":"%s"}' % body.split("xml=", 1)[-1]).encode("utf-8"))
            return
        if self.path.startswith("/api/login"):    # a session id for the page; the next calls must carry the newest one
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            Handler.sid = "SID%d" % int(time.time() * 1000)
            self._json(('{"sid":"%s"}' % Handler.sid).encode("utf-8"))
            return
        if self.path.startswith("/api/open"):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")
            Handler.seen.append("open:" + body.split("&")[0].split("=", 1)[-1])
            if body.split("&")[0] != "sid=" + Handler.sid:
                self.send_response(403); self.end_headers(); return
            Handler.token = "T%d" % int(time.time() * 1000)
            self._json(('{"tok":"%s"}' % Handler.token).encode("utf-8"))
            return
        if self.path.startswith("/api/s2"):
            body = dict(x.split("=", 1) for x in self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8").split("&") if "=" in x)
            if body.get("tok") != Handler.token:
                self.send_response(403); self.end_headers(); return
            Handler.seen.append(body.get("cif", ""))
            self._json(('{"kh":"KX%s"}' % body.get("cif", "")).encode("utf-8"))
            return
        if self.path.startswith("/api/cif2"):     # Gate 8: needs the token the screen opening gave; answers a customer number of its own
            body = dict(x.split("=", 1) for x in self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8").split("&") if "=" in x)
            if body.get("xsrf") != Handler.token:
                self.send_response(403); self.end_headers(); return
            cif = body.get("cif", "")
            Handler.seen.append(cif)
            self._json(('{"kh":"KX%d","name":"KHACH %s"}' % (sum(int(c) for c in cif if c.isdigit()) * 137 + 7, cif)).encode("utf-8"))
            return
        if self.path.startswith("/api/detail"):   # a form posted into the frame: the customer number the search gave
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")
            Handler.seen.append(body)
            self._send(("<html><body><table><tr><td>Ma KH</td><td>%s</td></tr></table></body></html>" % body.split("=", 1)[-1]).encode("utf-8"))
            return
        if self.path.startswith("/api/cif"):      # Gate 7: echoes the customer id, the page's session cookie and a header the page set
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")
            if self.headers.get("X-Test") != "1":
                self.send_response(403); self.end_headers(); return
            cookie = self.headers.get("Cookie") or ""
            self._json(('{"cif":"%s","name":"KHACH %s","cookie":"%s"}' % (body.split("=", 1)[-1], body.split("=", 1)[-1], cookie)).encode("utf-8"))
            return
        if self.path.startswith("/api/find"):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            self._json(b'{"name":"NGUYEN VAN A","balance":"5.000.000","account":"0123456789"}')
            return
        self._send(TOP)

    def log_message(self, *args):
        pass


def drive(action: str, match: str = "RookieE2E") -> str:
    done = subprocess.run(["powershell.exe", "-NoProfile", "-Sta", "-ExecutionPolicy", "Bypass", "-File", DRIVE, action, match],
                          capture_output=True, text=True, timeout=60)
    return done.stdout.strip()


@contextlib.contextmanager
def real_ie(path="/"):
    """A local site and an own IE window on it, a real bridge; everything is closed after, whatever happens."""
    for _ in range(10):  # windows of this test left by an earlier run that was stopped half way; only those, never another window
        if drive("quit") == "no window":
            break
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    opened = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                             "try { $ie = New-Object -ComObject InternetExplorer.Application } catch { exit 3 }; $ie.Visible = $false; "
                             f"$ie.Navigate2('http://127.0.0.1:{port}{path}'); $t = 0; while ($ie.Busy -and $t -lt 100) {{ Start-Sleep -Milliseconds 200; $t++ }}; Start-Sleep 2"],
                            timeout=60)
    if opened.returncode == 3:
        server.shutdown()
        pytest.skip("Máy này không có Internet Explorer dùng được qua COM")
    # a hard limit: whatever happens, the window of this test is closed after 150 seconds
    watchdog = threading.Timer(150, lambda: drive("quit"))
    watchdog.daemon = True
    watchdog.start()
    bridge = IeBridge().open()
    try:
        bridge.test_port = port
        yield bridge
    finally:
        watchdog.cancel()
        bridge.close()
        drive("quit")
        server.shutdown()


def start_session(bridge, requests: bool = True, diag: str = "") -> IeSession:
    tab = None
    for _ in range(25):  # the window may still be loading its title
        tab = next((t for t in bridge.tabs() if "RookieE2E" in t["title"]), None)
        if tab:
            break
        time.sleep(0.4)
    assert tab, "no IE window of this test"
    session = IeSession(bridge, tab["id"], "TouchPoint", requests=requests, diag=diag)
    session.start()
    time.sleep(1.0)
    return session


@pytest.mark.parametrize("how", ["click", "enter"])
def test_sign_in_then_role_screen_in_nested_frames_is_recorded_on_a_real_ie_window(how):
    """Sign in by clicking the button. Enter in the password field is also recorded (seen on a real keyboard); COM cannot press a real
    Enter into the page (fireEvent does not reach the recorder), so that way is not simulated here."""
    for attempt in (1, 2):  # Windows sometimes refuses to bring the window to the front: no focus events, and the run says nothing
        try:
            return _login_then_role(how)
        except AssertionError:
            if attempt == 2:
                raise


def _login_then_role(how):
    send = ("click-login", 3.0) if how == "click" else ("enter-pw", 3.0)
    with real_ie() as bridge:
        session = start_session(bridge)
        for action, wait in (("click-label", 0.3), ("type-user", 0.5), ("type-pw", 0.5), send, ("f-role-lang", 1.5), ("f-ok", 1.5)):
            drive(action)
            time.sleep(wait)
        events = session.stop()
    steps = [(e["type"], e["target"]["selectors"][0]) for e in events]
    why = (session.error, session.notes[-1:], [(r["kind"], r.get("id")) for r in session.raw])
    sent = ("click", "frame=top|id=btnLogin") if how == "click" else ("submit", "frame=top|id=txtPw")
    assert steps == [
        ("input", "frame=top|id=txtUser"),                         # typed in the field that already had the cursor
        sent,                                                      # the way the login was sent is not lost with the page
        ("select", "frame=desktopFrame/rhidden|id=cboLanguages"),  # the role screen is inside nested frames
        ("click", "frame=desktopFrame/rhidden|id=btnSelect"),
    ], why
    assert "TOPSECRET" not in str(events)  # the value of the password is never read
    # the trace keeps what each choice list showed before the teller touched it, also for the one never touched
    from rookie_agent.ie.trace import TraceBuilder
    builder = TraceBuilder("TouchPoint", "t-real")
    builder.add_session("s-1", session.raw)
    trace = builder.build()
    by_id = {el["selectors"][0].split("|id=")[-1]: el_id for el_id, el in trace["elements"].items() if "|id=" in el["selectors"][0]}
    initial = trace["sessions"][0]["initial"]
    assert initial[by_id["currentRole"]] == {"value": "ksv", "text": "KSV"}   # the page's script set it after onload; never touched
    assert initial[by_id["cboLanguages"]]["value"] == "en"                      # what it showed before the teller changed it
    assert trace["elements"][by_id["currentRole"]]["options"] == [{"value": "gdv", "text": "GDV"}, {"value": "ksv", "text": "KSV"}]
    change = next(e for e in trace["sessions"][0]["events"] if e["kind"] == "change" and e["el_id"] == by_id["cboLanguages"])
    assert (change["option_value"], change["value_before"]) == ("vi", "EN")
    uids = [r["uid"] for r in session.raw]
    assert len(uids) == len(set(uids)) and len(uids) >= 8, uids  # every line has its own id, and none arrived twice


def test_a_line_left_behind_by_the_last_recording_is_not_in_the_next_one():
    """Logoff sends the whole page away right before Dung ghi: its line can stay in the cookie. The next recording must not get it."""
    with real_ie() as bridge:
        first = start_session(bridge)
        first.stop()
        drive("plant-stale")                    # nothing records now: the line waits in the cookie, as the teller's Logoff click did
        second = start_session(bridge)
        for action, wait in (("type-user", 0.5), ("click-label", 0.5)):
            drive(action)
            time.sleep(wait)
        events = second.stop()
    assert "staleBtn" not in str(events) and [e["type"] for e in events] == ["input"], events


def test_the_tab_keeps_its_id_when_the_page_changes_its_title_after_sign_in():
    """The screen list must follow the page: the same tab, a new title. (The old list kept the sign in title until Tai lai.)"""
    with real_ie() as bridge:
        before = next(t for t in bridge.tabs() if "RookieE2E" in t["title"])
        for action, wait in (("type-user", 0.5), ("click-login", 3.0)):
            drive(action)
            time.sleep(wait)
        after = [t for t in bridge.tabs() if "RookieE2E" in t["title"]]
    assert [t["id"] for t in after] == [before["id"]]
    assert "Login" in before["title"] and "Role" in after[0]["title"]


def _search(account):
    """Type an account number in the form, press the search button, give the screen time to settle."""
    with real_ie("/search") as bridge:
        session = start_session(bridge)
        os.environ["RK_VALUE"] = account
        for action, wait in (("s-acct", 0.5), ("s-find", 3.0)):
            drive(action)
            time.sleep(wait)
        events = session.stop()
    return session, events


def test_the_agent_reads_the_table_the_search_shows_and_the_clock_is_not_the_result():
    session, events = _search("0123456789")
    after = [s for s in session.seen if s["after"] and s["after"]["id"] == "btnFind"]
    assert after, [(s["after"], s["summary"]) for s in session.seen]
    snap = next(x for x in after if x["changed"])                               # the look that saw the result (a later one sees no change)
    main = next(f for f in snap["frames"] if f["frame"] == "main")
    table = main["tables"][0]
    assert table["headers"] == ["So TK", "Loai", "So du"] and table["row_count"] == 2
    assert table["rows"][0] == ["0123456789", "DDA", "5.000"]                    # the full values, in memory
    assert main["fields"] == [{"label": "So tai khoan", "value": "0123456789"}]  # a label-value pair of the form
    assert snap["region"] == ["main"]                                            # the clock in rtop changes by itself: not the result
    kinds = {c["kind"] for c in snap["changed"]}
    assert "table" in kinds and kinds <= {"table", "field"}                      # the table (and maybe the account number just typed)
    assert not any(c["frame"] == "rtop" for c in snap["changed"])                # the clock is never a change
    assert [e["type"] for e in events] == ["input", "click"]


def test_an_error_message_on_the_screen_is_read_as_an_error():
    session, _ = _search("NONE")
    snap = next(x for x in session.seen if x["after"] and x["after"]["id"] == "btnFind" and x["changed"])
    main = next(f for f in snap["frames"] if f["frame"] == "main")
    assert main["tables"] == [] and main["messages"] == [{"level": "error", "text": "Khong tim thay khach hang"}]


def _requests(actions):
    with real_ie("/ajax") as bridge:
        session = start_session(bridge)
        for action, wait in actions:
            drive(action)
            time.sleep(wait)
        shown = None
        os.environ["RK_JS"] = "window.__res = document.getElementById('out').innerHTML;"
        shown = drive("js")
        events = session.stop()
    return session, events, shown


def test_a_request_and_its_response_made_with_xmlhttprequest_are_tracked_and_the_page_still_works():
    session, events, shown = _requests([("a-native", 2.0)])
    assert "native 200" in shown and "NGUYEN VAN A" in shown                         # the page got its answer: nothing was broken
    [req] = [r for r in session.requests if r["method"] == "POST"]
    assert req["status"] == 200 and req["url"].startswith("/api/find") and "acct=0123456789" in req["url"]
    assert '"account":"0123456789"' in req["req"] and "NGUYEN VAN A" in req["res"]    # the full request and response, in memory
    assert req["ms"] >= 0 and req["after"]["id"] == "btnNative"


def test_a_request_made_with_activex_xmlhttp_is_tracked_too():
    session, _, shown = _requests([("a-active", 1.5)])
    assert "active 200" in shown and "pong" in shown
    [req] = session.requests
    assert req["method"] == "GET" and req["url"] == "/api/ping" and req["status"] == 200 and "pong" in req["res"]


def test_a_failed_request_is_tracked_with_its_status():
    session, _, shown = _requests([("a-fail", 2.0)])
    assert "fail 500" in shown
    [req] = session.requests
    assert req["status"] == 500 and req["res"] == "server error"


def test_requests_leave_nothing_in_the_trace_but_their_shape():
    session, _, _ = _requests([("a-native", 2.0)])
    from rookie_agent.ie.trace import TraceBuilder
    builder = TraceBuilder("TouchPoint", "t-ajax")
    builder.add_session("s-1", session.raw)
    builder.add_requests("s-1", session.requests)
    trace = builder.build()
    text = json.dumps(trace, ensure_ascii=False)
    for secret in ("0123456789", "NGUYEN", "5.000.000"):
        assert secret not in text
    [meta] = trace["sessions"][0]["requests"]
    assert meta["method"] == "POST" and meta["path"] == "/api/find" and meta["status"] == 200


# ---- the runner's lowest layer: find an element by the selectors of a step and act on it, in document mode 5 ----

def _acts(steps):
    """Run (op, selectors, value) triples against the form page; returns the answers and the text the page shows."""
    from rookie_agent.ie.bridge import IeBridge  # noqa: F401  (the bridge of real_ie is the same class)

    answers = []
    with real_ie("/form") as bridge:
        tab = next(t for t in bridge.tabs() if "RookieE2E" in t["title"])
        bridge.bind(tab["id"])
        for op, selectors, value in steps:
            answers.append(bridge.act(op, selectors, value))
        os.environ["RK_JS"] = "window.__res = document.getElementById('res').innerHTML + '|' + document.getElementById('txtAcct').value;"
        shown = drive("js")
    return answers, shown


def test_the_runner_fills_selects_clicks_and_reads_in_the_page_and_the_page_reacts():
    answers, shown = _acts([
        ("fill", ["frame=top|id=txtAcct", "frame=top|label=So tai khoan"], "0123456789"),
        ("select", ["frame=top|id=cboKind"], "s"),
        ("read", ["frame=top|id=cboKind"], ""),
        ("click", ["frame=top|id=btnGo"], ""),
        ("read", ["frame=top|id=lblNote"], ""),
    ])
    assert answers[0]["ok"] and answers[0]["value"] == "0123456789"        # filled, and read back from the field
    assert answers[1]["ok"] and answers[1]["value"] == "s" and answers[1]["text"] == "SAV"
    assert answers[2]["value"] == "SAV"                                      # reading a list gives what the teller sees
    assert answers[3]["ok"] and answers[4]["value"] == "Ghi chu cua trang"
    assert shown == "went 0123456789 s|0123456789"                            # the page's own handlers ran


def test_the_runner_chooses_a_list_entry_by_its_value_and_the_page_hears_the_change():
    answers, shown = _acts([("select", ["frame=top|id=cboKind"], "s")])
    assert answers[0]["ok"] and shown.startswith("kind changed")


def test_the_runner_never_guesses_and_never_types_a_password():
    answers, _ = _acts([
        ("click", ["frame=top|id=nothere"], ""),
        ("click", ["frame=top|id=dup"], ""),                     # two elements with the same id: nothing is clicked
        ("fill", ["frame=top|id=txtPw"], "x"),                   # the password is typed by the teller, never by the agent
        ("fill", ["frame=top|id=txtLocked"], "x"),
        ("select", ["frame=top|id=cboKind"], "zzz"),
    ])
    assert [a["error"] for a in answers] == ["not_found", "ambiguous", "secret", "disabled", "no_option"]


def test_a_button_the_page_unlocks_on_typing_or_leaving_the_field_is_unlocked_by_the_fill():
    """TouchPoint keeps «Tìm kiếm» locked until it hears the keys (or the field is left): a fill must sound like a person typing."""
    answers, shown = _acts([("fill", ["frame=top|id=txtCif"], "123456"), ("click", ["frame=top|id=btnFind"], ""),
                            ("fill", ["frame=top|id=txtCif2"], "9"), ("click", ["frame=top|id=btnFind2"], "")])
    assert answers[1]["ok"] and answers[3]["ok"], answers
    assert shown.startswith("found2")


def test_enter_in_a_field_sends_its_form_the_way_the_browser_does():
    answers, shown = _acts([("fill", ["frame=top|id=txtQ"], "abc"), ("submit", ["frame=top|id=txtQ"], "")])
    assert answers[1]["ok"] and shown.startswith("submitted abc")


# ---- task 6.1: the page changed (an id renamed, a look-alike field added): the evidence decides, never a guess ----

def _driver_fill(selectors, js_before=""):
    from rookie_agent.ie.driver import IeDriver
    from rookie_agent.runner import NeedsHelp

    with real_ie("/form") as bridge:
        tab = next(t for t in bridge.tabs() if "RookieE2E" in t["title"])
        if js_before:
            os.environ["RK_JS"] = js_before + " window.__res = 'x';"
            drive("js")
        driver = IeDriver(bridge, tab["id"])
        try:
            driver.fill(selectors, "0123456789")
            outcome = "filled"
        except NeedsHelp as stopped:
            outcome = stopped.code
        os.environ["RK_JS"] = "window.__res = document.getElementById('txtAcct') ? document.getElementById('txtAcct').value : '';"
        return outcome, drive("js")


def test_a_renamed_id_is_still_found_by_its_label_and_place():
    outcome, value = _driver_fill(["frame=top|id=txtAcctOld", "frame=top|label=So tai khoan", "frame=top|input[0]"])
    assert (outcome, value) == ("filled", "0123456789")


def test_two_fields_with_the_same_label_stop_the_run_to_ask():
    clone = ("var row = document.getElementById('txtAcct').parentNode.parentNode; var copy = row.cloneNode(true);"
             " copy.getElementsByTagName('input')[0].id = 'txtAcct2'; copy.getElementsByTagName('input')[0].name = 'txtAcct2';"
             " row.parentNode.insertBefore(copy, row);")   # the new look-alike comes first: the learned place now points at it
    outcome, value = _driver_fill(["frame=top|id=txtAcctOld", "frame=top|label=So tai khoan", "frame=top|input[0]"], clone)
    assert outcome in ("low_confidence", "ambiguous") and value == ""


def test_look_alikes_are_suggested_and_coloured_without_touching_the_page():
    from rookie_agent.ie.driver import IeDriver

    with real_ie("/form") as bridge:
        tab = next(t for t in bridge.tabs() if "RookieE2E" in t["title"])
        driver = IeDriver(bridge, tab["id"])
        found = driver.suggest(["frame=top|id=txtAcctOld", "frame=top|label=So tai khoan"], "field")
        driver.mark(found)
        os.environ["RK_JS"] = "var e = document.getElementById('txtAcct'); window.__res = e.runtimeStyle.backgroundColor + '|' + e.value + '|' + e.style.cssText;"
        coloured = drive("js")
        driver.unmark()
        cleared = drive("js")
    assert found and found[0]["label"] == "So tai khoan" and "frame=top|id=txtAcct" in found[0]["selectors"]
    assert coloured.split("|")[0] in ("#ffd54f", "rgb(255, 213, 79)") and coloured.endswith("||") and cleared == "||"           # coloured, nothing typed, the page's own style untouched


def test_the_fingerprint_of_a_screen_has_its_fields_and_changes_when_a_field_is_added():
    from rookie_agent.ie import locate
    from rookie_agent.ie.driver import IeDriver

    with real_ie("/form") as bridge:
        tab = next(t for t in bridge.tabs() if "RookieE2E" in t["title"])
        driver = IeDriver(bridge, tab["id"])
        os.environ["RK_JS"] = "document.getElementById('txtAcct').value = '0123456789'; window.__res = 'x';"
        drive("js")
        before = driver.fingerprint()
        os.environ["RK_JS"] = ("var t = document.getElementsByTagName('table')[0]; for (var i = 0; i < 6; i++) { var r = t.insertRow(-1);"
                               " r.insertCell(-1).innerText = 'Moi ' + i; r.insertCell(-1).innerHTML = '<input type=text>'; } window.__res = 'x';")
        drive("js")
        after = driver.fingerprint()
    assert "top|input:text|So tai khoan" in before and "0123456789" not in "".join(before)
    assert locate.screen_similarity(before, before) == 1.0 and locate.screen_similarity(before, after) < locate.SAME_SCREEN


# ---- tasks 4.39 to 4.43: a whole flow run on a real IE window, with the approvals and the stop ----

FLOW = {
    "schema_version": 2, "engine": "ie", "id": "wf-form", "version": 1, "status": "approved",
    "inputs": [{"name": "acct", "type": "string"}, {"name": "kind", "type": "string"}],
    "steps": [
        {"id": "s1_acct", "action": "fill", "value": "{acct}", "target": {"selectors": ["frame=top|id=txtAcct", "frame=top|label=So tai khoan"], "label": "So tai khoan"}, "risk": "read", "mode": "auto"},
        {"id": "s2_kind", "action": "select", "value": "{kind}", "target": {"selectors": ["frame=top|id=cboKind"], "label": "Loai"}, "risk": "read", "mode": "auto"},
        {"id": "s3_go", "action": "click", "target": {"selectors": ["frame=top|id=btnGo"], "label": "Chay"}, "risk": "money", "mode": "approve"},
        {"id": "s4_note", "action": "read_value", "save_as": "note", "target": {"selectors": ["frame=top|id=lblNote"]}, "risk": "read", "mode": "auto"},
    ],
}


class _Controller:
    """A person who answers: approves, or not, or presses Dung khan while the question is open."""

    def __init__(self, approve=True, stop=None):
        self.approve_answer, self.stop, self.asked, self.log = approve, stop, [], []

    def approve(self, step, index, total):
        self.asked.append(step["id"])
        if self.stop is not None:
            self.stop.set()
        return self.approve_answer

    def review(self, step, index, total):
        return True

    def progress(self, step_id, status, detail):
        self.log.append((step_id, status))


def _run_flow(flow, inputs, controller, driver_class=None, stop=None, path="/form"):
    import threading

    from rookie_agent.ie.driver import IeDriver
    from rookie_agent.runner import run_workflow

    with real_ie(path) as bridge:
        tab = next(t for t in bridge.tabs() if "RookieE2E" in t["title"])
        driver = (driver_class or IeDriver)(bridge, tab["id"])
        result = run_workflow(flow, inputs, driver, controller, stop or threading.Event(), engine="ie", versions=(2, 3))
        os.environ["RK_JS"] = "window.__res = document.getElementById('res').innerHTML;"
        shown = drive("js")
    return result, shown


def test_a_flow_runs_on_the_page_with_the_money_step_waiting_for_a_person():
    controller = _Controller(approve=True)
    result, shown = _run_flow(FLOW, {"acct": "0123456789", "kind": "s"}, controller)
    assert result["status"] == "finished", result
    assert controller.asked == ["s3_go"]                                   # only the money step asked
    assert shown == "went 0123456789 s"                                    # what was filled, chosen and clicked
    assert "0123456789" not in str(result)                                 # the result never holds a value


def test_a_money_step_that_is_not_approved_is_not_done():
    result, shown = _run_flow(FLOW, {"acct": "0123456789", "kind": "s"}, _Controller(approve=False))
    assert result["status"] == "rejected" and "went" not in shown           # the money click never happened


def test_the_emergency_stop_wins_over_an_approval():
    import threading

    stop = threading.Event()
    result, shown = _run_flow(FLOW, {"acct": "0123456789", "kind": "s"}, _Controller(approve=True, stop=stop), stop=stop)
    assert result["status"] == "stopped" and "went" not in shown


def test_a_money_step_is_refused_on_a_page_that_is_not_a_mock():
    from rookie_agent.ie.driver import IeDriver

    class BankPage(IeDriver):
        def window_title(self):
            return "TouchPoint - Home"

    controller = _Controller(approve=True)
    result, shown = _run_flow(FLOW, {"acct": "0123456789", "kind": "s"}, controller, driver_class=BankPage)
    assert result["status"] == "refused" and controller.asked == [] and "went" not in shown


def test_an_element_the_agent_cannot_tell_apart_stops_the_run_and_nothing_after_it_is_done():
    flow = {**FLOW, "steps": [{"id": "s0", "action": "click", "target": {"selectors": ["frame=top|id=dup"]}, "risk": "read", "mode": "auto"}] + FLOW["steps"]}
    controller = _Controller()
    result, shown = _run_flow(flow, {"acct": "0123456789", "kind": "s"}, controller)
    assert result["status"] == "needs_help" and controller.asked == [] and shown == ""   # not even the first step of the flow ran


def test_the_whole_chain_from_the_pages_api_to_a_real_ie_window_with_the_decision_of_a_person(tmp_path):
    """The calls the page makes (start, status, decide) against a real bridge and a real IE window."""
    import time as _time

    from tests.test_webui import make_core

    with real_ie("/form") as bridge:
        core, _ = make_core(tmp_path, ie_bridge=lambda: bridge)
        tab = next(t for t in bridge.tabs() if "RookieE2E" in t["title"])
        core.store.put("flows", [{"title": "Form", "inputs": ["acct", "kind"], "steps": [], "warnings": [], "learned_at": "x", "workflow": {**FLOW, "status": "draft"}}])
        assert core.dispatch("POST", "/api/run/start", {"title": "Form", "inputs": {"acct": "1", "kind": "s"}, "window": f"ie-tab:{tab['id']}", "mode": "run"})[0] == 400
        assert core.dispatch("POST", "/api/flow/approve", {"title": "Form"})[0] == 200
        assert core.dispatch("POST", "/api/run/start", {"title": "Form", "inputs": {"acct": "0123456789", "kind": "s"}, "window": f"ie-tab:{tab['id']}", "mode": "run"})[0] == 200
        deadline, status = _time.monotonic() + 40, {}
        while _time.monotonic() < deadline:
            status = core.dispatch("GET", "/api/run/status", {})[1]
            if status["state"] == "waiting_approval":
                break
            _time.sleep(0.2)
        assert status["state"] == "waiting_approval", status
        ask = status["ask"]
        assert ask["step_id"] == "s3_go" and ask["risk"] == "money"
        assert ask["seen"]                                                  # the card says what the screen shows
        os.environ["RK_JS"] = "window.__res = document.getElementById('res').innerHTML;"
        assert "went" not in drive("js")                                    # the money click waits for the person
        assert core.dispatch("POST", "/api/run/decide", {"approve": True, "ask_id": ask["id"]})[0] == 200
        while _time.monotonic() < deadline:
            status = core.dispatch("GET", "/api/run/status", {})[1]
            if status["state"] == "finished":
                break
            _time.sleep(0.2)
        assert status["state"] == "finished", status
        assert "went 0123456789 s" in drive("js")
        steps = {s["id"]: s["status"] for s in status["steps"]}
        assert steps["s3_go"] == "done" and "0123456789" not in str(status["result"])


# ---- optional steps on a real page ----

OPTIONAL_FLOW = {
    "schema_version": 3, "engine": "ie", "id": "wf-optional", "version": 1, "status": "approved",
    "inputs": [{"name": "acct", "type": "string"}, {"name": "kind", "type": "string", "required": False}],
    "steps": [
        {"id": "s1_acct", "action": "fill", "value": "{acct}", "target": {"selectors": ["frame=top|id=txtAcct"], "label": "So tai khoan"}, "risk": "read", "mode": "auto"},
        {"id": "s2_kind", "action": "select", "value": "{kind}", "optional": {"mode": "if_different"}, "target": {"selectors": ["frame=top|id=cboKind"], "label": "Loai"}, "risk": "read", "mode": "auto"},
        {"id": "s3_ghost", "action": "click", "optional": {"mode": "if_present", "wait_ms": 400}, "target": {"selectors": ["frame=top|id=btnGhost"], "label": "Dong"}, "risk": "read", "mode": "auto"},
        {"id": "s4_go", "action": "click", "target": {"selectors": ["frame=top|id=btnGo"], "label": "Chay"}, "risk": "read", "mode": "auto"},
    ],
}


def test_an_optional_list_left_empty_is_not_touched_on_a_real_page_and_the_flow_goes_on():
    result, shown = _run_flow(OPTIONAL_FLOW, {"acct": "0123456789"}, _Controller())
    assert result["status"] == "finished", result
    statuses = {s["id"]: s["status"] for s in result["steps"]}
    assert statuses["s2_kind"] == "skipped" and statuses["s3_ghost"] == "skipped" and statuses["s4_go"] == "done"
    assert shown == "went 0123456789 d"                       # the list kept the value the page had; the page heard no change


def test_an_optional_list_with_a_value_is_chosen_on_a_real_page():
    result, shown = _run_flow(OPTIONAL_FLOW, {"acct": "0123456789", "kind": "s"}, _Controller())
    assert result["status"] == "finished" and shown == "went 0123456789 s"


def test_a_preview_on_a_real_page_shows_the_steps_and_the_screen_while_the_teller_works_and_keeps_nothing(tmp_path):
    import time as _time

    from tests.test_webui import make_core

    with real_ie("/search") as bridge:
        core, _ = make_core(tmp_path, ie_bridge=lambda: bridge)
        tab = next(t for t in bridge.tabs() if "RookieE2E" in t["title"])
        assert core.dispatch("POST", "/api/record/start", {"window": f"ie-tab:{tab['id']}", "preview": True})[0] == 200
        time.sleep(1.0)
        os.environ["RK_VALUE"] = "0123456789"
        for action, wait in (("s-acct", 0.5), ("s-find", 3.5)):
            drive(action)
            time.sleep(wait)
        live = core.dispatch("GET", "/api/live", {})[1]
        seen = core.dispatch("GET", "/api/seen", {})[1]
        assert live["preview"] and live["count"] >= 2 and len(live["steps"]) >= 2        # the steps appear while the teller works
        assert seen["last"] and any(t["headers"] == ["So TK", "Loai", "So du"] for f in seen["last"]["frames"] for t in f["tables"])
        stopped = core.dispatch("POST", "/api/record/stop", {})
        assert stopped[0] == 200 and stopped[1]["preview"] is True
        assert core.dispatch("GET", "/api/recordings", {})[1]["recordings"] == []         # nothing was saved
        assert not (tmp_path / "traces").exists() or not list((tmp_path / "traces").iterdir())
        on_disk = "".join(p.read_text(encoding="utf-8", errors="ignore") for p in tmp_path.rglob("*") if p.is_file())
        assert "0123456789" not in on_disk                                              # and no value reached the disk


def test_a_value_read_from_the_screen_is_called_by_a_later_step_on_a_real_page():
    """Search, read the whole screen as data, then type the account number of the SECOND row into another field."""
    import threading

    from rookie_agent.ie.driver import IeDriver
    from rookie_agent.runner import run_workflow

    flow = {"schema_version": 3, "engine": "ie", "id": "wf-data", "version": 1, "status": "approved",
            "inputs": [{"name": "acct", "type": "string"}],
            "steps": [
                {"id": "s1", "action": "fill", "value": "{acct}", "target": {"selectors": ["frame=main|id=txtAcct"]}, "risk": "read", "mode": "auto"},
                {"id": "s2", "action": "click", "target": {"selectors": ["frame=main|id=btnFind"]}, "risk": "read", "mode": "auto"},
                {"id": "s3", "action": "read_fields", "save_as": "kq", "risk": "read", "mode": "auto"},
                {"id": "s4", "action": "fill", "value": "{kq.grid.1.so_tk}", "target": {"selectors": ["frame=main|id=txtCopy"]}, "risk": "read", "mode": "auto"}]}
    with real_ie("/search") as bridge:
        tab = next(t for t in bridge.tabs() if "RookieE2E" in t["title"])
        result = run_workflow(flow, {"acct": "0123456789"}, IeDriver(bridge, tab["id"]), _Controller(), threading.Event(), engine="ie", versions=(2, 3))
        os.environ["RK_JS"] = "window.__res = window.frames['main'].document.getElementById('txtCopy').value;"
        copied = drive("js")
    assert result["status"] == "finished", result
    assert copied == "9002"                                    # the second row of the table the search showed
    assert "9002" not in str(result)                           # and the value is not in what the run reports


# ---- the whole system: record twice, learn with the model through the server, run what was learned ----

class _InProcessServer:
    """A ServerClient that talks to the real server application in this process: the same requests, no network."""

    def __init__(self, client):
        self._client = client

    def health(self):
        return {"ok": True}

    def post_session(self, session_id, engine, events, role=None, case_key=None):
        from rookie_agent.server_client import session_body

        body = session_body(session_id, engine, events, role, case_key)      # the same body as ServerClient.post_session
        reply = self._client.post("/sessions", json=body)
        assert reply.status_code == 201, reply.text

    def plan_request(self, payload):
        reply = self._client.post("/assistant/plan", json=payload)
        assert reply.status_code == 200, reply.text
        return reply.json()

    def learn(self, workflow_id, session_ids, title=None, traces=None):
        from rookie_agent.server_client import ServerError

        body = {"session_ids": session_ids, "title": title}
        if traces:
            body["traces"] = traces
        import json as _j, os as _o
        if _o.environ.get("RK_DUMP"):
            open(_o.environ["RK_DUMP"], "w", encoding="utf-8").write(_j.dumps(traces, ensure_ascii=False, indent=1))
        reply = self._client.post("/workflows/learn", json=body)
        if reply.status_code != 201:
            raise ServerError(str(reply.json().get("detail")))
        return reply.json()


def test_record_twice_learn_with_the_model_and_run_what_was_learned_on_a_real_page(tmp_path):
    import sys
    import time as _time
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    from tests.test_webui import make_core    # first: the server has a package named `tests` too, a regular one that would win afterwards
    sys.path.append(str(repo / "server"))
    from app.llm import codie_cli
    from app.llm.flow import CodieFlowBuilder
    from app.main import create_app
    from fastapi.testclient import TestClient

    app = create_app(tmp_path / "server.db")
    app.state.flow_builder = CodieFlowBuilder(codie_cli.Settings(argv0=[sys.executable, str(Path(__file__).with_name("fake_model.py"))], timeout=60))
    with TestClient(app) as server, real_ie("/search") as bridge:
        core, _ = make_core(tmp_path, ie_bridge=lambda: bridge, server_client=lambda url: _InProcessServer(server))
        tab = next(t for t in bridge.tabs() if "RookieE2E" in t["title"])
        ids = []
        for account in ("0123456789", "5555555555"):
            os.environ["RK_JS"] = "window.__res = window.frames['main'].document.getElementById('txtCopy').value = '';"    # a field that already holds the value raises no change
            drive("js")
            assert core.dispatch("POST", "/api/record/start", {"window": f"ie-tab:{tab['id']}"})[0] == 200
            _time.sleep(1.0)
            os.environ["RK_VALUE"], os.environ["RK_COPY"] = account, "9002"
            for action, wait in (("s-acct", 0.4), ("s-find", 3.5), ("s-copy", 1.5)):
                drive(action)
                _time.sleep(wait)
            status, saved = core.dispatch("POST", "/api/record/stop", {"name": "tra cuu"})
            assert status == 200, saved
            ids.append(saved["id"])
        status, shown = core.dispatch("POST", "/api/learn", {"ids": ids, "title": "Tra cuu tai khoan"})
        assert status == 200, shown
        assert shown["method"] == "codie", (shown.get("fallback_reason"), shown.get("llm"))                                                  # the model built it, the gate passed it
        workflow = core.store.get("flows")[0]["workflow"]
        actions = [(s["action"], s.get("value")) for s in workflow["steps"]]
        assert actions[0][0] == "fill" and actions[0][1].startswith("{") and ("click", None) in actions
        assert ("read_fields", None) in actions and ("fill", "{kq.grid.1.so_tk}") in actions       # the link was found and used
        calls = core.dispatch("GET", "/api/calls", {})[1]["calls"]
        assert [c["mode"] for c in calls][:2] == ["rookie-workflow", "rookie-design"] and all(c["ok"] for c in calls[:2])
        # run what was learned, with a new account number
        assert core.dispatch("POST", "/api/flow/approve", {"title": "Tra cuu tai khoan"})[0] == 200
        name = next(i["name"] for i in workflow["inputs"])
        os.environ["RK_JS"] = "window.__res = window.frames['main'].document.getElementById('txtCopy').value = '';"
        drive("js")
        assert core.dispatch("POST", "/api/run/start", {"title": "Tra cuu tai khoan", "inputs": {name: "7777777777"}, "window": f"ie-tab:{tab['id']}", "mode": "run"})[0] == 200
        deadline, status = _time.monotonic() + 60, {}
        while _time.monotonic() < deadline:
            status = core.dispatch("GET", "/api/run/status", {})[1]
            if status["state"] in ("finished", "needs_help", "failed", "refused", "stopped", "rejected"):
                break
            _time.sleep(0.3)
        assert status["state"] == "finished", status
        os.environ["RK_JS"] = "window.__res = window.frames['main'].document.getElementById('txtCopy').value;"
        assert drive("js") == "9002"                                                              # the value read from the screen, typed by the agent
        # the Assistant: one sentence, one card, one click; the same agent runs with the account that was in the sentence
        drive_js = lambda code: (os.environ.__setitem__("RK_JS", code), drive("js"))[1]
        drive_js("window.__res = window.frames['main'].document.getElementById('txtCopy').value = '';")
        shown = core.dispatch("POST", "/api/assistant/plan", {"text": "tra cuu tai khoan 8888888888"})[1]
        assert shown["state"] == "ready" and shown["inputs"][0]["value"] == "8888888888", shown
        assert core.dispatch("POST", "/api/assistant/run", {"plan_id": shown["plan_id"], "window": f"ie-tab:{tab['id']}"})[0] == 200
        deadline = _time.monotonic() + 60
        while _time.monotonic() < deadline:
            status = core.dispatch("GET", "/api/run/status", {})[1]
            if status["state"] in ("finished", "needs_help", "failed", "refused", "stopped", "rejected"):
                break
            _time.sleep(0.3)
        assert status["state"] == "finished", status
        assert drive_js("window.__res = window.frames['main'].document.getElementById('txtCopy').value;") == "9002"
        audit = (core.store.home / "audit.jsonl").read_text(encoding="utf-8")
        assert '"via": "assistant"' in audit and "8888888888" not in audit and "tra cuu" not in audit.lower().replace("tra cuu tai khoan", "")


def test_requests_made_on_the_screen_the_page_moved_to_are_tracked():
    """The screen changes by itself after a click (like the sign in). What the teller does on the new screen is tracked again.
    Known limit: a request the new page sends in the first instants of loading, before the recorder is in that page, cannot be seen."""
    with real_ie("/ajaxnav") as bridge:
        session = start_session(bridge)
        drive("a-nav")
        time.sleep(6.0)
        drive("a-native")
        time.sleep(2.0)
        session.stop()
    posts = [r for r in session.requests if r["method"] == "POST" and (r["after"] or {}).get("id") == "btnNative"]
    assert len(posts) == 1 and posts[0]["status"] == 200 and "NGUYEN VAN A" in posts[0]["res"], session.requests


def test_a_screen_that_opens_in_a_new_tab_is_recorded_too():
    """The next screen of a sign in may open in a new tab of the same IE window (it shares the window handle of the first tab)."""
    with real_ie("/opener") as bridge:
        bridge_url = "http://127.0.0.1:" + str(bridge.test_port)
        session = start_session(bridge)
        os.environ["RK_URL"] = bridge_url + "/ajaxtab"
        drive("open-tab")
        time.sleep(4.0)
        drive("a-native", "Tab2")
        time.sleep(2.0)
        titles = [t["title"] for t in bridge.tabs()]
        session.stop()
        drive("quit", "Tab2")
    assert any("Tab2" in t for t in titles), titles
    assert [r for r in session.requests if r["method"] == "POST"], (titles, session.requests)
    assert any(line.get("id") == "btnNative" for line in session.raw), titles


@pytest.mark.parametrize("requests", [False, True])
def test_changing_screens_while_recording_never_makes_a_script_error_of_its_own(requests):
    """Sign in, the role screen and the main screen (frames that reload): the recorder must not be the cause of a script error."""
    with real_ie() as bridge:
        session = start_session(bridge, requests=requests)
        for action, wait in (("click-label", 0.3), ("type-user", 0.5), ("type-pw", 0.5), ("click-login", 3.0), ("f-role-lang", 2.0), ("f-ok", 2.5)):
            drive(action)
            time.sleep(wait)
        session.stop()
    assert session.js_errors == [], session.js_errors
    assert not [n for n in session.notes if "Lỗi bộ ghi" in n or "tự tắt" in n], session.notes


@pytest.mark.parametrize("listen, expect_click", [("none", False), ("click", True), ("", True)])
def test_ROOKIE_IE_LISTEN_puts_in_only_the_listeners_asked_for(listen, expect_click):
    """To find which listener upsets a page: nothing is listened to with "none"; "click" listens to clicks only."""
    if listen:
        os.environ["ROOKIE_IE_LISTEN"] = listen
    try:
        with real_ie("/ajax") as bridge:
            session = start_session(bridge, requests=False)
            drive("a-native")
            time.sleep(1.5)
            session.stop()
    finally:
        os.environ.pop("ROOKIE_IE_LISTEN", None)
    got = any(line.get("kind") == "click" and line.get("id") == "btnNative" for line in session.raw)
    assert got is expect_click, (listen, [(l.get("kind"), l.get("id")) for l in session.raw])


def test_a_failure_in_the_recorders_own_reading_never_reaches_the_pages_error_handler():
    """TouchPoint opens its error dialog (errorDlg.htm) from window.onerror: nothing of the recorder's may get there."""
    with real_ie("/ajax") as bridge:
        session = start_session(bridge, requests=False)
        os.environ["RK_JS"] = ("window.__pageErrors = 0; window.onerror = function () { window.__pageErrors++; return true; };"
                               "window.__rkTestReadFail = true; window.__res = 'set';")
        drive("js")
        drive("a-native")
        time.sleep(3.0)
        os.environ["RK_JS"] = "window.__res = String(window.__pageErrors);"
        count = drive("js")
        session.stop()
    assert count == "0", count
    assert any("Lỗi bộ ghi" in note and "forced read failure" in note for note in session.notes), session.notes


def test_recording_writes_nothing_onto_the_elements_of_the_page():
    """A script of the page that clones or walks its elements must find them as the page made them: no property of ours on any element."""
    with real_ie() as bridge:
        session = start_session(bridge, requests=False)
        for action, wait in (("click-label", 0.3), ("type-user", 0.5), ("type-pw", 0.5), ("click-login", 3.0), ("f-role-lang", 2.0)):
            drive(action)
            time.sleep(wait)
        os.environ["RK_JS"] = ("var r = [], docs = [document], d, all, i, p; try { docs.push(window.frames['desktopFrame'].frames['rhidden'].document); } catch (e) {}"
                               "for (d = 0; d < docs.length; d++) { all = docs[d].getElementsByTagName('*'); for (i = 0; i < all.length; i++) {"
                               " for (p in all[i]) { if (String(p).indexOf('__rk') === 0) { r.push(all[i].tagName + '.' + p); } } } }"
                               "window.__res = 'docs=' + docs.length + ' found=' + r.join(',');")
        shown = drive("js")
        session.stop()
    assert shown.startswith("docs=2") and shown.endswith("found="), shown
    assert any(line.get("kind") == "input" and line.get("id") == "txtUser" for line in session.raw) or any(line.get("id") == "txtUser" for line in session.raw), [(l.get("kind"), l.get("id")) for l in session.raw]


def test_what_the_pages_own_script_does_with_the_focus_is_not_read_and_what_the_teller_typed_is_still_kept():
    """TouchPoint moves the focus and fills fields itself when its answer comes. The recorder must not read a field inside such a
    change (that is what upset TouchPoint): a focus change no press of the teller led to is left alone. The value the teller typed
    before the page moved the cursor away is still recorded, at the teller's next press."""
    with real_ie("/search") as bridge:
        session = start_session(bridge, requests=False)
        os.environ["RK_VALUE"] = "0123456789"
        drive("s-acct-stay")
        time.sleep(1.5)
        os.environ["RK_JS"] = ("var a = document.getElementById('txtAcct'), c = document.getElementById('txtCopy');"
                               "function f(el, n) { try { el.fireEvent('on' + n); } catch (x) {} }"
                               "try { c.focus(); } catch (x) {} f(a, 'focusout'); f(c, 'focusin'); c.value = 'PAGESET'; f(c, 'change'); f(c, 'focusout'); f(a, 'focusin');"
                               "window.__res = 'moved';")
        assert drive("js-main") == "moved"
        time.sleep(1.5)
        drive("s-find")
        time.sleep(1.5)
        events = session.stop()
    steps = [(e["type"], e["target"]["selectors"][0]) for e in events]
    assert steps == [("input", "frame=main|id=txtAcct"), ("click", "frame=main|id=btnFind")], (steps, [(r["kind"], r.get("id")) for r in session.raw])
    assert "PAGESET" not in json.dumps(session.raw)                                  # the page's own value was never taken for the teller's
    assert not [r for r in session.raw if r.get("id") == "txtCopy" and r["kind"] in ("focus", "input")], session.raw


def test_the_recorder_is_put_into_a_page_once_and_is_not_run_again_at_every_look():
    """Every look ran the whole recorder in every frame again (each 150 ms): script of ours inside the page all the time, and also
    while the page's own script waits in a dialog. Once it is in, a look only takes the lines."""
    with real_ie("/ajax") as bridge:
        session = start_session(bridge, requests=False)
        os.environ["RK_JS"] = "window.__rkRec = false; window.__res = 'set';"
        drive("js")
        time.sleep(1.5)
        os.environ["RK_JS"] = "window.__res = String(window.__rkRec); window.__rkRec = true;"
        shown = drive("js")
        drive("a-native")
        time.sleep(1.5)
        session.stop()
    assert shown == "false", shown                                                    # nothing put it back: the recorder was not run again
    assert any(line.get("kind") == "click" and line.get("id") == "btnNative" for line in session.raw)


def test_a_javascript_link_that_keeps_the_page_sends_no_cookie_of_the_recorder_to_the_server():
    """IE fires beforeunload for <a href="javascript:..."> (GWT pages are full of them) although the page stays: the recorder must not
    put its lines in a cookie then, or the page's next request carries them to the bank's server."""
    with real_ie("/jslink") as bridge:
        session = start_session(bridge, requests=False)
        os.environ["RK_JS"] = "window.__ck = 'not run'; document.getElementById('lnkFind').click(); window.__res = 'clicked';"
        drive("js")
        time.sleep(1.0)
        os.environ["RK_JS"] = "window.__res = String(window.__ck);"
        cookies = drive("js")
        session.stop()
    assert cookies != "not run", cookies                                              # the link really ran
    assert "__rkkeep" not in cookies, cookies
    assert any(line.get("kind") == "click" and line.get("id") == "lnkFind" for line in session.raw), session.raw


def test_the_record_button_accepts_a_page_when_listeners_are_left_out_on_purpose_and_the_panel_says_whether_requests_are_recorded(tmp_path):
    from tests.test_webui import make_core

    os.environ["ROOKIE_IE_LISTEN"] = "none"
    try:
        with real_ie("/search") as bridge:
            core, _ = make_core(tmp_path, ie_bridge=lambda: bridge)
            tab = next(t for t in bridge.tabs() if "RookieE2E" in t["title"])
            assert core.dispatch("POST", "/api/record/start", {"window": f"ie-tab:{tab['id']}", "preview": True})[0] == 200
            time.sleep(1.0)
            live = core.dispatch("GET", "/api/live", {})[1]
            core.dispatch("POST", "/api/record/stop", {})
    finally:
        os.environ.pop("ROOKIE_IE_LISTEN", None)
    assert "Ghi yêu cầu: bật" in live["hint"], live


@pytest.mark.parametrize("diag, injected, clicked, read", [("", True, True, True), ("noread", True, True, False), ("nolisten", True, False, True), ("none", False, False, False),
                                                        ("only-click", True, True, True), ("only-key", True, False, True), ("only-field", True, False, True), ("only-page", True, False, True),
                                                        ("field-empty", True, False, True), ("only-focusin", True, False, True), ("only-focusout", True, False, True), ("only-change", True, False, True),
                                                        ("body-prop", True, False, True), ("body-label", True, False, True), ("body-place", True, False, True),
                                                        ("body-uid", True, False, True), ("body-value", True, False, True), ("body-meta", True, False, True)])
def test_the_diagnosis_levels_take_away_exactly_what_they_say(diag, injected, clicked, read):
    """To find what upsets a page: nothing run in the page ("none"), no listener ("nolisten"), no reading of the screen ("noread")."""
    with real_ie("/ajax") as bridge:
        session = start_session(bridge, requests=False, diag=diag)
        drive("a-native")
        time.sleep(2.0)
        os.environ["RK_JS"] = "window.__res = typeof window.__rkOn;"
        on = drive("js")
        session.stop()
    assert (on == "boolean") is injected, on
    assert any(line.get("kind") == "click" and line.get("id") == "btnNative" for line in session.raw) is clicked, [(l.get("kind"), l.get("id")) for l in session.raw]
    assert bool(session.seen) is read, session.seen


def test_the_recorder_waits_until_the_page_has_finished_loading_and_then_goes_in():
    with real_ie("/ajax") as bridge:
        session = start_session(bridge, requests=False)
        os.environ["RK_JS"] = "window.setTimeout(\"location.href='/slowpage'\", 50); window.__res = 'go';"
        drive("js")
        time.sleep(1.5)
        os.environ["RK_JS"] = "window.__res = document.readyState + '|' + typeof window.__rkOn;"
        while_loading = drive("js", "")
        time.sleep(5.5)
        after = drive("js", "")
        session.stop()
    assert while_loading.endswith("|undefined") and not while_loading.startswith("complete"), while_loading
    assert after == "complete|boolean", after


def test_without_the_request_option_the_page_is_left_alone_and_what_the_teller_does_is_still_recorded():
    """Recording must not upset the page: by default the page's own XMLHttpRequest and ActiveXObject are not touched."""
    with real_ie("/ajax") as bridge:
        session = start_session(bridge, requests=False)
        drive("a-native")
        time.sleep(2.0)
        drive("a-active")
        time.sleep(1.5)
        os.environ["RK_JS"] = ("window.__res = String(window.__rkAjaxHooked) + '|' + document.getElementById('out').innerHTML;")
        shown = drive("js")
        session.stop()
    assert shown.startswith("undefined|") and "active 200" in shown            # not hooked, and the page got its answers
    assert session.requests == []
    assert any(line.get("id") == "btnNative" for line in session.raw)                   # the clicks are still recorded


def test_a_password_in_a_request_body_is_never_kept():
    session, _, shown = _requests([("a-pw", 2.0)])
    assert "pw 200" in shown                                               # the page's request went out untouched
    [req] = session.requests
    assert "S3cretPw" not in req["req"] and "4321" not in req["req"] and "Another1" not in req["req"]
    assert "teller01" in req["req"] and "keep=yes" in req["req"]            # the rest of the body is still there


def test_a_page_that_reads_responseXML_parseError_early_finds_an_object_as_with_the_real_request():
    """TouchPoint's commonIncludes.js read xhr.responseXML.parseError and got 'undefined or null reference'."""
    with real_ie("/ajax") as bridge:
        session = start_session(bridge, requests=True)
        os.environ["RK_JS"] = ("var out = []; var ids = ['Microsoft.XMLHTTP', 'MSXML2.XMLHTTP'];"
                               "for (var i = 0; i < ids.length; i++) { var x = new ActiveXObject(ids[i]); x.open('GET', '/api/ping', false);"
                               " out.push(typeof x.responseXML + ':' + (x.responseXML ? typeof x.responseXML.parseError : 'none'));"
                               " x.send(); out.push(x.responseXML ? typeof x.responseXML.parseError : 'none'); }"
                               "window.__res = out.join(',');")
        shown = drive("js")
        session.stop()
    assert "none" not in shown and "undefined:" not in shown, shown


def test_an_error_inside_the_recorder_while_recording_an_action_reaches_the_panel_notes():
    with real_ie("/ajax") as bridge:
        session = start_session(bridge, requests=False)
        os.environ["RK_JS"] = "window.__rkTestHandlerFail = true; window.__res = 'set';"
        drive("js")
        drive("a-native")
        time.sleep(2.0)
        session.stop()
    assert any("Lỗi bộ ghi trong trang" in note and "forced handler failure" in note for note in session.notes), session.notes


def test_a_script_error_of_the_page_itself_reaches_the_panel_with_its_detail_and_is_not_swallowed():
    with real_ie("/ajax") as bridge:
        session = start_session(bridge, requests=False)
        os.environ["RK_JS"] = ("window.__seen = ''; var old = window.onerror; window.onerror = function (m) { window.__seen = String(m); return true; };"
                               "window.setTimeout('rkNoSuchFunction123()', 1500); window.__res = 'set';")
        drive("js")
        time.sleep(3.5)
        os.environ["RK_JS"] = "window.__res = window.__seen;"
        seen = drive("js")
        session.stop()
    assert session.js_errors and "rkNoSuchFunction123" in session.js_errors[0]["message"], session.js_errors
    assert any("Lỗi JavaScript của trang" in note for note in session.notes), session.notes
    assert "rkNoSuchFunction123" in seen or seen == "", seen      # the page's own handler (set after ours) still sees it


def test_the_page_really_runs_in_the_document_mode_asked_for():
    """The suite is run with RK_DOCMODE=5, 8 and 9 (IE 11 standing in for the old browsers): the mode must be the one asked for."""
    with real_ie("/ajax") as bridge:
        start_session(bridge, requests=False)
        os.environ["RK_JS"] = "window.__res = String(document.documentMode);"
        shown = drive("js")
    assert shown == os.environ.get("RK_DOCMODE", "5"), shown


def test_a_page_that_uses_the_capitalised_names_of_an_activex_request_still_works():
    """TouchPoint's checkResponseError reads inXMLHTTP.ResponseText / .Status: ActiveX ignores case, so the stand-in must too."""
    with real_ie("/ajax") as bridge:
        session = start_session(bridge, requests=True)
        os.environ["RK_JS"] = ("var x = new ActiveXObject('Msxml2.XMLHTTP'); x.Open('GET', '/api/ping', false); x.Send(null);"
                               "window.__res = x.Status + '|' + x.ResponseText + '|' + typeof x.ResponseXML.parseError + '|' + x.ReadyState;")
        shown = drive("js")
        session.stop()
    assert shown.startswith("200|") and "pong" in shown and "|object|4" in shown or "|undefined|4" not in shown and shown.startswith("200|"), shown
    assert [r for r in session.requests if r["url"] == "/api/ping"], session.requests


def test_a_script_error_right_after_a_request_makes_the_recorder_step_back_and_the_site_is_remembered():
    with real_ie("/ajax") as bridge:
        session = start_session(bridge, requests=True)
        failed = []
        session.on_hook_failed = failed.append
        os.environ["RK_JS"] = "var x = new ActiveXObject('Microsoft.XMLHTTP'); x.open('GET', '/api/ping', true); window.setTimeout('rkNoSuchFunction()', 100); window.__res = 'set';"
        drive("js")
        time.sleep(2.5)
        os.environ["RK_JS"] = "window.__res = String(window.__rkAjax);"
        shown = drive("js")
        session.stop()
    assert shown == "off:pageerror", shown
    assert failed and failed[0], failed
    assert any("tự tắt" in note for note in session.notes), session.notes


def test_when_the_recorders_own_part_fails_the_page_gets_its_own_request_objects_back_and_the_screen_says_so():
    with real_ie("/ajax") as bridge:
        session = start_session(bridge, requests=True)
        os.environ["RK_JS"] = "window.__rkTestFail = true; window.__res = 'set';"
        drive("js")
        drive("a-native")
        time.sleep(2.0)
        os.environ["RK_JS"] = "window.__res = String(window.__rkAjax) + '|' + document.getElementById('out').innerHTML;"
        shown = drive("js")
        session.stop()
    assert shown.startswith("off:finish|") and "native 200" in shown       # the page still got its answer, and its objects are its own again
    assert any("tự tắt" in note for note in session.notes), session.notes


def test_a_learned_request_is_sent_again_from_the_page_in_its_own_session_and_the_screen_is_not_touched():
    """Task 7.3: the page sends it (its cookie goes along, none is read), with the header it set; the answer comes back to the agent."""
    with real_ie("/form") as bridge:
        tab = next(t for t in bridge.tabs() if "RookieE2E" in t["title"])
        os.environ["RK_JS"] = "document.cookie = 'sid=S1; path=/'; window.__res = 'ok';"
        drive("js")
        bridge.bind(tab["id"])
        answer = bridge.send("top", "POST", "/api/cif", "X-Test:1\nContent-Type:application/x-www-form-urlencoded\n", "cif=4455667788")
        refused = bridge.send("top", "POST", "/api/cif", "", "cif=1")
        nowhere = bridge.send("nope", "GET", "/api/ping", "", "")
        os.environ["RK_JS"] = "window.__res = document.getElementById('res').innerHTML + '|' + document.getElementById('txtAcct').value;"
        shown = drive("js")
    assert answer["ok"] and answer["status"] == 200, answer
    assert '"cif":"4455667788"' in answer["text"] and "sid=S1" in answer["text"]
    assert refused["ok"] and refused["status"] == 403
    assert nowhere == {"ok": False, "error": "no_frame"}
    assert shown == "|"                                                  # nothing on the screen was filled or clicked


def test_an_element_whose_frame_was_renamed_since_the_recording_is_found_in_its_one_frame():
    """TouchPoint may name or order its frames differently after another sign-in: the selectors are then asked of every frame."""
    from rookie_agent.ie.driver import IeDriver

    with real_ie("/form") as bridge:
        tab = next(t for t in bridge.tabs() if "RookieE2E" in t["title"])
        IeDriver(bridge, tab["id"]).fill(["frame=gone/main|id=txtAcct", "frame=gone/main|label=So tai khoan"], "5566778899")
        os.environ["RK_JS"] = "window.__res = document.getElementById('txtAcct').value;"
        shown = drive("js")
    assert shown == "5566778899"


def test_record_the_api_calls_learn_them_and_run_them_from_the_page_with_a_new_customer_id(tmp_path):
    """Gate 8 end to end: the screen opening gives a token, the search sends it with the typed id, the detail form posts the customer
    number the search answered. Learned from one recording, run with another id: every call goes with this run's values."""
    import sys
    import time as _time
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    from tests.test_webui import make_core
    sys.path.append(str(repo / "server"))
    from app.main import create_app
    from fastapi.testclient import TestClient

    app = create_app(tmp_path / "server.db")
    app.state.flow_builder = None
    Handler.seen.clear()
    with TestClient(app) as server, real_ie("/cifapp") as bridge:
        core, _ = make_core(tmp_path, ie_bridge=lambda: bridge, server_client=lambda url: _InProcessServer(server))
        for _ in range(75):                                   # the page with a frame takes a moment to show its title
            tab = next((t for t in bridge.tabs() if "RookieE2E Cif" in t["title"]), None)
            if tab:
                break
            _time.sleep(0.2)
        assert tab, bridge.tabs()
        assert core.dispatch("POST", "/api/record/start", {"window": f"ie-tab:{tab['id']}", "requests": True})[0] == 200
        _time.sleep(1.0)
        os.environ["RK_VALUE"] = "0123456789"
        for action, wait in (("c-open", 1.0), ("c-cif", 0.5), ("c-find", 1.5), ("c-detail", 2.5)):
            drive(action, "RookieE2E Cif")
            _time.sleep(wait)
        status, saved = core.dispatch("POST", "/api/record/stop", {"name": "tra cif"})
        assert status == 200 and saved["requests_kept"] >= 3, saved
        status, shown = core.dispatch("POST", "/api/learn", {"ids": [saved["id"]], "title": "Tra CIF"})
        assert status == 200 and shown["api_count"] >= 3, shown
        flow = core.store.get("flows")[0]
        assert "0123456789" not in json.dumps(flow) and Handler.token not in json.dumps(flow)
        kinds = [(n["method"], "/" + n["url"].split("?")[0].split("/", 3)[-1] if "://" in n["url"] else n["url"].split("?")[0], n["kind"]) for n in flow["api"]]
        assert ("GET", "/api/init", "xhr") in kinds and ("POST", "/api/cif2", "xhr") in kinds and ("POST", "/api/detail", "form") in kinds, kinds
        name = flow["workflow"]["inputs"][0]["name"]
        Handler.seen.clear()
        os.environ["RK_JS"] = "window.__res = document.getElementById('res').innerHTML = '';"
        drive("js", "RookieE2E Cif")
        status, reply = core.dispatch("POST", "/api/run/start", {"title": "Tra CIF", "mode": "simulate", "window": f"ie-tab:{tab['id']}", "inputs": {name: "5566778899"}})
        assert status == 200, reply
        for _ in range(150):
            run = core.dispatch("GET", "/api/run/status", {})[1]
            if run.get("result"):
                break
            _time.sleep(0.2)
        os.environ["RK_JS"] = "window.__res = document.getElementById('res').innerHTML + '|' + document.getElementById('txtCif').value;"
        shown_page = drive("js", "RookieE2E Cif")
    assert run["result"]["status"] == "finished", run
    expected = "kh=KX%d" % (sum(int(c) for c in "5566778899") * 137 + 7)
    assert Handler.seen == ["5566778899", expected], Handler.seen          # the new id, then the customer number its answer gave
    assert shown_page == "|0123456789"                                      # the screen was not touched by the run


def _sess_tab(bridge):
    import time as _time
    for _ in range(75):
        tab = next((t for t in bridge.tabs() if "RookieE2E Sess" in t["title"]), None)
        if tab:
            return tab
        _time.sleep(0.2)
    raise AssertionError(bridge.tabs())


def test_a_run_takes_the_session_the_page_uses_now_from_the_live_page_when_the_sign_in_gave_a_new_one(tmp_path):
    """The sign-in answer gave the session id the screen opening sends. A real run never signs in again: the id comes from what the open
    page sent last (the page signed in again by itself since the recording), and the old one would be refused."""
    import sys
    import time as _time
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    from tests.test_webui import make_core
    sys.path.append(str(repo / "server"))
    from app.main import create_app
    from fastapi.testclient import TestClient

    app = create_app(tmp_path / "server.db")
    app.state.flow_builder = None
    Handler.seen.clear()
    with TestClient(app) as server, real_ie("/sessapp") as bridge:
        core, _ = make_core(tmp_path, ie_bridge=lambda: bridge, server_client=lambda url: _InProcessServer(server))
        tab = _sess_tab(bridge)
        assert core.dispatch("POST", "/api/record/start", {"window": f"ie-tab:{tab['id']}", "requests": True})[0] == 200
        _time.sleep(1.0)
        os.environ["RK_VALUE"] = "0123456789"
        for action, wait in (("enter-pw", 2.0), ("q-role", 0.8), ("c-open", 1.5), ("c-cif", 0.5), ("c-find", 1.5)):
            drive(action, "RookieE2E Sess")
            _time.sleep(wait)
        status, saved = core.dispatch("POST", "/api/record/stop", {"name": "tra cif phien"})
        assert status == 200 and saved["requests_kept"] >= 3, saved
        status, shown = core.dispatch("POST", "/api/learn", {"ids": [saved["id"]], "title": "Tra CIF phien"})
        assert status == 200 and shown["api_count"] >= 3, shown
        flow = core.store.get("flows")[0]
        old_sid = Handler.sid
        assert old_sid and old_sid not in json.dumps(flow) and Handler.token not in json.dumps(flow)
        opening = next(n for n in flow["api"] if n["url"].endswith("/api/open"))
        assert opening["body"] == "sid=⟦l1⟧&screen=1" and opening["links"]["l1"]["from"] in [n["id"] for n in flow["api"] if n["url"].endswith("/api/login")], [(n["id"], n["label"], n["body"], n["links"]) for n in flow["api"]]
        name = flow["workflow"]["inputs"][0]["name"]
        Handler.seen.clear()
        os.environ["RK_JS"] = "again(); window.__res = 1;"          # a new session: the page signed in and opened its screen by itself
        drive("js", "RookieE2E Sess")
        _time.sleep(2.0)
        new_sid = Handler.sid
        assert new_sid != old_sid and Handler.seen == ["open:" + new_sid], (old_sid, new_sid, Handler.seen)
        Handler.seen.clear()
        status, reply = core.dispatch("POST", "/api/run/start", {"title": "Tra CIF phien", "mode": "simulate", "window": f"ie-tab:{tab['id']}", "inputs": {name: "5566778899"}})
        assert status == 200, reply
        for _ in range(150):
            run = core.dispatch("GET", "/api/run/status", {})[1]
            if run.get("result"):
                break
            _time.sleep(0.2)
    assert run["result"]["status"] == "finished", run
    assert Handler.seen == ["open:" + new_sid, "5566778899"], Handler.seen      # the live session, then the search with the token it gave
    assert new_sid not in json.dumps(core.store.get("flows")) and new_sid not in json.dumps(run["result"])


def test_binding_a_run_watches_the_pages_requests_in_memory_only_even_when_nothing_was_recorded():
    import time as _time
    with real_ie("/sessapp") as bridge:
        tab = _sess_tab(bridge)
        bridge.bind(tab["id"], peek=True)
        os.environ["RK_JS"] = "again(); window.__res = 1;"
        drive("js", "RookieE2E Sess")
        _time.sleep(2.0)
        bodies = bridge.last_requests("*", "/api/open")
        os.environ["RK_JS"] = "window.__res = String(window.__rkRec) + '|' + String(window.__rkq)"
        state = drive("js", "RookieE2E Sess")
        bridge.unbind()
    assert len(bodies) == 1 and bodies[0] == "sid=" + Handler.sid + "&screen=1", (bodies, Handler.sid)
    assert state == "false|", state                                           # nothing was recorded


def test_a_service_call_with_a_bearer_token_from_a_token_service_is_recorded_learned_and_run_with_a_fresh_token(tmp_path):
    """TouchPoint: each service is two calls, a token service then the service with `Authorization: Bearer <token>`. The recording keeps no token;
    the run asks the token service again and sends the service with the new one."""
    import sys
    import time as _time
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    from tests.test_webui import make_core
    sys.path.append(str(repo / "server"))
    from app.main import create_app
    from fastapi.testclient import TestClient

    app = create_app(tmp_path / "server.db")
    app.state.flow_builder = None
    Handler.seen.clear()
    with TestClient(app) as server, real_ie("/tokapp") as bridge:
        core, _ = make_core(tmp_path, ie_bridge=lambda: bridge, server_client=lambda url: _InProcessServer(server))
        for _ in range(75):
            tab = next((t for t in bridge.tabs() if "RookieE2E Tok" in t["title"]), None)
            if tab:
                break
            _time.sleep(0.2)
        assert tab, bridge.tabs()
        assert core.dispatch("POST", "/api/record/start", {"window": f"ie-tab:{tab['id']}", "requests": True})[0] == 200
        _time.sleep(1.0)
        os.environ["RK_VALUE"] = "0123456789"
        for action, wait in (("c-cif", 0.5), ("c-find", 2.5)):
            drive(action, "RookieE2E Tok")
            _time.sleep(wait)
        assert Handler.seen == ["0123456789"], Handler.seen
        old_jwt = Handler.jwt
        status, saved = core.dispatch("POST", "/api/record/stop", {"name": "tra cif token"})
        assert status == 200 and saved["requests_kept"] >= 2, saved
        status, shown = core.dispatch("POST", "/api/learn", {"ids": [saved["id"]], "title": "Tra CIF token"})
        assert status == 200 and shown["api_count"] >= 2, shown
        flow = core.store.get("flows")[0]
        on_disk = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in core.store.home.rglob("*") if p.is_file() and p.suffix in (".json", ".txt", ".jsonl"))
        assert old_jwt and old_jwt not in json.dumps(flow) and old_jwt not in on_disk and "Bearer ⟦l1⟧" in json.dumps(flow, ensure_ascii=False)
        name = flow["workflow"]["inputs"][0]["name"]
        Handler.seen.clear()
        status, reply = core.dispatch("POST", "/api/run/start", {"title": "Tra CIF token", "mode": "simulate", "window": f"ie-tab:{tab['id']}", "inputs": {name: "5566778899"}})
        assert status == 200, reply
        for _ in range(150):
            run = core.dispatch("GET", "/api/run/status", {})[1]
            if run.get("result"):
                break
            _time.sleep(0.2)
    assert run["result"]["status"] == "finished", run
    assert Handler.seen == ["5566778899"] and Handler.jwt != old_jwt, (Handler.seen, Handler.jwt, old_jwt)   # accepted: the token of this run, not the old one
    # one click that fires two calls (the token service, then the service) is ONE node that fires its batch: one step in the run, two calls inside
    listed = core.dispatch("GET", "/api/flows", {})[1]["flows"][0]["api_nodes"]
    batch = [n for n in listed if n["call_count"] == 2]
    assert len(batch) == 1 and all(c["ready"] for c in batch[0]["calls"]), listed
    assert [s["id"] for s in run["steps"]].count(batch[0]["id"]) == 1 and len(run["steps"]) == len(listed), (run["steps"], listed)
    sent = run["details"][batch[0]["id"]]["requests"]
    assert len(sent) == 2 and [r["status"] for r in sent] == [200, 200] and "state" not in sent[0], sent


def test_a_click_no_rule_names_asks_once_sends_after_chi_xem_and_the_next_run_does_not_ask(tmp_path):
    """The step is write only by default: the question is answered by the person, the calls are then really sent from the page (200),
    the confirmation is kept on the flow, and the next run sends them without a question."""
    import time as _time
    from tests.test_webui import make_core

    node = {"id": "a0", "step_id": "s1", "kind": "xhr", "group": "g1", "group_label": "Khách hàng lạ", "label": "x", "frame": "top", "method": "POST",
            "url": "/api/cif", "headers": "X-Test:1\nContent-Type:application/x-www-form-urlencoded\n", "body": "cif=4455667788", "links": {},
            "risk": "write", "complete": True, "answer": "", "ms": 1, "shape": None, "unresolved": []}
    workflow = {"engine": "ie", "status": "approved", "inputs": [], "steps": [
        {"id": "s1", "action": "click", "risk": "write", "mode": "approve", "target": {"selectors": ["x"], "label": "Khách hàng lạ", "tag": "button"}}]}
    with real_ie("/form") as bridge:
        core, _ = make_core(tmp_path, ie_bridge=lambda: bridge)
        core.store.put("flows", [{"title": "Khach", "steps": [], "inputs": [], "learned_at": "x", "workflow": workflow, "api": [node]}])
        tab = next(t for t in bridge.tabs() if "RookieE2E" in t["title"])
        start = {"title": "Khach", "mode": "simulate", "window": f"ie-tab:{tab['id']}", "inputs": {}}

        def wait(pred):
            for _ in range(150):
                run = core.dispatch("GET", "/api/run/status", {})[1]
                if pred(run):
                    return run
                _time.sleep(0.2)
            raise AssertionError(run)

        assert core.dispatch("POST", "/api/run/start", start)[0] == 200
        run = wait(lambda r: r.get("ask") or r.get("result"))
        assert run["ask"]["kind"] == "confirm_read", run
        assert core.dispatch("POST", "/api/run/decide", {"ask_id": run["ask"]["id"], "approve": True})[0] == 200
        run = wait(lambda r: r.get("result"))
        assert run["result"]["status"] == "finished" and run["details"]["g1"]["requests"][0]["status"] == 200, run
        core._run["thread"].join(5)
        assert core.store.get("flows")[0]["read_confirmed"]["s1"]["at"]
        assert core.dispatch("POST", "/api/run/start", {**start, "refresh": True})[0] == 200
        run = wait(lambda r: r.get("ask") or r.get("result"))
        assert run["ask"] is None and run["result"]["status"] == "finished" and run["details"]["g1"]["requests"][0]["status"] == 200, run


# ---- a report exported as a PDF: recorded, learned and run by request, the saved file equal to the served bytes (docs/design.md 6.4) ----------

def _quit_windows_of_this_site(port):
    """A window.open of the test opens one more IE window on this test's own site: closed too (matched by the site's port, never another window)."""
    for _ in range(6):
        if drive("quit", rf"127\.0\.0\.1:{port}") == "no window":
            break


@pytest.mark.parametrize("path_kind, field, button", [("xhr", "txtFrom", "btnXhr"), ("form", "txtFrom2", "btnForm")])
def test_a_pdf_answer_is_recorded_as_a_file_learned_and_run_by_request_and_the_saved_file_equals_the_served_bytes(tmp_path, path_kind, field, button):
    import sys
    import time as _time

    repo = Path(__file__).resolve().parents[2]
    from tests.test_webui import make_core
    sys.path.append(str(repo / "server"))
    from app.main import create_app
    from fastapi.testclient import TestClient

    app = create_app(tmp_path / "server.db")
    app.state.flow_builder = None
    Handler.seen.clear()
    folder = tmp_path / "Rookie"
    with TestClient(app) as server, real_ie("/export") as bridge:
        core, _ = make_core(tmp_path, ie_bridge=lambda: bridge, server_client=lambda url: _InProcessServer(server))
        core.store.put("download_folder", str(folder))
        for _ in range(75):
            tab = next((t for t in bridge.tabs() if "RookieE2E Export" in t["title"]), None)
            if tab:
                break
            _time.sleep(0.2)
        assert tab, bridge.tabs()
        try:
            assert core.dispatch("POST", "/api/record/start", {"window": f"ie-tab:{tab['id']}", "requests": True})[0] == 200
            _time.sleep(1.0)
            os.environ["RK_ID"], os.environ["RK_VALUE"] = field, "2026-01-31"
            drive("e-type", "RookieE2E Export")
            _time.sleep(0.5)
            os.environ["RK_ID"] = button
            drive("e-click", "RookieE2E Export")
            _time.sleep(7.0)                       # the page that left, or a window that opened, has no document to show: the recorder waits a few seconds for one
            assert any(s.startswith({"xhr": "xhr:", "form": "form:", "open": "win:"}[path_kind]) for s in Handler.seen), Handler.seen
            status, saved = core.dispatch("POST", "/api/record/stop", {"name": "xuat bao cao " + path_kind})
            assert status == 200, saved
            status, shown = core.dispatch("POST", "/api/learn", {"ids": [saved["id"]], "title": "Xuất báo cáo giao dịch"})
            assert status == 200, shown
            flow = core.store.get("flows")[0]
            nodes = [n for n in flow["api"] if n["kind"] == "file"]
            assert len(nodes) == 1, [(n["kind"], n["method"], n["url"]) for n in flow["api"]]
            node = nodes[0]
            assert node["via"] == path_kind and (node["file"]["guess"] is (path_kind != "xhr"))
            if path_kind == "xhr":
                assert node["file"]["ctype"] == "application/pdf" and node["file"]["size"] == len(PDF_BYTES) and node["method"] == "POST"
            on_disk = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in core.store.home.rglob("*") if p.is_file() and p.suffix in (".json", ".txt", ".jsonl"))
            assert "RKPDFMARK" not in on_disk and "RKPDFMARK" not in json.dumps(flow) and "NGUYEN VAN A" not in on_disk      # the file's content is kept nowhere
            assert flow["workflow"]["steps"][-1]["risk"] == "read", flow["workflow"]["steps"][-1]   # «Xuất báo cáo» is a read
            inputs = {i["name"]: "2026-02-15" for i in flow["workflow"]["inputs"]}
            Handler.seen.clear()
            status, reply = core.dispatch("POST", "/api/run/start", {"title": "Xuất báo cáo giao dịch", "mode": "simulate", "window": f"ie-tab:{tab['id']}", "inputs": inputs})
            assert status == 200, reply
            for _ in range(200):
                run = core.dispatch("GET", "/api/run/status", {})[1]
                if run.get("result"):
                    break
                _time.sleep(0.2)
            core._run["thread"].join(5)
        finally:
            _quit_windows_of_this_site(bridge.test_port)
    assert run["result"]["status"] == "finished", run
    made = list(folder.glob("Xuất báo cáo giao dịch-*.pdf"))
    assert len(made) == 1 and made[0].read_bytes() == PDF_BYTES, (made, run)                       # every byte as the server sent it
    assert len(Handler.seen) == 1, Handler.seen
    if inputs:
        assert "2026-02-15" in Handler.seen[0], Handler.seen                                          # this run's value, not the recorded one
    shown = next(r for d in run["details"].values() for r in d["requests"] if r.get("file"))
    assert shown["file"]["saved"] is True and shown["file"]["size"] == len(PDF_BYTES) and "view" not in shown


DATEPICK = b"""<html><head><title>RookieE2E Datepick</title></head><body>
<input type="text" id="txtFrom"><img id="imgdtFrom" src="about:blank" width="16" height="16" alt="" onclick="openPicker()">
<div id="cal"></div>
<script>function pick() { document.getElementById('txtFrom').value = '17/11/2026'; }
function openPicker() {   // the picker is built when its icon is pressed, with the frame it always has (an IE trick for covering a select)
  document.getElementById('cal').innerHTML = '<iframe name="calFrame" id="calFrame" src="javascript:false;" style="width:200px;height:120px"></iframe>' +
    '<div id="d17" onclick="pick()">17</div>'; }</script></body></html>"""
PAGES["/datepick"] = DATEPICK


def test_a_date_picker_frame_at_a_script_address_is_not_recorded_as_a_request():
    with real_ie("/datepick") as bridge:
        session = start_session(bridge, requests=True)
        time.sleep(1.0)
        os.environ["RK_ID"] = "imgdtFrom"
        drive("e-click", "RookieE2E Datepick")
        time.sleep(1.5)
        os.environ["RK_ID"] = "d17"
        drive("e-click", "RookieE2E Datepick")
        time.sleep(1.0)
        session.stop()
    assert not any(str(r.get("url")).lower().startswith("javascript:") for r in session.requests), [r.get("url") for r in session.requests]


SESSLINK = b"""<html><head><title>RookieE2E Sesslink</title></head><body>
<a id="lnkAcct" href="/touchpoint/locate/accountLocatePRF.jsp?sessionId=LIVE777&lang=vi" target="work">Tai khoan</a>
<form id="frmX" method="post" action="/touchpoint/other.jsp?sessionId=LIVE777"><input type="hidden" name="a" value="1"></form>
<input type="button" id="btnAjax" value="ajax" onclick="var x = new XMLHttpRequest(); x.open('GET', '/api/ping?sessionId=LIVE777&t=1', true); x.send(null);">
<iframe name="work" src="/blank?sessionId=LIVE777" style="width:200px;height:50px"></iframe></body></html>"""
PAGES["/sesslink"] = SESSLINK


def test_the_addresses_with_a_session_value_that_the_live_page_shows_or_used_are_readable_by_the_run():
    from rookie_agent.ie import replay

    with real_ie("/sesslink") as bridge:
        tab = None
        for _ in range(25):
            tab = next((t for t in bridge.tabs() if "RookieE2E" in t["title"]), None)
            if tab:
                break
            time.sleep(0.4)
        assert tab
        bridge.bind(tab["id"], peek=True)
        os.environ["RK_ID"] = "btnAjax"
        drive("e-click", "RookieE2E Sesslink")
        time.sleep(1.5)
        urls = bridge.live_urls()
    text = "\n".join(urls)
    assert "accountLocatePRF.jsp?sessionId=LIVE777" in text and "other.jsp?sessionId=LIVE777" in text and "/api/ping?sessionId=LIVE777" in text, urls
    node = {"url": "/touchpoint/locate/accountLocatePRF.jsp?sessionId=⟦l1⟧&lang=vi", "body": ""}
    assert replay._live_query_value(node, "l1", urls) == "LIVE777"


def test_a_press_is_in_the_recorders_queue_before_the_page_script_that_it_started_waits():
    """Tick a row, press «In báo nợ/có» whose own script waits (a dialog): the press must already be recorded when the wait begins, and once only."""
    Handler.seen.clear()
    with real_ie("/waiting") as bridge:
        session = start_session(bridge, requests=True)
        time.sleep(1.0)
        os.environ["RK_ID"] = "chkRow"
        drive("e-click", "RookieE2E Waiting")
        time.sleep(1.0)
        os.environ["RK_ID"] = "btnWait"
        drive("e-click", "RookieE2E Waiting")
        time.sleep(2.0)
        session.stop()
    assert any(x.startswith("/api/mark") for x in Handler.seen), Handler.seen
    kinds = [(line.get("kind"), line.get("id") or line.get("url")) for line in session.raw]
    press = next((i for i, k in enumerate(kinds) if k == ("click", "btnWait")), None)
    asked = next((i for i, k in enumerate(kinds) if k[0] == "ajax" and "/api/mark" in str(k[1])), None)
    assert press is not None and asked is not None and press < asked, kinds      # the press comes before the request its own script made
    ids = [line.get("id") for line in session.raw if line.get("kind") == "click"]
    assert ids.count("chkRow") == 1 and ids.count("btnWait") == 1, ids


def test_a_page_shown_in_a_dialog_that_opens_while_recording_is_recorded_with_its_requests(tmp_path):
    """The dialog of IE is a window Shell.Application does not list: the recorder finds it by its class and puts itself in its document."""
    Handler.seen.clear()
    with real_ie("/waiting") as bridge:
        session = start_session(bridge, requests=True)
        host = tmp_path / "dlg.hta"
        host.write_text('<html><head><HTA:APPLICATION ID="x" /></head><body><script>window.setTimeout(function () { window.showModelessDialog("http://127.0.0.1:%d/dlgviewer", null, "dialogWidth:300px;dialogHeight:200px"); }, 500);'
                        'window.setTimeout(function () { window.close(); }, 12000);</script></body></html>' % bridge.test_port, encoding="utf-8")
        process = subprocess.Popen(["mshta.exe", str(host)])
        try:
            time.sleep(8.0)
            session.stop()
        finally:
            process.kill()
    assert any("/api/exportpdf?from=dlg" in str(r.get("url")) for r in session.requests), (session.requests, session.notes)


def test_the_address_of_a_message_box_dialog_is_not_a_request_but_the_address_of_a_report_dialog_is():
    with real_ie("/dlgcall") as bridge:
        session = start_session(bridge, requests=True)
        time.sleep(1.0)
        for button in ("btnMsg", "btnRpt"):
            os.environ["RK_ID"] = button
            drive("e-click", "RookieE2E Dlgcall")
            time.sleep(1.0)
        session.stop()
    urls = [str(line.get("url")) for line in session.raw if line.get("kind") == "open"]
    assert any("viewReport.jsp" in u for u in urls) and not any("dlgMessageBox" in u for u in urls), urls


def test_a_message_box_dialog_that_opens_while_recording_is_left_out_of_the_recording(tmp_path):
    Handler.seen.clear()
    with real_ie("/waiting") as bridge:
        session = start_session(bridge, requests=True)
        host = tmp_path / "dlg.hta"
        host.write_text('<html><head><HTA:APPLICATION ID="x" /></head><body><script>window.setTimeout(function () { window.showModelessDialog("http://127.0.0.1:%d/touchpoint/utilities/dlgMessageBox.jsp", null, "dialogWidth:300px;dialogHeight:200px"); }, 500);'
                        'window.setTimeout(function () { window.close(); }, 12000);</script></body></html>' % bridge.test_port, encoding="utf-8")
        process = subprocess.Popen(["mshta.exe", str(host)])
        try:
            time.sleep(8.0)
            session.stop()
        finally:
            process.kill()
    assert not any("/api/exportpdf?from=dlg" in str(r.get("url")) for r in session.requests), session.requests       # the message box is not recorded: its request is not
