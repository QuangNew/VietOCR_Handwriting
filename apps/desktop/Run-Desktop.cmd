@echo off
setlocal
cd /d "%~dp0"
title VietHandOCR - Desktop console
if not exist "dist\vietocr-desktop.exe" (
    echo Missing apps\desktop\dist\vietocr-desktop.exe.
    echo Download the Windows artifact from the refactor GitHub workflow, or build apps\desktop\src-tauri with Rust MSVC.
    pause
    exit /b 1
)
"dist\vietocr-desktop.exe"
set "exit_code=%ERRORLEVEL%"
echo VietHandOCR exited: %exit_code%
pause
exit /b %exit_code%
