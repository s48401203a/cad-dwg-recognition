@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
"%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ROOT%start-project.ps1" %*
set "EXITCODE=%ERRORLEVEL%"
echo.
if not "%EXITCODE%"=="0" echo Startup failed. Exit code: %EXITCODE%
set "URL="
for /f "usebackq delims=" %%U in (`"%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$p='%ROOT%.cad-server.json'; if (Test-Path -LiteralPath $p) { (Get-Content -LiteralPath $p -Raw | ConvertFrom-Json).url }"`) do set "URL=%%U"
if "%URL%"=="" set "URL=http://127.0.0.1:8000"
echo Service page: %URL%
echo Press any key to close this window.
pause >nul
exit /b %EXITCODE%
