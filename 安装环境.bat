@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
"%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ROOT%install-env.ps1" %*
set "EXITCODE=%ERRORLEVEL%"
echo.
if not "%EXITCODE%"=="0" echo Environment setup failed. Exit code: %EXITCODE%
if "%EXITCODE%"=="0" echo Environment setup completed.
echo Press any key to close this window.
pause >nul
exit /b %EXITCODE%
