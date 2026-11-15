@echo off
chcp 65001 >nul
echo Dang go Rookie Agent khoi may nay...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-agent\install\remove.ps1"
echo.
pause
