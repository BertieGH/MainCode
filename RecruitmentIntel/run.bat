@echo off
REM Launch the RecruitmentIntel dev stack with pre-flight port checks.
REM   Backend  (FastAPI)  -> http://localhost:8002   (Swagger: /docs)
REM   Frontend (Angular)  -> http://localhost:4200
REM
REM Stale uvicorn / ng serve processes from earlier sessions commonly
REM keep these ports bound. This script detects that up front and
REM offers to free the port instead of failing inside a hidden window.

setlocal enabledelayedexpansion
set "ROOT=%~dp0"

echo === RecruitmentIntel dev launcher ===
echo.

call :check_port 8002 "Backend (FastAPI)"
if errorlevel 1 goto :end

call :check_port 4200 "Frontend (Angular)"
if errorlevel 1 goto :end

if not exist "%ROOT%node_modules" (
    echo [!] node_modules not found at %ROOT%node_modules
    echo     Run: npm install
    goto :end
)

echo Starting backend on port 8002...
start "RecruitmentIntel - Backend" cmd /k "cd /d ""%ROOT%backend"" && python -m uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload"

echo Starting frontend on port 4200...
start "RecruitmentIntel - Frontend" cmd /k "cd /d ""%ROOT%"" && npm start"

echo.
echo   Backend:  http://localhost:8002/docs
echo   Frontend: http://localhost:4200
echo.
goto :end


:check_port
set "PORT=%~1"
set "LABEL=%~2"
set "FOUND_PID="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr LISTENING') do (
    set "FOUND_PID=%%a"
    goto :got_pid
)
:got_pid
if not defined FOUND_PID (
    exit /b 0
)

set "PROC_NAME=<unknown>"
for /f "tokens=1 delims=," %%b in ('tasklist /FI "PID eq !FOUND_PID!" /FO CSV /NH 2^>nul') do set "PROC_NAME=%%~b"

echo [!] Port %PORT% is already in use ^(needed for %LABEL%^).
echo     PID:     !FOUND_PID!
echo     Process: !PROC_NAME!
echo.
set "KILL="
set /p "KILL=Kill PID !FOUND_PID! and continue? [y/N] "
if /i not "!KILL!"=="y" (
    echo     Aborted. Free the port manually and re-run.
    exit /b 1
)

taskkill /PID !FOUND_PID! /F >nul 2>&1
if errorlevel 1 (
    echo     taskkill failed. Try re-running this script as Administrator.
    exit /b 1
)
echo     Killed PID !FOUND_PID!.
REM give Windows a moment to release the socket
ping -n 2 127.0.0.1 >nul
echo.
exit /b 0


:end
endlocal
