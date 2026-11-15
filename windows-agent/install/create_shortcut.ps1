# Set Rookie Agent up for the person using this PC. Double-click Cai-dat.cmd in the package folder to run this.
#  1. Copy the browser extension to a fixed place, so it keeps working if the package folder is moved or deleted.
#  2. Put the "Rookie Agent" icon on the desktop; it starts the local page with the bundled Python
#     (the 32-bit or 64-bit one, whichever matches Java).
#     It also starts by itself, hidden, each time the user logs in.
#  3. (only with -WithChrome) Open the extensions page of Chrome and put the extension folder on the clipboard.
# Nothing needs to be installed first. Step 3 only with -WithChrome (Cai-extension-Chrome.cmd). -DesktopDir and -StartupDir are for testing.
param(
    [string]$DesktopDir = [Environment]::GetFolderPath("Desktop"),
    [string]$StartupDir = [Environment]::GetFolderPath("Startup"),
    [string]$AppHome = (Join-Path $env:LOCALAPPDATA "RookieAgent"),
    [switch]$WithChrome
)
$ErrorActionPreference = "Stop"
$agent = Split-Path -Parent $PSScriptRoot
$package = Split-Path -Parent $agent
$python = Join-Path $package "runtime\py64\pythonw.exe"
if (-not (Test-Path $python)) { $python = Join-Path $package "runtime\py32\pythonw.exe" }
if (-not (Test-Path $python)) { Write-Host "Khong thay Python di kem trong thu muc runtime."; exit 1 }

# 1. the extension
$source = Join-Path $package "extension"
$target = Join-Path $AppHome "extension"
if (Test-Path $source) {
    if (Test-Path $target) { Remove-Item -Recurse -Force $target }
    New-Item -ItemType Directory -Force $AppHome | Out-Null
    Copy-Item -Recurse $source $target
    Write-Host "Da chep extension vao: $target"
}

# 2. the icon
New-Item -ItemType Directory -Force $DesktopDir | Out-Null
$link = Join-Path $DesktopDir "Rookie Agent.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $python
$shortcut.Arguments = "-m rookie_agent web --auto-bits"
$shortcut.WorkingDirectory = $agent
$shortcut.Description = "Rookie Agent"
$shortcut.IconLocation = "$env:SystemRoot\System32\imageres.dll,109"
$shortcut.Save()
Write-Host "Da tao bieu tuong Rookie Agent tren man hinh nen: $link"

# 2b. start by itself when this user logs in to Windows: the agent and the learning server are ready, no window shown
New-Item -ItemType Directory -Force $StartupDir | Out-Null
$auto = $shell.CreateShortcut((Join-Path $StartupDir "Rookie Agent.lnk"))
$auto.TargetPath = $python
$auto.Arguments = "-m rookie_agent web --auto-bits --no-browser --start-server"
$auto.WorkingDirectory = $agent
$auto.WindowStyle = 7
$auto.Save()
Write-Host "Rookie Agent se tu chay ngam moi khi dang nhap Windows."

# 3. the extension in Chrome
if ((Test-Path $target) -and $WithChrome) {
    Set-Clipboard -Value $target
    Write-Host ""
    Write-Host "De cai extension vao Chrome (chi lam mot lan):"
    Write-Host "  1. Trang chrome://extensions vua mo. Bat 'Che do nha phat trien' o goc tren ben phai."
    Write-Host "  2. Bam 'Tai tien ich da giai nen'."
    Write-Host "  3. Dan duong dan (Ctrl+V) vao o ten thu muc roi bam Chon thu muc. Duong dan da duoc chep san:"
    Write-Host "     $target"
    $chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($chrome) { Start-Process $chrome "chrome://extensions" } else { Write-Host "  (Khong tim thay Chrome. Mo Chrome va go chrome://extensions vao thanh dia chi.)" }
}
