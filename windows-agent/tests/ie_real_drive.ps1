param([string]$Action, [string]$Match = '')
$shell = New-Object -ComObject Shell.Application
$w = $null
foreach ($x in $shell.Windows()) { try { if ($x.FullName -match 'iexplore' -and $x.LocationName -match $Match) { $w = $x } } catch { } }
if ($null -eq $w) { Write-Output "no window"; exit 2 }
$d = $w.Document
Add-Type -Namespace RK -Name U -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); [DllImport("user32.dll")] public static extern void SwitchToThisWindow(IntPtr h, bool alt);'
if ($Action -ne 'quit' -and $Action -ne 'title') { [RK.U]::SwitchToThisWindow([IntPtr]$w.HWND, $true); [void][RK.U]::SetForegroundWindow([IntPtr]$w.HWND); Start-Sleep -Milliseconds 500 }
Add-Type -Namespace RK -Name W -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
[DllImport("user32.dll")] public static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, string cls, string win);
[DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr h, System.Text.StringBuilder s, int n);
'@
function Find-Child($parent, [string]$cls) {
  $c = [RK.W]::FindWindowEx($parent, [IntPtr]::Zero, [NullString]::Value, [NullString]::Value)
  while ($c -ne [IntPtr]::Zero) {
    $sb = New-Object System.Text.StringBuilder 256
    [void][RK.W]::GetClassName($c, $sb, 256)
    if ($sb.ToString() -eq $cls) { return $c }
    $r = Find-Child $c $cls
    if ($r -ne [IntPtr]::Zero) { return $r }
    $c = [RK.W]::FindWindowEx($parent, $c, [NullString]::Value, [NullString]::Value)
  }
  return [IntPtr]::Zero
}
# Focus and blur as the page sees them. When Windows does not let the test window come to the front, IE sends no focus events at
# all; so the same events are always sent into the field by a script in the page too (at worst a line `focus` or `blur` twice), and
# what is tested (the recorder's handling of focus, typing and leaving a field) does not depend on which window the person at the PC uses.
function Send-FocusEvent($doc, $el, [string]$name) {
  $id = [string]$el.id
  $js = "var e = document.getElementById('" + $id + "'); if (e) { if (e.fireEvent) { try { e.fireEvent('on" + $name + "'); } catch (x) {} } if (document.createEvent && !document.attachEvent) { var ev = document.createEvent('Event'); ev.initEvent('" + $name + "', true, false); e.dispatchEvent(ev); } }"
  $null = $doc.parentWindow.execScript($js, 'javascript')
}
# A person's press starts with the mouse button going down (or a key): the recorder tells the teller's focus changes from the ones the
# page's own script makes by that. $id empty: the press lands on the page itself (a click somewhere else, which takes the cursor away).
function Send-MouseDown($doc, [string]$id) {
  $js = "var e = document.getElementById('" + $id + "') || document.body; if (e.fireEvent) { try { e.fireEvent('onmousedown'); } catch (x) {} } if (document.createEvent && !document.attachEvent) { var ev = document.createEvent('MouseEvents'); ev.initEvent('mousedown', true, true); e.dispatchEvent(ev); }"
  $null = $doc.parentWindow.execScript($js, 'javascript')
}
function Do-Focus($doc, $el) { Send-MouseDown $doc ([string]$el.id); $el.focus(); Send-FocusEvent $doc $el 'focusin'; Start-Sleep -Milliseconds 60 }   # a person needs far more than this between the cursor entering a field and the first key
function Do-Blur($doc, $el) { Send-MouseDown $doc ''; $el.blur(); Send-FocusEvent $doc $el 'focusout' }
function Get-Frame($doc, [string]$path) {
  $win = $doc.parentWindow
  foreach ($n in $path.Split('/')) { $win = $win.frames.item($n) }
  return $win.document
}
switch ($Action) {
  'plant-stale' {
    $js = @'
var line = '{"t":' + (new Date().getTime() - 60000) + ',"kind":"click","frame":"top","title":"x","tag":"button","type":"button","id":"staleBtn","name":null,"label":"OLD","pos":0,"value":null,"ctl":true}\n';
document.cookie = '__rkkeep=' + encodeURIComponent(line) + '; path=/';
'@
    $null = $d.parentWindow.execScript([string]$js, 'javascript')
  }
  'f-role-lang' { $fd = Get-Frame $d 'desktopFrame/rhidden'; $s = $fd.getElementById('cboLanguages'); Do-Focus $fd $s; $s.selectedIndex = 1; $s.fireEvent('onchange') }  # the page reloads its frame on change: no blur ever happens
  'f-logoff'    { $fd = Get-Frame $d 'desktopFrame/rhidden'; $e = $fd.getElementById('btnLogoff'); $e.focus(); $e.click() }
  'f-ok'        { $fd = Get-Frame $d 'desktopFrame/rhidden'; $e = $fd.getElementById('btnSelect'); $e.focus(); $e.click() }
  'click-label' { $d.getElementById('lblUser').click() }
  's-acct'    { $fd = Get-Frame $d 'main'; $e = $fd.getElementById('txtAcct'); Do-Focus $fd $e; $e.value = $env:RK_VALUE; Do-Blur $fd $e }
  's-copy'    { $fd = Get-Frame $d 'main'; $e = $fd.getElementById('txtCopy'); Do-Focus $fd $e; $e.value = $env:RK_COPY; Do-Blur $fd $e }
  's-find'    { $fd = Get-Frame $d 'main'; $e = $fd.getElementById('btnFind'); Send-MouseDown $fd 'btnFind'; $e.focus(); $e.click() }
  's-acct-stay' { $fd = Get-Frame $d 'main'; $e = $fd.getElementById('txtAcct'); Do-Focus $fd $e; $e.value = $env:RK_VALUE }   # typed, and the cursor stays in the field
  'js-main'   { $fd = Get-Frame $d 'main'; $null = $fd.parentWindow.execScript([string]$env:RK_JS, 'javascript'); Write-Output ([System.__ComObject].InvokeMember('__res', 'GetProperty', $null, $fd.parentWindow, $null)) }
  'open-tab'  { $w.Navigate2($env:RK_URL, 0x800) }   # navOpenInNewTab: as a link that opens in a new tab does
  'a-nav'     { $e = $d.getElementById('btnNav'); $e.focus(); $e.click() }
  'a-pw'      { $e = $d.getElementById('btnPw'); $e.focus(); $e.click() }
  'a-native'  { $e = $d.getElementById('btnNative'); $e.focus(); $e.click() }
  'a-active'  { $e = $d.getElementById('btnActive'); $e.focus(); $e.click() }
  'a-fail'    { $e = $d.getElementById('btnFail'); $e.focus(); $e.click() }
  'type-user' { $e = $d.getElementById('txtUser'); Do-Focus $d $e; $e.value = 'teller01'; Do-Blur $d $e }
  'enter-pw'  {
    $e = $d.getElementById('txtPw'); $e.focus()
    $page = Find-Child ([IntPtr]$w.HWND) 'Internet Explorer_Server'
    if ($page -eq [IntPtr]::Zero) { Write-Output 'no page window'; exit 3 }
    [void][RK.W]::PostMessage($page, 0x100, [IntPtr]13, [IntPtr]0x001C0001)
    [void][RK.W]::PostMessage($page, 0x102, [IntPtr]13, [IntPtr]0x001C0001)
    [void][RK.W]::PostMessage($page, 0x101, [IntPtr]13, [IntPtr]0xC01C0001)
  }
  'tree'      {
    function Show-Tree($parent, $depth) {
      $c = [RK.W]::FindWindowEx($parent, [IntPtr]::Zero, [NullString]::Value, [NullString]::Value)
      while ($c -ne [IntPtr]::Zero) {
        $sb = New-Object System.Text.StringBuilder 256
        [void][RK.W]::GetClassName($c, $sb, 256)
        Write-Output (('  ' * $depth) + $sb.ToString())
        if ($depth -lt 6) { Show-Tree $c ($depth + 1) }
        $c = [RK.W]::FindWindowEx($parent, $c, [NullString]::Value, [NullString]::Value)
      }
    }
    Write-Output ("HWND=" + $w.HWND)
    Show-Tree ([IntPtr]$w.HWND) 0
  }
  'type-pw'   { $e = $d.getElementById('txtPw'); Do-Focus $d $e; $e.value = 'TOPSECRET'; Do-Blur $d $e }
  'click-login' { $e = $d.getElementById('btnLogin'); $e.focus(); $e.click() }
  'role-lang' { $s = $d.getElementById('cboLanguages'); $s.focus(); $s.selectedIndex = 1; $s.blur() }
  'click-ok'  { $e = $d.getElementById('btnSelect'); $e.focus(); $e.click() }
  'quit'      { $w.Quit() }
  'js'        { $null = $d.parentWindow.execScript([string]$env:RK_JS, 'javascript'); Write-Output ([System.__ComObject].InvokeMember('__res', 'GetProperty', $null, $d.parentWindow, $null)) }
  'cookie'    { Write-Output $d.cookie }
  'title'     { Write-Output $w.LocationName }
}
