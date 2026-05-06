@echo off
REM ============================================================
REM   RecruitmentIntel - one-stop launcher
REM ------------------------------------------------------------
REM   Brings up the full local dev stack:
REM     [1] Pre-flight: ports 8002, 4200 are free
REM     [2] Pre-flight: node_modules present
REM     [3] Redis    -> redis://localhost:6379/0
REM     [4] Worker   -> arq app.tasks.worker.WorkerSettings
REM     [5] Backend  -> http://localhost:8002   (Swagger: /docs)
REM     [6] Frontend -> http://localhost:4200
REM
REM   Each long-running service opens in its own labelled window
REM   so you can watch logs and Ctrl+C any one of them.
REM ============================================================

setlocal enabledelayedexpansion
set "ROOT=%~dp0"

echo === RecruitmentIntel one-stop launcher ===
echo.

REM ---------- 1. Port pre-flight ----------
call :check_port 8002 "Backend (FastAPI)"
if errorlevel 1 goto :end

call :check_port 4200 "Frontend (Angular)"
if errorlevel 1 goto :end

REM ---------- 2. node_modules pre-flight ----------
if not exist "%ROOT%node_modules" (
    echo [!] node_modules not found at %ROOT%node_modules
    echo     Run: npm install
    goto :end
)

REM ---------- 3. Redis ----------
echo [3/6] Checking Redis on localhost:6379...
call :probe_redis
if not errorlevel 1 (
    echo       Redis already reachable. Skipping launch.
    goto :worker
)

echo       Redis not reachable. Looking for a runtime...

REM ---- try Docker ----
where docker >nul 2>&1
if not errorlevel 1 (
    echo       Found docker. Starting redis:7-alpine container...
    docker rm -f recruitmentintel-redis >nul 2>&1
    docker run -d --name recruitmentintel-redis -p 6379:6379 redis:7-alpine >nul
    if not errorlevel 1 goto :wait_redis
    echo       docker run failed. Trying next option...
)

REM ---- try native redis-server.exe ----
where redis-server >nul 2>&1
if not errorlevel 1 (
    echo       Found redis-server in PATH. Launching window...
    start "RecruitmentIntel - Redis" cmd /k "redis-server"
    goto :wait_redis
)

REM ---- try Memurai (Redis-compatible Windows service) ----
where memurai >nul 2>&1
if not errorlevel 1 (
    echo       Found Memurai in PATH. Launching window...
    start "RecruitmentIntel - Memurai" cmd /k "memurai"
    goto :wait_redis
)

REM ---- try Memurai installed as Windows service ----
sc query Memurai 2>nul | find "RUNNING" >nul
if not errorlevel 1 (
    echo       Memurai service is already running.
    goto :worker
)
sc query Memurai >nul 2>&1
if not errorlevel 1 (
    echo       Memurai service found but not running. Starting...
    net start Memurai
    if not errorlevel 1 goto :wait_redis
)

echo.
echo [!] No Redis runtime found. Continuing WITHOUT background worker.
echo     The Angular UI and FastAPI backend will still start.
echo     What you lose: scheduled RSS ingestion, on-demand enrichment, job crawls.
echo     To enable later, install one of:
echo       - Docker Desktop:  https://www.docker.com/products/docker-desktop
echo       - Memurai (Win):   https://www.memurai.com/get-memurai
echo       - WSL Redis:       wsl -d Ubuntu sudo apt install -y redis-server
echo.
set "SKIP_WORKER=1"
goto :backend

:wait_redis
echo       Waiting for Redis to accept connections...
set /a TRIES=0
:wait_loop
set /a TRIES+=1
call :probe_redis
if not errorlevel 1 goto :redis_ok
if !TRIES! gtr 20 (
    echo [!] Redis did not come up within ~20s. Aborting.
    goto :end
)
ping -n 2 127.0.0.1 >nul
goto :wait_loop

:redis_ok
echo       Redis is up.
echo.

REM ---------- 4. arq worker ----------
:worker
echo [4/6] Starting arq worker...
if not exist "%ROOT%backend\app\tasks\worker.py" (
    echo       worker.py not found - skipping worker. Backend/frontend will still start.
    goto :backend
)

tasklist /FI "WINDOWTITLE eq RecruitmentIntel - Worker*" 2>nul | find "cmd.exe" >nul
if not errorlevel 1 (
    echo       A worker window is already open. Skipping.
) else (
    start "RecruitmentIntel - Worker" cmd /k "cd /d ""%ROOT%backend"" && python dev_worker.py"
    echo       Worker launched.
)
echo.

REM ---------- 5. FastAPI backend ----------
:backend
echo [5/6] Starting backend on port 8002...
start "RecruitmentIntel - Backend" cmd /k "cd /d ""%ROOT%backend"" && python dev_server.py"
echo       Backend launching.
echo.

REM ---------- 6. Angular frontend ----------
echo [6/6] Starting frontend on port 4200...
start "RecruitmentIntel - Frontend" cmd /k "cd /d ""%ROOT%"" && npm start"
echo       Frontend launching.
echo.

echo === Stack up ===
if defined SKIP_WORKER (
    echo   Redis:    NOT RUNNING ^(install Memurai/Docker/WSL Redis to enable worker^)
    echo   Worker:   SKIPPED
) else (
    echo   Redis:    redis://localhost:6379/0
    echo   Worker:   window "RecruitmentIntel - Worker"
)
echo   Backend:  http://localhost:8002/docs
echo   Frontend: http://localhost:4200
echo.
echo   Close the per-service windows to stop individual processes.
echo.
goto :end


REM ============================================================
REM   Helpers
REM ============================================================

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
ping -n 2 127.0.0.1 >nul
echo.
exit /b 0


:probe_redis
REM Returns errorlevel 0 if Redis answers on :6379, 1 otherwise.
powershell -NoProfile -Command "try { $c = New-Object Net.Sockets.TcpClient; $c.Connect('localhost', 6379); $c.Close(); exit 0 } catch { exit 1 }"
exit /b %errorlevel%


:end
endlocal
