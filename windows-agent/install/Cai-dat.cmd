@echo off
chcp 65001 >nul
echo Dang cai dat Rookie Agent cho may nay...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-agent\install\create_shortcut.ps1"
echo.
echo Xong. Tu gio bam vao bieu tuong Rookie Agent tren man hinh nen de mo.
pause
