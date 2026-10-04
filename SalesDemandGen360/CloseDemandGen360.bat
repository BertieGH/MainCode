@echo off
REM ===========================================================================
REM  Sales Demand Gen360 - stop both servers.
REM
REM  Kills by *port*, not by image name. "taskkill /IM node.exe" would take
REM  down every other Node process on the machine, and the same for python -
REM  this only stops what is actually serving this application.
REM
REM  /T as well as /F because both servers spawn children that outlive the
REM  parent: uvicorn --reload runs a reloader that owns the real server, and
REM  the Angular CLI spawns esbuild workers. Killing only the parent leaves
REM  the port held, and the next start then refuses to run.
REM ===========================================================================
setlocal enabledelayedexpansion

set "API_PORT=8011"
set "WEB_PORT=4200"

echo.
echo   Sales Demand Gen360 - shutting down
echo   ----------------------------------

call :killport %API_PORT% "API"
call :killport %WEB_PORT% "frontend"

echo.
echo   Done.
echo.
pause
exit /b 0

REM --- kill whatever listens on port %1, described as %2 --------------------
:killport
set "PORT=%~1"
set "WHAT=%~2"
set "FOUND=0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
    if not "%%P"=="0" (
        set "FOUND=1"
        echo   Stopping %WHAT% on %PORT% ^(PID %%P^)
        taskkill /F /T /PID %%P >nul 2>&1
        if errorlevel 1 (
            echo   [!] Could not stop PID %%P - it may need an elevated prompt.
        )
    )
)
if "!FOUND!"=="0" echo   Nothing was listening on %PORT% ^(%WHAT% already stopped^)
exit /b 0
