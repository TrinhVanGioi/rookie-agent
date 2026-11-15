@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-agent\install\enable_java_agent.ps1" -Disable
echo.
pause
