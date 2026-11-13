# Build one zip with everything path B needs on an offline machine:
# the Windows agent, the server (to learn workflows) with its Python wheels, the shared config and
# schemas, the Java recording helper and the Swing mock.
#
#   .\scripts\package-path-b.ps1                                  ->  dist\rookie-agent-path-b.zip
#   .\scripts\package-path-b.ps1 -PythonVersion 3.10 -Platform win32   for a 32-bit Python 3.10 on the target
#
# The wheels must match the Python that will be installed on the target machine (version and 32/64 bit).
# The agent itself uses only the Python standard library; the wheels are for the server.
#   .\scripts\package-path-b.ps1 -Format 7z -Password <pass>      dist\rookie-agent-path-b.7z, AES-256, file names hidden
#   .\scripts\package-path-b.ps1 -Password <pass>                 zip with a password (needs 7-Zip to build)
#
# 7z needs 7-Zip (or a tool that reads .7z) on the target. For a zip, -Encryption ZipCrypto (default) opens with the
# Extract All of Windows Explorer; AES256 is stronger but needs 7-Zip or WinRAR on the target.
# The password is only given on the command line, never stored in the repo.
param(
    [string]$PythonVersion = "3.12",
    [string]$Platform = "win_amd64",
    [string]$Password = "",
    [ValidateSet("zip", "7z")][string]$Format = "zip",
    [ValidateSet("ZipCrypto", "AES256")][string]$Encryption = "ZipCrypto"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $repo "dist"
$stage = Join-Path $dist "rookie-agent-path-b"
$zip = Join-Path $dist "rookie-agent-path-b.$Format"

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

if ($Password -or $Format -eq "7z") {
    $sevenZip = @("C:\Program Files\7-Zip\7z.exe", "C:\Program Files (x86)\7-Zip\7z.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $sevenZip) { $sevenZip = (Get-Command 7z -ErrorAction SilentlyContinue).Source }
    if (-not $sevenZip) { throw "Can 7-Zip (7z.exe) de tao file 7z hoac file co mat khau." }
    $options = @("-t$Format", "-mx=5", "-bso0", "-bsp0")
    if ($Password) {
        $options += "-p$Password"
        if ($Format -eq "7z") { $options += "-mhe=on" }   # also hides the file names
        else { $options += "-mem=$Encryption" }
    }
    # The folder itself is added, so the entries start with rookie-agent-path-b/ and use "/".
    & $sevenZip a @options $zip $stage
    if ($LASTEXITCODE -ne 0) { throw "7-Zip failed" }
    $check = @("t", "-bso0", "-bsp0"); if ($Password) { $check += "-p$Password" }
    & $sevenZip @check $zip
    if ($LASTEXITCODE -ne 0) { throw "The archive did not pass its own test" }
} else {
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
}
Remove-Item -Recurse -Force $stage
$how = if (-not $Password) { "" } elseif ($Format -eq "7z") { " (co mat khau, AES-256, an ca ten file)" } else { " (co mat khau, $Encryption)" }
Write-Host "Da tao $zip$how"
