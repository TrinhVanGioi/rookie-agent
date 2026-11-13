# Build one zip with everything path B needs on an offline machine:
# the Windows agent, the server (to learn workflows) with its Python wheels, the shared config and
# schemas, the Java recording helper and the Swing mock.
#
#   .\scripts\package-path-b.ps1                                  ->  dist\rookie-agent-path-b.zip
#   .\scripts\package-path-b.ps1 -PythonVersion 3.10 -Platform win32   for a 32-bit Python 3.10 on the target
#
# The wheels must match the Python that will be installed on the target machine (version and 32/64 bit).
# The agent itself uses only the Python standard library; the wheels are for the server.
param(
    [string]$PythonVersion = "3.12",
    [string]$Platform = "win_amd64"
)
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
# The server, without its virtual environment, database and tests
$serverTarget = Join-Path $stage "server"
New-Item -ItemType Directory -Force $serverTarget | Out-Null
Copy-Item -Recurse (Join-Path $repo "server\app") (Join-Path $serverTarget "app")
Copy-Item (Join-Path $repo "server\requirements-run.txt") $serverTarget

# Python wheels for the server, for the target's Python
$wheels = Join-Path $stage "wheels"
$python = Join-Path $repo "server\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
& $python -m pip download --quiet --dest $wheels --only-binary=:all: --python-version $PythonVersion --platform $Platform -r (Join-Path $serverTarget "requirements-run.txt")
if ($LASTEXITCODE -ne 0) { throw "pip download failed: wheels for Python $PythonVersion / $Platform" }

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
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
# Windows PowerShell 5.1 writes "\" in the names of ZipFile.CreateFromDirectory entries, which breaks the zip
# format for many tools. Add the entries one by one with "/".
# A freshly built jar can be held briefly by a virus scanner, so retry a few times.
for ($attempt = 1; ; $attempt++) {
    try {
        $archive = [System.IO.Compression.ZipFile]::Open($zip, "Create")
        try {
            foreach ($file in Get-ChildItem -Recurse -File -Force $stage) {
                $name = "rookie-agent-path-b/" + $file.FullName.Substring($stage.Length + 1).Replace("\", "/")
                [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, $name, "Optimal")
            }
        } finally {
            $archive.Dispose()
        }
        break
    } catch [System.IO.IOException] {
        if ($attempt -ge 5) { throw }
        if (Test-Path $zip) { Remove-Item -Force $zip }
        Start-Sleep -Seconds 2
    }
}
Remove-Item -Recurse -Force $stage
Write-Host "Da tao $zip"
