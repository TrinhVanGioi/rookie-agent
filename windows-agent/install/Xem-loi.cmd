@echo off
chcp 65001 >nul
rem Khi bieu tuong Rookie Agent khong mo duoc: bam dup file nay. No ghi ket qua kiem tra vao file Loi-khoi-dong.txt tren man hinh nen.
set "PKG=%~dp0"
set "OUT=%USERPROFILE%\Desktop\Loi-khoi-dong.txt"
set "AGENT_HOME=%LOCALAPPDATA%\RookieAgent"
echo Dang kiem tra, doi vai giay...
powershell -NoProfile -Command "[IO.File]::WriteAllBytes('%OUT%', [byte[]](239,187,191))"
set PYTHONUTF8=1
(
  echo === Thoi gian: %date% %time%
  echo === Thu muc goi: %PKG%
  echo.
  echo === Python 64-bit
  if exist "%PKG%runtime\py64\python.exe" ( pushd "%PKG%windows-agent" & "%PKG%runtime\py64\python.exe" -m rookie_agent status 2>&1 & popd ) else ( echo khong co )
  echo.
  echo === Python 32-bit
  if exist "%PKG%runtime\py32\python.exe" ( pushd "%PKG%windows-agent" & "%PKG%runtime\py32\python.exe" -m rookie_agent status 2>&1 & popd ) else ( echo khong co )
  echo.
  echo === Trang quan ly co dang chay khong
  powershell -NoProfile -Command "try { (Invoke-WebRequest http://localhost:8765/api/ping -UseBasicParsing -TimeoutSec 3).Content } catch { 'Khong chay: ' + $_.Exception.Message }"
  echo.
  echo === agent.log
  if exist "%AGENT_HOME%\agent.log" ( powershell -NoProfile -Command "Get-Content -Tail 60 -Encoding UTF8 '%AGENT_HOME%\agent.log'" ) else ( echo chua co file agent.log )
  echo.
  echo === server.log
  if exist "%AGENT_HOME%\server.log" ( powershell -NoProfile -Command "Get-Content -Tail 40 -Encoding UTF8 '%AGENT_HOME%\server.log'" ) else ( echo chua co file server.log )
) >> "%OUT%" 2>&1
echo.
echo Da ghi ket qua vao: %OUT%
echo Hay gui file Loi-khoi-dong.txt tren man hinh nen cho nhom phat trien.
start "" notepad "%OUT%"
pause
