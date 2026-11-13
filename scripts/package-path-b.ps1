# Build one zip with everything path B needs on an offline machine:
# the Windows agent, the shared config and schemas, and the Swing mock.
#
#   .\scripts\package-path-b.ps1        ->  dist\rookie-agent-path-b.zip
#
# The agent uses only the Python standard library at run time, so no wheels are needed.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $repo "dist"
$stage = Join-Path $dist "rookie-agent-path-b"
$zip = Join-Path $dist "rookie-agent-path-b.zip"

& (Join-Path $repo "mock-java\build.ps1")
& (Join-Path $repo "java-agent\build.ps1")

if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force $stage | Out-Null

# Keep the repo layout: the agent finds config\ and schemas\ relative to itself.
foreach ($folder in @("windows-agent", "config", "schemas")) {
    Copy-Item -Recurse (Join-Path $repo $folder) (Join-Path $stage $folder)
}
New-Item -ItemType Directory -Force (Join-Path $stage "java-agent") | Out-Null
Copy-Item (Join-Path $repo "java-agent\rookie-java-agent.jar") (Join-Path $stage "java-agent")
New-Item -ItemType Directory -Force (Join-Path $stage "mock-java") | Out-Null
Copy-Item (Join-Path $repo "mock-java\mock-tpss.jar") (Join-Path $stage "mock-java")

Get-ChildItem -Recurse -Force $stage -Directory |
    Where-Object { $_.Name -in @("__pycache__", ".pytest_cache") } |
    Remove-Item -Recurse -Force
Get-ChildItem (Join-Path $stage "windows-agent\install") -Include *.json, *.bat -Recurse |
    Where-Object { $_.Name -notlike "*.ps1" } |
    Remove-Item -Force

if (Test-Path $zip) { Remove-Item -Force $zip }
Add-Type -AssemblyName System.IO.Compression.FileSystem
# A freshly built jar can be held briefly by a virus scanner, so retry a few times.
for ($attempt = 1; ; $attempt++) {
    try {
        [System.IO.Compression.ZipFile]::CreateFromDirectory($stage, $zip, "Optimal", $true)
        break
    } catch [System.IO.IOException] {
        if ($attempt -ge 5) { throw }
        if (Test-Path $zip) { Remove-Item -Force $zip }
        Start-Sleep -Seconds 2
    }
}
Remove-Item -Recurse -Force $stage
Write-Host "Da tao $zip"
