@echo off
chcp 65001 >nul
echo Dang chuan bi extension cho Chrome...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-agent\install\create_shortcut.ps1" -WithChrome
echo.
pause
