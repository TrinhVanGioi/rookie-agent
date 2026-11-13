# Register the Windows agent as a Native Messaging host for Edge and Chrome (current user only).
#
#   .\register_host.ps1 -ExtensionId <32 characters> [-Python C:\path\to\python.exe]
#   .\register_host.ps1 -Unregister
#
# -Python must have the same bitness as the JRE of the Java application (see README.md).
param(
    [string]$ExtensionId,
    [string]$Python = "python",
    [switch]$Unregister
)
$ErrorActionPreference = "Stop"

$hostName = "com.rookie_agent.host"
$agentDir = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $PSScriptRoot "$hostName.json"
$launcherPath = Join-Path $PSScriptRoot "rookie-agent-host.bat"
$registryKeys = @(
    "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\$hostName",
    "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$hostName"
)

if ($Unregister) {
    foreach ($key in $registryKeys) {
        if (Test-Path $key) { Remove-Item -Path $key -Force }
    }
    foreach ($file in @($manifestPath, $launcherPath)) {
        if (Test-Path $file) { Remove-Item -Path $file -Force }
    }
    Write-Host "Da go dang ky $hostName."
    exit 0
}

if ($ExtensionId -notmatch "^[a-p]{32}$") {
    throw "Can -ExtensionId gom 32 ky tu a-p (xem tai edge://extensions)."
}
$pythonPath = (Get-Command $Python -ErrorAction Stop).Source

# The browser starts the launcher; the launcher starts the agent from its own folder.
$launcher = "@echo off`r`ncd /d `"$agentDir`"`r`n`"$pythonPath`" -m rookie_agent host`r`n"
[System.IO.File]::WriteAllText($launcherPath, $launcher, [System.Text.Encoding]::ASCII)

$manifest = [ordered]@{
    name            = $hostName
    description     = "Rookie Agent Windows agent (Java Access Bridge)"
    path            = $launcherPath
    type            = "stdio"
    allowed_origins = @("chrome-extension://$ExtensionId/")
}
$json = $manifest | ConvertTo-Json
[System.IO.File]::WriteAllText($manifestPath, $json, (New-Object System.Text.UTF8Encoding($false)))

foreach ($key in $registryKeys) {
    New-Item -Path $key -Force | Out-Null
    Set-ItemProperty -Path $key -Name "(default)" -Value $manifestPath
}
Write-Host "Da dang ky $hostName cho extension $ExtensionId."
Write-Host "Manifest: $manifestPath"
Write-Host "Python:   $pythonPath"
