@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
call "%~dp0..\Desktop\Run-Desktop.cmd" %*
exit /b %errorlevel%
