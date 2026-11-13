# Let the Windows agent see keyboard actions in Java programs (Enter in a field, Space or Enter on a button).
#
#   .\enable_java_agent.ps1 -Jar ..\..\java-agent\rookie-java-agent.jar
#   .\enable_java_agent.ps1 -Disable
#
# It sets JAVA_TOOL_OPTIONS for the current Windows user only (no administrator rights) so that every Java
# program the user starts afterwards loads the recording helper. The programs themselves are not changed.
# The helper does nothing unless the GDV has pressed Ghi, and it never records what is typed.
# Programs that are already running must be closed and opened again.
#
# To limit it to one program instead, do not run this script: add -javaagent:<jar> to that program's launcher options.
param(
    [string]$Jar,
    [switch]$Disable
)
$ErrorActionPreference = "Stop"

$home_ = if ($env:ROOKIE_AGENT_HOME) { $env:ROOKIE_AGENT_HOME } else { Join-Path $env:LOCALAPPDATA "RookieAgent" }
$target = Join-Path $home_ "rookie-java-agent.jar"
$name = "JAVA_TOOL_OPTIONS"
$current = [Environment]::GetEnvironmentVariable($name, "User")

# Remove any earlier copy of our option, keep everything else the user may have set.
$others = @()
if ($current) {
    $others = $current -split "\s+" | Where-Object { $_ -and $_ -notmatch "rookie-java-agent\.jar" }
}

if ($Disable) {
    $value = ($others -join " ").Trim()
    [Environment]::SetEnvironmentVariable($name, $(if ($value) { $value } else { $null }), "User")
    Write-Host "Da tat. Dong va mo lai cac chuong trinh Java de co hieu luc."
    exit 0
}

if (-not $Jar) { throw "Can -Jar tro toi rookie-java-agent.jar" }
if (-not (Test-Path $Jar)) { throw "Khong thay $Jar" }
New-Item -ItemType Directory -Force $home_ | Out-Null
Copy-Item -Force $Jar $target
if ($target -match "\s") { throw "Duong dan $target co dau cach, JAVA_TOOL_OPTIONS khong dung duoc. Dat ROOKIE_AGENT_HOME tro toi thu muc khong co dau cach." }

$value = (@($others) + "-javaagent:$target") -join " "
[Environment]::SetEnvironmentVariable($name, $value.Trim(), "User")
Write-Host "Da bat. JAVA_TOOL_OPTIONS = $value"
Write-Host "Dong va mo lai cac chuong trinh Java (vi du Touchpoint) de co hieu luc."
Write-Host "Moi chuong trinh Java se in dong 'Picked up JAVA_TOOL_OPTIONS' ra man hinh lenh neu chay tu cua so lenh; day la binh thuong."
