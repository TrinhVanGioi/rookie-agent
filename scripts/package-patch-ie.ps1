# Build dist\patch-ie.7z: the code that changes between full packages, to be unpacked OVER C:\rookie-agent-path-b on a PC that
# already has the full package (scripts\package-path-b.ps1). Everything of the agent, the shared config and schemas and the
# server code goes in, so a new file is never forgotten; tests, docs and the Python runtimes stay out.
#
#   .\scripts\package-patch-ie.ps1
param([string]$Out = "")
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
if (-not $Out) { $Out = Join-Path $repo "dist\patch-ie.7z" }
$root = Join-Path $env:TEMP "patch-ie-stage"
$stage = Join-Path $root "rookie-agent-path-b"
if (Test-Path $root) { Remove-Item -Recurse -Force $root }
New-Item -ItemType Directory -Force $stage | Out-Null

function Copy-Tree([string]$from, [string]$to, [string[]]$include) {
    New-Item -ItemType Directory -Force $to | Out-Null
    Get-ChildItem $from -Recurse -File | Where-Object {
        $_.FullName -notmatch '\\(__pycache__|\.pytest_cache|\.venv|node_modules)\\' -and ($include | Where-Object { $_ -ne $null } | ForEach-Object { $name = $_; $true }) -and ($include -contains $_.Extension)
    } | ForEach-Object {
        $target = Join-Path $to $_.FullName.Substring($from.Length + 1)
        New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
        Copy-Item $_.FullName $target
    }
}
Copy-Tree (Join-Path $repo "windows-agent\rookie_agent") (Join-Path $stage "windows-agent\rookie_agent") @(".py", ".js", ".ps1", ".html", ".json", ".cmd", ".png", ".txt")
Copy-Tree (Join-Path $repo "server\app") (Join-Path $stage "server\app") @(".py", ".json", ".html", ".js", ".css")   # the admin page (task 10.6) too
Copy-Tree (Join-Path $repo "config") (Join-Path $stage "config") @(".json")
New-Item -ItemType Directory -Force (Join-Path $stage "mock-site") | Out-Null      # the TouchPoint look-alike (task 11.1), tests left out
Get-ChildItem (Join-Path $repo "mock-site") -File -Filter *.py | Copy-Item -Destination (Join-Path $stage "mock-site")
Copy-Tree (Join-Path $repo "schemas") (Join-Path $stage "schemas") @(".json")
foreach ($loose in @("windows-agent\install\Xem-loi.cmd", "windows-agent\install\start.js", "windows-agent\soi-ie-click.ps1", "windows-agent\soi-ie-dom.ps1", "windows-agent\soi-ie.py")) {
    $source = Join-Path $repo $loose
    if (Test-Path $source) {
        $target = Join-Path $stage $loose
        New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
        Copy-Item $source $target
    }
}
[IO.File]::WriteAllText((Join-Path $stage "DOC-DAY.txt"), "Giai nen DE LEN thu muc goi (C:\rookie-agent-path-b), chon ghi de. Dong va mo lai bieu tuong Rookie Agent (may chu hoc cung khoi dong lai).")

$sevenZip = @("C:\Program Files\7-Zip\7z.exe", "C:\Program Files (x86)\7-Zip\7z.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $sevenZip) { throw "Can 7-Zip (7z.exe) de tao file 7z." }
if (Test-Path $Out) { Remove-Item -Force $Out }
Push-Location $root
& $sevenZip a -t7z -mx=5 -bso0 -bsp0 $Out "rookie-agent-path-b"
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "7-Zip failed" }
& $sevenZip t -bso0 -bsp0 $Out
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "The archive did not pass its own test" }
Pop-Location
Remove-Item -Recurse -Force $root
$info = Get-Item $Out
Write-Host ("Da tao {0} ({1} KB, {2})" -f $Out, [int]($info.Length / 1KB), $info.LastWriteTime)
