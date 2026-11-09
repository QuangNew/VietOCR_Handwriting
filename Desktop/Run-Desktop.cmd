@echo off
setlocal
cd /d "%~dp0"
title VietOCR - Desktop console
if not exist "dist\vietocr-desktop.exe" (
    echo Missing Desktop\dist\vietocr-desktop.exe.
    echo Download the Windows artifact from the refactor GitHub workflow, or build Desktop\src-tauri with Rust MSVC.
    pause
    exit /b 1
)
"dist\vietocr-desktop.exe"
set "exit_code=%ERRORLEVEL%"
echo VietOCR exited: %exit_code%
pause
exit /b %exit_code%
