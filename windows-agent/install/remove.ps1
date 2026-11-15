# Take Rookie Agent off this PC: stop it, remove the icons and its data folder. Your recordings are removed too.
# The package folder itself is left alone; delete it by hand if you no longer need it.
param(
    [string]$DesktopDir = [Environment]::GetFolderPath("Desktop"),
    [string]$StartupDir = [Environment]::GetFolderPath("Startup"),
    [string]$AppHome = (Join-Path $env:LOCALAPPDATA "RookieAgent")
)
$ErrorActionPreference = "Continue"
$agent = Split-Path -Parent $PSScriptRoot
$package = Split-Path -Parent $agent
# Only programs that run from this package, never other Python or Java on the PC.
Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($package, [StringComparison]::OrdinalIgnoreCase) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
foreach ($folder in @($DesktopDir, $StartupDir)) {
    $link = Join-Path $folder "Rookie Agent.lnk"
    if (Test-Path $link) { Remove-Item $link -Force; Write-Host "Da xoa: $link" }
}
if (Test-Path $AppHome) { Remove-Item $AppHome -Recurse -Force; Write-Host "Da xoa: $AppHome" }
Write-Host "Xong. Neu da cai extension trong Chrome, vao chrome://extensions va bam Xoa."
