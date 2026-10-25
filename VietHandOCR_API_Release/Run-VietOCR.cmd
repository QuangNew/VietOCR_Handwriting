@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
title VietOCR - Debug Console
if not exist ".venv\Scripts\python.exe" (
    echo Python environment not found. Please follow README.md to create .venv first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -u -X utf8 debug_console.py %*
if not "%errorlevel%"=="0" pause
