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
$bound = $null          # the window (tab) being recorded

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
            try { foreach ($child in (Get-Windows $win.frames.item($i) ($depth + 1))) { [void]$list.Add($child) } } catch { }
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
            $tabs += [pscustomobject]@{ id = $index; title = [string]$w.LocationName; window = $w }
        } catch { }
    }
    return $tabs
}

function Inject($win) {
    try { $null = $win.execScript($recorderJs, 'javascript') } catch { }   # execScript returns a value: it must not reach the output
}

function Collect {
    $lines = @()
    foreach ($w in (Get-Windows $bound.Document.parentWindow)) {
        Inject $w   # a frame that has just loaded a new page has no recorder yet; one that has it ignores this
        $text = Invoke-Method $w '__rkTake'
        if ($text) { $lines += ([string]$text).Split("`n", [StringSplitOptions]::RemoveEmptyEntries) }
    }
    return $lines
}

function Describe($tab) {
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
            $frames += [pscustomobject]@{ name = $name; mode = [int]$doc.documentMode; inputs = $visible }
        } catch { }
    }
    return [pscustomobject]@{ frames = $frames; inputs = $inputs; buttons = $buttons; objects = $objects }
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
                Reply @{ ok = $true; tabs = @(Get-IeTabs | ForEach-Object { @{ id = $_.id; title = $_.title } }) }
            }
            'probe' {
                $tab = Get-IeTabs | Where-Object { $_.id -eq [int]$request.id } | Select-Object -First 1
                if ($null -eq $tab) { Reply @{ ok = $false; error = 'tab not found' } } else { Reply @{ ok = $true; info = (Describe $tab) } }
            }
            'start' {
                $tab = Get-IeTabs | Where-Object { $_.id -eq [int]$request.id } | Select-Object -First 1
                if ($null -eq $tab) { Reply @{ ok = $false; error = 'tab not found' }; continue }
                $script:bound = $tab.window
                foreach ($w in (Get-Windows $bound.Document.parentWindow)) { Inject $w }
                Reply @{ ok = $true; title = $tab.title }
            }
            'poll' {
                if ($null -eq $bound) { Reply @{ ok = $false; error = 'not started' } } else { Reply @{ ok = $true; lines = @(Collect) } }
            }
            'stop' {
                if ($null -eq $bound) { Reply @{ ok = $true; lines = @() }; continue }
                $rest = @(Collect)
                foreach ($w in (Get-Windows $bound.Document.parentWindow)) { try { $null = $w.execScript('window.__rkRec = false', 'javascript') } catch { } }
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
