# Put the "Rookie Agent" icon on the desktop. Double-click Cai-dat.cmd in the package folder to run this.
# The icon starts the local page with the bundled Python; it picks the 32-bit or 64-bit one by itself to match Java.
$ErrorActionPreference = "Stop"
$agent = Split-Path -Parent $PSScriptRoot
$package = Split-Path -Parent $agent
$python = Join-Path $package "runtime\py64\pythonw.exe"
if (-not (Test-Path $python)) { $python = Join-Path $package "runtime\py32\pythonw.exe" }
if (-not (Test-Path $python)) { Write-Host "Khong thay Python di kem trong thu muc runtime."; exit 1 }
$desktop = [Environment]::GetFolderPath("Desktop")
$link = Join-Path $desktop "Rookie Agent.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $python
$shortcut.Arguments = "-m rookie_agent web --auto-bits"
$shortcut.WorkingDirectory = $agent
$shortcut.Description = "Rookie Agent"
$shortcut.IconLocation = "$env:SystemRoot\System32\imageres.dll,109"
$shortcut.Save()
Write-Host "Da tao bieu tuong Rookie Agent tren man hinh nen: $link"
