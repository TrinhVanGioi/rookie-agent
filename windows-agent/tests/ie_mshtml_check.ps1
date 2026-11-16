# Runs page_recorder.js in the real MSHTML engine (the object `htmlfile`, quirks mode like the IE pages) and prints what it recorded.
# Used by test_ie_bridge.py. Needs -Sta. No window is opened.
param([string]$JsPath)
$js = [string][IO.File]::ReadAllText($JsPath)   # a plain string: one straight from Get-Content hangs COM
$h = New-Object -ComObject htmlfile
$h.IHTMLDocument2_write('<html><head><title>Main</title></head><body><table><tr><td>Ma khach hang:</td><td><input type="text" id="txtCustomerId" name="txtPartyID"></td></tr><tr><td>Mat khau</td><td><input type="password" id="pw" name="pw"></td></tr><tr><td>So tien</td><td><input type="text" id="amt" name="amt"></td></tr></table><input type="hidden" name="appPasswd" value="SECRET1"><button id="btnSave">LUU</button><table><tr><td id="tabHoSo" style="cursor:pointer">Ho so</td><td id="tabTin" style="cursor:pointer">Thong tin tai</td></tr></table><div id="plain">Chi la chu, khong bam duoc</div><table><tr id="row1" style="cursor:pointer"><td>-3864</td><td>DDA</td><td>9.998.920.766</td></tr></table><span id="inner" style="cursor:pointer"><b id="bold">Duy tri</b></span></body></html>')
$h.IHTMLDocument2_close()
$win = $h.parentWindow
$win.execScript($js, 'javascript')
$win.execScript(@'
var H = window.__rkHandlers; var doc = document;
function fin(el){ H.focusin({srcElement: el}); } function fout(el){ H.focusout({srcElement: el}); }
var a=document.getElementById("txtCustomerId"), pw=document.getElementById("pw"), amt=document.getElementById("amt"), b=document.getElementById("btnSave"), hid=document.getElementsByName("appPasswd")[0];
fin(a); a.value="0123456789"; fout(a);
fin(pw); pw.value="TOPSECRET"; fout(pw);
H.keydown({srcElement: pw, keyCode: 13});
fin(amt); amt.value="5000000"; H.keydown({srcElement: amt, keyCode: 13});
H.click({srcElement: b});
H.click({srcElement: hid});
H.click({srcElement: doc.getElementById("tabHoSo")});
H.click({srcElement: doc.getElementById("plain")});
H.click({srcElement: doc.getElementById("row1").cells[2]});
H.click({srcElement: doc.getElementById("bold")});
window.__out = window.__rkTake();
window.__flags = document.compatMode + "|" + typeof JSON + "|" + typeof document.addEventListener;
'@, 'javascript')
[Console]::Out.WriteLine("FLAGS " + [System.__ComObject].InvokeMember('__flags', 'GetProperty', $null, $win, $null))
[Console]::Out.WriteLine([System.__ComObject].InvokeMember('__out', 'GetProperty', $null, $win, $null))
