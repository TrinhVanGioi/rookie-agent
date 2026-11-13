# Build rookie-java-agent.jar: the recording helper that is loaded into a Swing application (see README.md).
# Targets Java 8 so it loads into the JRE 8 the real applications use. Needs a JDK 8 or newer on PATH.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Test-Path out) { Remove-Item -Recurse -Force out }
New-Item -ItemType Directory -Force out | Out-Null

$sources = (Get-ChildItem -Recurse src -Filter *.java).FullName
$version = (& javac -version 2>&1 | Out-String)
if ($version -match "javac 1\.8") {
    & javac -encoding UTF-8 -d out $sources
} else {
    & javac -encoding UTF-8 --release 8 -Xlint:-options -d out $sources
}
if ($LASTEXITCODE -ne 0) { throw "javac failed" }

[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot "manifest.txt"), "Premain-Class: rookie.RecorderAgent`r`n", [System.Text.Encoding]::ASCII)
& jar cfm rookie-java-agent.jar manifest.txt -C out .
if ($LASTEXITCODE -ne 0) { throw "jar failed" }
Remove-Item manifest.txt
Write-Host "Built $(Join-Path $PSScriptRoot 'rookie-java-agent.jar')"
