@echo off
chcp 65001 >nul
echo Dang tao bieu tuong Rookie Agent tren man hinh nen...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-agent\install\create_shortcut.ps1"
echo.
echo Xong. Tu gio bam vao bieu tuong Rookie Agent tren man hinh nen de mo.
pause
