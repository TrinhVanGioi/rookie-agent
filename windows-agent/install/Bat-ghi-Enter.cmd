@echo off
chcp 65001 >nul
echo Bat ghi thao tac bang phim Enter cho cac chuong trinh Java cua tai khoan nay.
echo (Chi hoat dong khi ban bam Bat dau ghi. Khong ghi ky tu nao ban go.)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-agent\install\enable_java_agent.ps1" -Jar "%~dp0java-agent\rookie-java-agent.jar"
echo.
echo Hay DONG HET IE/Edge va cac chuong trinh Java, roi mo lai.
pause
