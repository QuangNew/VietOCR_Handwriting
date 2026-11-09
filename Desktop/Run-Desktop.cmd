@echo off
setlocal
cd /d "%~dp0src-tauri"
cargo +stable-x86_64-pc-windows-msvc run --release
set "exit_code=%ERRORLEVEL%"
echo VietOCR exited: %exit_code%
pause
exit /b %exit_code%
