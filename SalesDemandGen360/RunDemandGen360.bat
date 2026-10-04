@echo off
REM ===========================================================================
REM  Sales Demand Gen360 - start the whole application.
REM
REM  Two servers, each in its own window so its log stays readable:
REM    backend   FastAPI on 127.0.0.1:8011  (the port web\proxy.conf.json
REM              targets - change both together or the UI gets no data)
REM    frontend  Angular dev server on 127.0.0.1:4200
REM
REM  What it does, in order, and why each step is here:
REM
REM   1. Stops anything already serving on those two ports. It used to refuse
REM      to start instead, which is what "the batch file does nothing" usually
REM      was: a server left over from an earlier session, or an old API still
REM      running code from before the last change - new screens then fail with
REM      "Could not load ..." because the routes they call do not exist yet.
REM      Kills by port, exactly as CloseDemandGen360.bat does.
REM
REM   2. Brings the database schema up to date (alembic upgrade head). A new
REM      table that has not been migrated fails the first request that reads
REM      it, which looks like a broken app rather than a missing step.
REM      Safe to run every time: it does nothing when already current.
REM
REM   3. Starts each server and waits until it actually ANSWERS over HTTP, not
REM      merely until its port is open - a port can be open before the app
REM      behind it is ready, and a browser opened then shows an error.
REM
REM  Both bind to 127.0.0.1 rather than the Angular default, which resolves to
REM  the IPv6 loopback only and refuses IPv4 clients outright.
REM
REM  The browser is opened at that SAME address, deliberately. 127.0.0.1 and
REM  localhost are one server but two browser origins, and localStorage does
REM  not cross between them - so the "Browse anyway" choice that unlocks the
REM  menu while setup is incomplete is stored against whichever one you were
REM  on. Open the other and the menu is locked again, which reads as a broken
REM  app rather than an unconfigured one. Bind and open must not disagree.
REM ===========================================================================
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "VENV=%ROOT%.venv\Scripts\python.exe"
set "BACKEND=%ROOT%backend"
set "WEB=%ROOT%web"
set "API_PORT=8011"
set "WEB_PORT=4200"
set "CURL=%SystemRoot%\System32\curl.exe"
set "MIGRATE_LOG=%TEMP%\demandgen360-migrate.log"

echo.
echo   Sales Demand Gen360
echo   -------------------

if not exist "%VENV%" (
    echo   [X] No virtualenv at %VENV%
    echo       Create it first, then re-run this script.
    goto :fail
)
if not exist "%WEB%\node_modules" (
    echo   [X] No node_modules in %WEB%
    echo       Run "npm install" in that folder first.
    goto :fail
)
if not exist "%CURL%" (
    echo   [X] curl.exe not found at %CURL%
    echo       It ships with Windows 10 1803 and later.
    goto :fail
)

REM --- 1. clear the ports ----------------------------------------------------
call :killport %API_PORT% "API"
call :killport %WEB_PORT% "frontend"

REM --- 2. database schema ----------------------------------------------------
echo   Updating the database schema...
pushd "%BACKEND%"
"%VENV%" -m alembic upgrade head > "%MIGRATE_LOG%" 2>&1
set "MIGRATE_RC=%ERRORLEVEL%"
popd
if not "%MIGRATE_RC%"=="0" (
    echo   [X] The database migration failed. Is PostgreSQL running?
    echo       Last lines of %MIGRATE_LOG%:
    echo.
    powershell -NoProfile -Command "Get-Content -Tail 15 '%MIGRATE_LOG%'"
    goto :fail
)
echo   Schema is current.

REM --- 3. the servers --------------------------------------------------------
echo   Starting API       http://127.0.0.1:%API_PORT%
start "DemandGen360 API" cmd /k "cd /d "%BACKEND%" && "%VENV%" -m uvicorn app.main:app --reload --host 127.0.0.1 --port %API_PORT%"

call :waitfor "http://127.0.0.1:%API_PORT%/api/health" 40
if not "%READY%"=="1" (
    echo   [X] The API did not answer after ~2 minutes.
    echo       Check the "DemandGen360 API" window for the error.
    goto :fail
)
echo   API is answering.

echo   Starting frontend  http://127.0.0.1:%WEB_PORT%
start "DemandGen360 Web" cmd /k "cd /d "%WEB%" && npx ng serve --host 127.0.0.1 --port %WEB_PORT%"

REM  The first Angular build takes a while; opening the browser before it is
REM  ready shows a connection error and invites a pointless second start.
echo   Waiting for the frontend to finish its first build...
call :waitfor "http://127.0.0.1:%WEB_PORT%/" 60
if not "%READY%"=="1" (
    echo   [!] The frontend still is not answering after ~3 minutes.
    echo       Check the "DemandGen360 Web" window for a build error.
    goto :done
)

echo   Ready. Opening the browser.
REM  The same origin the server binds to - see the header. Do not change one
REM  of these without the other.
start "" "http://127.0.0.1:%WEB_PORT%/"

:done
echo.
echo   Both servers run in their own windows.
echo   Close them with CloseDemandGen360.bat (closing this window does not
echo   stop them).
echo.
pause
exit /b 0

:fail
echo.
pause
exit /b 1

REM --- stop whatever listens on port %1, described as %2 ---------------------
REM  /T as well as /F: uvicorn --reload runs a reloader that owns the real
REM  server, and the Angular CLI spawns esbuild workers. Killing only the
REM  parent leaves the port held.
:killport
set "PORT=%~1"
set "WHAT=%~2"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:"127.0.0.1:%PORT% .*LISTENING" /C:"0.0.0.0:%PORT% .*LISTENING" /C:"\[::\]:%PORT% .*LISTENING" /C:"\[::1\]:%PORT% .*LISTENING"') do (
    if not "%%P"=="0" (
        echo   Stopping an earlier %WHAT% on %PORT% ^(PID %%P^)
        taskkill /F /T /PID %%P >nul 2>&1
    )
)
REM  Give Windows a moment to release the socket before it is bound again.
"%SystemRoot%\System32\ping.exe" -n 2 127.0.0.1 >nul 2>&1
exit /b 0

REM --- wait until URL %1 answers 2xx, trying up to %2 times; sets READY -----
:waitfor
set "READY=0"
set /a TRIES=0
:waitloop
set /a TRIES+=1
"%CURL%" -s -f -o nul --max-time 2 "%~1" >nul 2>&1
if not errorlevel 1 (
    set "READY=1"
    exit /b 0
)
if %TRIES% GEQ %~2 exit /b 0
"%SystemRoot%\System32\ping.exe" -n 3 127.0.0.1 >nul 2>&1
goto :waitloop
