@echo off
cd /d "%~dp0"

if not exist "logs" mkdir "logs"

start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0start-hidden.ps1"

exit /b 0
