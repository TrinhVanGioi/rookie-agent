# Bridge between the agent (Python) and the pages open in Internet Explorer.
# Runs as a child process of the agent, started with -Sta. One JSON object per line on stdin, one reply per line on stdout.
# Everything on the pipe is ASCII (non-ASCII is written as \uXXXX), so no code page can spoil it.
#
# What was learned the hard way on real MSHTML (see docs/design.md 3C):
#   - the script text passed to execScript must be a plain [string]; a string straight from Get-Content hangs COM;
#   - expando properties and functions of the page are reached with InvokeMember, not with the dot syntax;
#   - the page is in quirks mode (old JScript), see page_recorder.js.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$recorderJs = [string][IO.File]::ReadAllText((Join-Path $here "page_recorder.js"))
$shell = New-Object -ComObject Shell.Application
# The dialogs of IE (showModalDialog, showModelessDialog) are windows of their own that Shell.Application does not list. They are found by their
# window class, and their document is taken from the window with the message IE answers for the accessibility API (WM_HTML_GETOBJECT).
# Any failure here leaves the recording as it was (no dialogs): $dialogsOk stays false.
$script:dialogsOk = $false
$script:dialogsTried = $false
# Compiled the first time it is needed (Ghi, Soi), not when the bridge starts: the compiler takes a second or two.
function Enable-Dialogs {
  if ($script:dialogsTried) { return }
  $script:dialogsTried = $true
  try {
    Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class RkDialogs {
    delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc p, IntPtr l);
    [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr parent, EnumProc p, IntPtr l);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] static extern uint RegisterWindowMessage(string s);
    [DllImport("user32.dll")] static extern IntPtr SendMessageTimeout(IntPtr h, uint msg, IntPtr w, IntPtr l, uint flags, uint timeout, out IntPtr result);
    [DllImport("oleacc.dll")] static extern int ObjectFromLresult(IntPtr lres, ref Guid riid, IntPtr wParam, [MarshalAs(UnmanagedType.IDispatch)] out object obj);
    static string ClassOf(IntPtr h) { var b = new StringBuilder(256); GetClassName(h, b, 256); return b.ToString(); }
    // the "Internet Explorer_Server" window inside each dialog frame that is open now
    public static List<long> Servers() {
        var found = new List<long>();
        EnumWindows(delegate(IntPtr top, IntPtr l1) {
            if (ClassOf(top) == "Internet Explorer_TridentDlgFrame") {
                EnumChildWindows(top, delegate(IntPtr child, IntPtr l2) {
                    if (ClassOf(child) == "Internet Explorer_Server") { found.Add(child.ToInt64()); return false; }
                    return true;
                }, IntPtr.Zero);
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }
    public static object DocumentOf(long server) {
        IntPtr result;
        uint message = RegisterWindowMessage("WM_HTML_GETOBJECT");
        if (SendMessageTimeout(new IntPtr(server), message, IntPtr.Zero, IntPtr.Zero, 2, 1500, out result) == IntPtr.Zero) { return null; }
        Guid iid = new Guid("626FC520-A41E-11CF-A731-00A0C9082637");   // IHTMLDocument2
        object doc;
        if (ObjectFromLresult(result, ref iid, IntPtr.Zero, out doc) != 0) { return null; }
        return doc;
    }
    public static bool Alive(long server) { return IsWindow(new IntPtr(server)); }
}
"@
    $script:dialogsOk = $true
  } catch { $script:dialogsOk = $false }
}
function New-DialogTarget([long]$server) {
    $o = New-Object psobject -Property @{ Hwnd = $server; Dlg = $true }
    # the document is taken again at each use: a dialog that goes to another page has a new document
    $o | Add-Member -MemberType ScriptProperty -Name Document -Value { try { [RkDialogs]::DocumentOf([long]$this.Hwnd) } catch { $null } }
    return $o
}
$bound = $null          # the window (tab) being recorded
$skipped = New-Object System.Collections.ArrayList   # frames that could not be read in this look (for the log)
$diagText = ""
$lastDiag = ""

function Ascii([string]$json) {
    return [regex]::Replace($json, '[^\x00-\x7F]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
}
function Reply($object) {
    [Console]::Out.WriteLine((Ascii (ConvertTo-Json -InputObject $object -Compress -Depth 8)))
    [Console]::Out.Flush()
}
function Get-Prop($object, [string]$name) {
    try { return [System.__ComObject].InvokeMember($name, 'GetProperty', $null, $object, $null) } catch { return $null }
}
function Invoke-Method($object, [string]$name) {
    try { return [System.__ComObject].InvokeMember($name, 'InvokeMethod', $null, $object, $null) } catch { return $null }
}

# Every window of the page: the top one and the frames inside it, to any depth (up to 8).
function Get-Windows($win, [int]$depth = 0) {
    $list = New-Object System.Collections.ArrayList
    [void]$list.Add($win)
    if ($depth -lt 8) {
        $count = 0
        try { $count = [int]$win.frames.length } catch { }
        for ($i = 0; $i -lt $count; $i++) {
            try { foreach ($child in (Get-Windows $win.frames.item($i) ($depth + 1))) { [void]$list.Add($child) } }
            catch { [void]$script:skipped.Add("frame #$i unreadable: " + [string]$_.Exception.Message) }
        }
    }
    return $list
}

function Get-IeTabs {
    $tabs = @()
    $index = 0
    foreach ($w in $shell.Windows()) {
        $index++
        try {
            if ($w.FullName -notmatch 'iexplore') { continue }
            $null = $w.Document.parentWindow   # a tab that is not a web page (a folder) is left out
            $hostName = ''; try { $hostName = ([uri][string]$w.LocationURL).Host } catch { }
            $tabs += [pscustomobject]@{ id = $index; title = [string]$w.LocationName; host = $hostName; window = $w }
        } catch { }
    }
    return $tabs
}

$script:peek = $false   # a run of the API flow: the page's requests are only remembered in its memory (last bodies per path), never recorded
$script:hookRequests = $false   # recording hooks the page's requests only when the person asked for it: the hook is what can upset a page
$script:diagMode = ""   # "none": nothing is run in the page; "nolisten": the recorder is put in but listens to nothing (to find what upsets a page)
function RunFlags() { if ($script:peek) { return 'window.__rkRunMode = true;' } return 'window.__rkRunMode = true; window.__rkNoXhr = true;' }

function Inject($win, [bool]$late = $true, [bool]$force = $false) {
    if ($script:diagMode -eq 'none') { return $null }
    # Once the recorder is in a document, nothing is run there again at each look (it was: the whole recorder, in every frame, every
    # 150 ms, also while the page's own script waited in a dialog). Reading the marker runs no script. $force: Ghi and the runner,
    # which change the mode of a recorder that is already in (record again after Dung ghi; run).
    if (-not $force -and (Get-Prop $win '__rkOn') -eq $true) { return $null }
    # The recorder goes only into a document that has finished loading ("complete"): running a script into a page that is still writing itself
    # or still calling the server can upset it (TouchPoint's frame "main" was "loading" at the very second its script error was reported).
    # $late: the page waited too long for a frame, so one that has been read ("interactive", "loaded") is accepted too; one still being read never.
    try {
        $state = [string]$win.document.readyState
        if ($state -ne 'complete' -and -not ($late -and ($state -eq 'interactive' -or $state -eq 'loaded'))) { return $null }
    } catch { }
    try {
        if (-not $script:hookRequests -and -not $script:peek) { $null = $win.execScript("window.__rkNoXhr = true;", 'javascript') }
        $only = [string]$env:ROOKIE_IE_LISTEN -replace '[^a-z,]', ''   # to find which listener upsets a page: "none" or e.g. "click,keydown"
        if ($script:diagMode -eq 'nolisten') { $only = 'none' }
        $groups = @{ 'only-click' = 'click,dblclick'; 'only-key' = 'keydown'; 'only-field' = 'focusin,focusout,change'; 'only-page' = 'load,unload' }
        $groups['only-focusin'] = 'focusin'; $groups['only-focusout'] = 'focusout'; $groups['only-change'] = 'change'; $groups['field-empty'] = 'focusin,focusout,change'
        if ($groups.ContainsKey($script:diagMode)) { $only = $groups[$script:diagMode] }
        $bodies = @{ 'body-prop' = 'prop'; 'body-label' = 'label'; 'body-place' = 'place'; 'body-uid' = 'uid'; 'body-value' = 'value'; 'body-meta' = 'meta' }
        if ($bodies.ContainsKey($script:diagMode)) { $only = 'focusin,focusout,change'; $null = $win.execScript("window.__rkBody = '" + $bodies[$script:diagMode] + "';", 'javascript') }
        if ($script:diagMode -eq 'field-empty') { $null = $win.execScript("window.__rkEmpty = true;", 'javascript') }
        if ($only) { $null = $win.execScript("window.__rkOnly = '$only';", 'javascript') }
        $null = $win.execScript($recorderJs, 'javascript'); return $null }   # execScript returns a value: it must not reach the output
    catch { return [string]$_.Exception.Message }
}

# One line per window and frame: where it is (host only, never the path or the query), how far it has loaded, whether
# the recorder listens in it. Sent with a poll only when it changed, so the log shows what the recorder could and could not reach.
function Describe-Reach($w, $injectError) {
    $host_ = "?"; $ready = "?"; $mode = "?"; $name = ""
    try { $name = [string]$w.name } catch { }
    try { $host_ = ([uri][string]$w.document.location.href).Host } catch { }
    try { $ready = [string]$w.document.readyState; $mode = [string]$w.document.documentMode } catch { }
    $how = Get-Prop $w '__rkAttached'
    # An error the recorder caught inside the page (a handler that failed while recording an action): read once, then cleared.
    $caught = [string](Get-Prop $w '__rkErr')
    if ($caught) { try { $null = $w.execScript("window.__rkErr = '';", 'javascript') } catch { } }
    return "frame='$name' host=$host_ ready=$ready mode=$mode listen=$how" + $(if ($injectError) { " inject_error=$injectError" } else { "" }) + $(if ($caught) { " recorder_error=" + $caught.Replace('|', '/') } else { "" })
}

# What is recorded is the chosen tab and every IE window that opens after Ghi starts (the role / language / location
# window of a login, a pop-up). A window that closes is dropped; recording goes on in the others.
$targets = New-Object System.Collections.ArrayList
$baseline = @{}   # windows that were open at Ghi and are not the chosen tab: never recorded
$known = @{}

function Get-Key($w) {
    # Tells one tab from another: the frame window handle (a pop-up has a new one) and the identity of the tab itself. The tabs of one
    # IE window share the handle, so the handle alone took a screen that opens in a NEW TAB (the next screen of a sign in) for the
    # tab being recorded and never recorded it. Stable between looks.
    try {
        $frame = [string][int64]$w.HWND
        $unknown = [System.Runtime.InteropServices.Marshal]::GetIUnknownForObject($w)
        [void][System.Runtime.InteropServices.Marshal]::Release($unknown)
        return $frame + ":" + [string][int64]$unknown
    } catch { return $null }
}

function Update-Targets {
    foreach ($w in $shell.Windows()) {
        try {
            if ($w.FullName -notmatch 'iexplore') { continue }
            $key = Get-Key $w
            if (-not $key -or $baseline.ContainsKey($key) -or $known.ContainsKey($key)) { continue }
            $null = $w.Document.parentWindow    # a window still loading throws here: it is taken on a later poll
            $known[$key] = $true
            [void]$targets.Add($w)
        } catch { }
    }
    if ($script:dialogsOk) {
        try {
            foreach ($server in [RkDialogs]::Servers()) {
                $key = "dlg:" + $server
                if ($baseline.ContainsKey($key) -or $known.ContainsKey($key)) { continue }
                $known[$key] = $true
                [void]$targets.Add((New-DialogTarget $server))
            }
        } catch { }
    }
}

# Whether a window with all its frames has finished loading: "ready" (all complete), "wait" (not yet), "late" (waited over 6 s: take what has been read).
$script:waiting = @{}
function Get-PageState($frames, $key) {
    $all = $true
    foreach ($f in $frames) { try { if ([string]$f.document.readyState -ne 'complete') { $all = $false; break } } catch { $all = $false; break } }
    if ($all) { $script:waiting.Remove($key); return 'ready' }
    if (-not $script:waiting.ContainsKey($key)) { $script:waiting[$key] = Get-Date }
    if (((Get-Date) - $script:waiting[$key]).TotalSeconds -gt 6) { return 'late' }
    return 'wait'
}

function Collect {
    $lines = @()
    $script:skipped.Clear()
    $diag = New-Object System.Collections.ArrayList
    Update-Targets
    $n = 0
    foreach ($t in @($targets)) {
        $n++
        $top = $null
        try { $top = $t.Document.parentWindow } catch { }
        if ($null -eq $top) {
            # A page that is changing (the sign in leads to the next screen) has no document for a moment: that is not a closed
            # window. Only a window that is no longer among the open ones is dropped; a dropped one would never be taken again.
            if ($t.PSObject.Properties['Dlg']) {
                if ([RkDialogs]::Alive([long]$t.Hwnd)) { [void]$diag.Add("window $n (dialog) changing page"); continue }
                $targets.Remove($t); [void]$diag.Add("window $n (dialog) closed"); continue
            }
            $tkey = Get-Key $t; $still = $false
            if ($tkey) { foreach ($open in $shell.Windows()) { try { if ((Get-Key $open) -eq $tkey) { $still = $true; break } } catch { } } }
            if ($still) { [void]$diag.Add("window $n changing page"); continue }
            $targets.Remove($t); [void]$diag.Add("window $n closed"); continue
        }
        $frames = @(Get-Windows $top)
        $tkey = Get-Key $t; if (-not $tkey) { $tkey = "t$n" }
        $pageState = Get-PageState $frames $tkey
        foreach ($w in $frames) {
            $err = $null
            if ($pageState -ne 'wait') { $err = Inject $w ($pageState -eq 'late') }   # a frame that has just loaded a new page has no recorder yet; one that has it ignores this
            [void]$diag.Add("window $n " + (Describe-Reach $w $err))
            $text = Invoke-Method $w '__rkTake'   # also takes back the lines a closed window or an old page left behind
            if ($text) { $lines += ([string]$text).Split("`n", [StringSplitOptions]::RemoveEmptyEntries) }
        }
    }
    foreach ($s in $script:skipped) { [void]$diag.Add($s) }
    $script:diagText = ($diag -join " | ")
    return $lines
}

function Invoke-MethodArgs($object, [string]$name, [object[]]$arguments) {
    try { return [System.__ComObject].InvokeMember($name, 'InvokeMethod', $null, $object, $arguments) } catch { return $null }
}

$runTab = $null   # the tab the agent drives when it runs a flow (not the one it records)

function Describe($tab) {
    $script:skipped.Clear()
    $frames = @(); $inputs = 0; $buttons = 0; $objects = 0
    foreach ($w in (Get-Windows $tab.window.Document.parentWindow)) {
        try {
            $doc = $w.document
            $name = [string]$w.name
            $visible = 0
            foreach ($e in $doc.getElementsByTagName('input')) { if ($e.type -ne 'hidden') { $visible++ } }
            $inputs += $visible
            $buttons += @($doc.getElementsByTagName('button')).Count
            $objects += @($doc.getElementsByTagName('object')).Count + @($doc.getElementsByTagName('applet')).Count
            # What the page holds, to see why a screen is not recorded: counts by tag, and the id and name (never the value or the
            # text) of the first controls. The host only, never the path or the query.
            $counts = @{}
            foreach ($tagName in 'select', 'textarea', 'input', 'button', 'a', 'iframe', 'frame', 'object', 'embed', 'applet', 'img', 'table', 'form') {
                $counts[$tagName] = @($doc.getElementsByTagName($tagName)).Count
            }
            $controls = @()
            foreach ($tagName in 'select', 'input', 'textarea', 'button') {
                foreach ($e in $doc.getElementsByTagName($tagName)) {
                    if ($controls.Count -ge 40) { break }
                    $shown = $false; try { $shown = ([int]$e.offsetWidth -gt 0 -and [int]$e.offsetHeight -gt 0) } catch { }
                    $options = 0; if ($tagName -eq 'select') { try { $options = [int]$e.options.length } catch { } }
                    $controls += @{ tag = $tagName; type = [string]$e.type; id = [string]$e.id; name = [string]$e.name; visible = $shown; options = $options }
                }
            }
            # The size of the frame as the teller sees it: a frame of 0 x 0 is not on the screen.
            $size = ''; try { $fe = $w.frameElement; $size = "$([int]$fe.offsetWidth)x$([int]$fe.offsetHeight)" } catch { }
            $hostName = ''; try { $hostName = ([uri][string]$doc.location.href).Host } catch { }
            $frames += [pscustomobject]@{ name = $name; mode = [int]$doc.documentMode; inputs = $visible; host = $hostName; ready = [string]$doc.readyState; size = $size; counts = $counts; controls = $controls }
        } catch { [void]$script:skipped.Add("frame '" + [string]$w.name + "' not readable: " + [string]$_.Exception.Message) }
    }
    return [pscustomobject]@{ frames = $frames; inputs = $inputs; buttons = $buttons; objects = $objects; unreadable = @($script:skipped) }
}

Reply @{ ok = $true; ready = $true }
while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    try {
        $request = ConvertFrom-Json -InputObject $line
        switch ($request.cmd) {
            'ping' { Reply @{ ok = $true } }
            'tabs' {
                Reply @{ ok = $true; tabs = @(Get-IeTabs | ForEach-Object { @{ id = $_.id; title = $_.title; host = $_.host } }) }
            }
            'probe' {
                $tab = Get-IeTabs | Where-Object { $_.id -eq [int]$request.id } | Select-Object -First 1
                if ($null -eq $tab) { Reply @{ ok = $false; error = 'tab not found' }; continue }
                Enable-Dialogs
                $info = Describe $tab
                # the dialogs open now (Shell.Application does not list them): what each holds, or that its document cannot be read (a plugin shows a file in it)
                $dialogs = @()
                if ($script:dialogsOk) {
                    try {
                        foreach ($server in [RkDialogs]::Servers()) {
                            $doc = $null; try { $doc = [RkDialogs]::DocumentOf([long]$server) } catch { }
                            if ($null -eq $doc) { $dialogs += [pscustomobject]@{ readable = $false; frames = @() }; continue }
                            $fake = [pscustomobject]@{ window = [pscustomobject]@{ Document = $doc } }
                            $d = Describe $fake
                            $dialogs += [pscustomobject]@{ readable = $true; frames = $d.frames; unreadable = $d.unreadable }
                        }
                    } catch { }
                }
                $info | Add-Member -NotePropertyName dialogs -NotePropertyValue @($dialogs)
                Reply @{ ok = $true; info = $info }
            }
            'start' {
                $tab = Get-IeTabs | Where-Object { $_.id -eq [int]$request.id } | Select-Object -First 1
                if ($null -eq $tab) { Reply @{ ok = $false; error = 'tab not found' }; continue }
                Enable-Dialogs
                $script:bound = $tab.window
                $script:hookRequests = [bool]$request.requests
                $script:diagMode = [string]$request.diag
                $targets.Clear(); $baseline.Clear(); $known.Clear()
                $boundKey = Get-Key $bound
                foreach ($other in $shell.Windows()) {
                    try {
                        $key = Get-Key $other
                        if ($key -and $key -ne $boundKey -and $other.FullName -match 'iexplore') { $baseline[$key] = $true }
                    } catch { }
                }
                if ($boundKey) { $known[$boundKey] = $true }
                if ($script:dialogsOk) { try { foreach ($server in [RkDialogs]::Servers()) { $baseline["dlg:" + $server] = $true } } catch { } }
                [void]$targets.Add($bound)
                $frames = 0; $attached = 0; $injectFailed = ''
                foreach ($w in (Get-Windows $bound.Document.parentWindow)) {
                    # What an earlier recording left in the cookie (the Logoff click, when the page left before the last look) belongs
                    # to that recording, never to this one: clear it before the recorder is put in.
                    $stillLoading = $false; try { $st = [string]$w.document.readyState; $stillLoading = ($st -eq 'loading' -or $st -eq 'uninitialized') } catch { }
                    if (-not $stillLoading -and $script:diagMode -ne 'none') { try { $null = $w.execScript("try { document.cookie = '__rkkeep=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT'; } catch (e) {}", 'javascript') } catch { } }
                    $err = Inject $w $true $true
                    if ($err -and -not $injectFailed) { $injectFailed = [string]$err }   # why the page refused the recorder: it reaches the panel
                    $frames++
                    $how = Get-Prop $w '__rkAttached'
                    if ($how -and $how -ne 'none') { $attached++ }
                }
                Reply @{ ok = $true; title = $tab.title; frames = $frames; attached = $attached; inject_error = $injectFailed }
            }
            'bind' {
                $tab = Get-IeTabs | Where-Object { $_.id -eq [int]$request.id } | Select-Object -First 1
                if ($null -eq $tab) { Reply @{ ok = $false; error = 'tab not found' } }
                else {
                    $script:runTab = $tab.window
                    $script:peek = [bool]$request.peek
                    if ($script:peek) {   # the page's requests are remembered from now on (what the sign-in gave, for a run that does not sign in)
                        try { foreach ($w in (Get-Windows $script:runTab.Document.parentWindow)) { $null = $w.execScript((RunFlags), 'javascript'); $null = Inject $w $true $true } } catch { }
                    }
                    Reply @{ ok = $true; title = $tab.title; host = $tab.host }
                }
            }
            'unbind' { $script:runTab = $null; $script:peek = $false; Reply @{ ok = $true } }
            'act' {
                if ($null -eq $runTab) { Reply @{ ok = $false; error = 'not bound' }; continue }
                $selectors = ([string[]]@($request.selectors)) -join "`n"
                $op = [string]$request.op; $val = [string]$request.value
                $candidates = @()
                try { $top = $runTab.Document.parentWindow } catch { Reply @{ ok = $false; error = 'the tab is gone' }; continue }
                foreach ($w in (Get-Windows $top)) {
                    $null = $w.execScript($(RunFlags), 'javascript')
                    $null = Inject $w $true $true
                    $found =Invoke-MethodArgs $w '__rkOp' @('find', $selectors, '')
                    if ($found) {
                        $o = ConvertFrom-Json -InputObject ([string]$found)
                        if ($o.count -gt 0) { $candidates += [pscustomobject]@{ win = $w; count = $o.count; rank = $o.rank } }
                    }
                }
                if ($candidates.Count -eq 0) { Reply @{ ok = $true; result = @{ ok = $false; error = 'not_found' } }; continue }
                $best = ($candidates | Measure-Object -Property rank -Minimum).Minimum
                $chosen = @($candidates | Where-Object { $_.rank -eq $best })
                if ($chosen.Count -gt 1) { Reply @{ ok = $true; result = @{ ok = $false; error = 'ambiguous'; count = $chosen.Count } }; continue }
                $answer = Invoke-MethodArgs $chosen[0].win '__rkOp' @($op, $selectors, $val)
                if (-not $answer) { Reply @{ ok = $true; result = @{ ok = $false; error = 'no_answer' } }; continue }
                Reply @{ ok = $true; result = (ConvertFrom-Json -InputObject ([string]$answer)) }
            }
            'frameop' {   # tasks 6.2: suggest, mark, unmark in every frame of the bound tab; each frame answers for itself (or nothing)
                if ($null -eq $runTab) { Reply @{ ok = $false; error = 'not bound' }; continue }
                $selectors = ([string[]]@($request.selectors)) -join "`n"
                $answers = New-Object System.Collections.ArrayList
                try { $top = $runTab.Document.parentWindow } catch { Reply @{ ok = $false; error = 'the tab is gone' }; continue }
                foreach ($w in (Get-Windows $top)) {
                    $null = $w.execScript($(RunFlags), 'javascript')
                    $null = Inject $w $true $true
                    $answer = Invoke-MethodArgs $w '__rkOp' @([string]$request.op, $selectors, [string]$request.value)
                    if ($answer) { [void]$answers.Add((ConvertFrom-Json -InputObject ([string]$answer))) }
                }
                Reply @{ ok = $true; frames = @($answers) }
            }
            'fetchfile' {   # the bytes of a file answer a page's request got (docs/design.md 6.4): read from the request object's responseBody (a byte array) here,
                # never converted in the page's JScript, and handed on as base64. Nothing is written by the bridge.
                if ($null -eq $runTab) { Reply @{ ok = $false; error = 'not bound' }; continue }
                $id = [string]$request.id
                $limit = [int64]$request.max
                $holder = $null; $xhr = $null
                try { $top = $runTab.Document.parentWindow } catch { Reply @{ ok = $false; error = 'the tab is gone' }; continue }
                foreach ($w in (Get-Windows $top)) {
                    $found = Invoke-MethodArgs $w '__rkFileX' @($id)
                    if ($found) { $xhr = $found; $holder = $w; break }
                }
                if ($null -eq $xhr) { Reply @{ ok = $true; found = $false }; continue }
                $bytes = $null
                try { $bytes = [byte[]][System.__ComObject].InvokeMember('responseBody', 'GetProperty', $null, $xhr, $null) } catch { }
                $null = Invoke-MethodArgs $holder '__rkFileX' @($id, 'drop')
                if ($null -eq $bytes) { Reply @{ ok = $true; found = $false }; continue }
                if ($limit -gt 0 -and $bytes.Length -gt $limit) { Reply @{ ok = $true; found = $true; too_big = $true; size = $bytes.Length }; continue }
                $b64 = [Convert]::ToBase64String($bytes)
                [Console]::Out.WriteLine('{"ok":true,"found":true,"size":' + $bytes.Length + ',"b64":"' + $b64 + '"}')
                [Console]::Out.Flush()
            }
            'dropfile' {
                if ($null -ne $runTab) { try { foreach ($w in (Get-Windows $runTab.Document.parentWindow)) { $null = Invoke-MethodArgs $w '__rkFileX' @([string]$request.id, 'drop') } } catch { } }
                Reply @{ ok = $true }
            }
            'locate' {   # task 6.1: each frame's matches for every selector of a step; the agent weighs them, nothing is done to the page
                if ($null -eq $runTab) { Reply @{ ok = $false; error = 'not bound' }; continue }
                $selectors = ([string[]]@($request.selectors)) -join "`n"
                $found = New-Object System.Collections.ArrayList
                try { $top = $runTab.Document.parentWindow } catch { Reply @{ ok = $false; error = 'the tab is gone' }; continue }
                foreach ($w in (Get-Windows $top)) {
                    $null = $w.execScript($(RunFlags), 'javascript')
                    $null = Inject $w $true $true
                    $answer = Invoke-MethodArgs $w '__rkOp' @('probe', $selectors, '')
                    if ($answer) { $o = ConvertFrom-Json -InputObject ([string]$answer); if (@($o.probes).Count -gt 0) { [void]$found.Add($o) } }
                }
                Reply @{ ok = $true; frames = @($found) }
            }
            'read' {
                if ($null -eq $bound -and $null -eq $runTab) { Reply @{ ok = $false; error = 'not started' } }
                else {
                    $reads = New-Object System.Collections.ArrayList
                    $sources = @()
                    if ($null -ne $bound) { Update-Targets; $sources = @($targets) } else { $sources = @($runTab) }   # the tab being run is read too
                    foreach ($t in $sources) {
                        $top = $null
                        try { $top = $t.Document.parentWindow } catch { }
                        if ($null -eq $top) { continue }
                        foreach ($w in (Get-Windows $top)) {
                            if ($null -eq $bound) { $null = $w.execScript($(RunFlags), 'javascript') }
                            $err = Inject $w $true ($null -eq $bound)
                            $text = Invoke-Method $w '__rkRead'
                            if ($text) { [void]$reads.Add([string]$text) }
                        }
                    }
                    Reply @{ ok = $true; reads = @($reads) }
                }
            }
            'poll' {
                if ($null -eq $bound) { Reply @{ ok = $false; error = 'not started' } }
                else {
                    $got = @(Collect)
                    $answer = @{ ok = $true; lines = $got }
                    if ($script:diagText -ne $script:lastDiag) { $answer.diag = $script:diagText; $script:lastDiag = $script:diagText }
                    Reply $answer
                }
            }
            'stop' {
                if ($null -eq $bound) { Reply @{ ok = $true; lines = @() }; continue }
                $rest = @(Collect)
                # A page that is still loading (the one Logoff leads to) cannot hand over what the page before it left: wait for it
                # a little, so the last click of the recording stays in this recording.
                $deadline = (Get-Date).AddSeconds(3)
                while ((Get-Date) -lt $deadline) {
                    $loading = $false
                    foreach ($t in @($targets)) { try { if ([string]$t.Document.readyState -ne 'complete') { $loading = $true } } catch { $loading = $true } }
                    if (-not $loading) { break }
                    Start-Sleep -Milliseconds 300
                    $rest += @(Collect)
                }
                $rest += @(Collect)
                foreach ($t in @($targets)) {
                    try { foreach ($w in (Get-Windows $t.Document.parentWindow)) { try { $null = $w.execScript('window.__rkRec = false', 'javascript') } catch { } } } catch { }
                }
                $targets.Clear()
                $script:bound = $null
                Reply @{ ok = $true; lines = $rest }
            }
            'quit' { Reply @{ ok = $true }; exit 0 }
            default { Reply @{ ok = $false; error = "unknown command: $($request.cmd)" } }
        }
    } catch {
        Reply @{ ok = $false; error = [string]$_.Exception.Message }
    }
}
