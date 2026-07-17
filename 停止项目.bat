@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
"%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ROOT%stop-project.ps1" %*
set "EXITCODE=%ERRORLEVEL%"
echo.
echo Press any key to close this window.
pause >nul
exit /b %EXITCODE%
