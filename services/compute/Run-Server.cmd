@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -File "%~dp0tools\Start-Server.ps1" %*
echo.
echo Server stopped. This console remains open.
pause
