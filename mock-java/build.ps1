# Build the Swing mock into out\ and mock-tpss.jar. Needs JDK 8 or newer on PATH.
# Bytecode targets Java 8 so the result runs on the JRE 8 used by the real applets.
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

& jar cfe mock-tpss.jar mocktpss.Main -C out .
if ($LASTEXITCODE -ne 0) { throw "jar failed" }

& java "-Djava.awt.headless=true" "-Dfile.encoding=UTF-8" -cp out mocktpss.SelfTest
if ($LASTEXITCODE -ne 0) { throw "SelfTest failed" }
