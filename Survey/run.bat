@echo off
REM Survey Application Runner Script (Windows Batch)
setlocal enabledelayedexpansion

cd /d "%~dp0"

if "%1"=="" goto help
if "%1"=="help" goto help
if "%1"=="backend" goto backend
if "%1"=="frontend" goto frontend
if "%1"=="all" goto all
if "%1"=="stop" goto stop

echo Unknown command: %1
goto help

:backend
echo.
echo [INFO] Starting backend API...
echo.
cd src\Survey.Api
if not exist "bin" dotnet restore
echo [INFO] Backend will be available at: https://localhost:5001
echo [INFO] Swagger UI: https://localhost:5001/swagger
echo.
dotnet run
goto end

:frontend
echo.
echo [INFO] Starting frontend UI...
echo.
cd survey-ui
if not exist "node_modules" (
    echo [WARNING] node_modules not found. Installing dependencies...
    call npm install
)
echo [INFO] Frontend will be available at: http://localhost:4200
echo.
call npm start
goto end

:all
echo.
echo [INFO] Starting both backend and frontend...
echo.

REM Start backend in new window
echo [INFO] Starting backend API in new window...
start "Survey Backend API" /D "%~dp0src\Survey.Api" cmd /c "dotnet run"

REM Wait for backend to start
timeout /t 5 /nobreak

REM Start frontend in new window
echo [INFO] Starting frontend UI in new window...
start "Survey Frontend UI" /D "%~dp0survey-ui" cmd /c "npm start"

echo.
echo [SUCCESS] Application is running!
echo ================================
echo Backend API: https://localhost:5001
echo Swagger UI: https://localhost:5001/swagger
echo Frontend UI: http://localhost:4200
echo ================================
echo.
echo Press Ctrl+C in each window to stop the services
echo Or use: run.bat stop
echo.
goto end

:stop
echo.
echo [INFO] Stopping all services...
echo.

REM Kill dotnet processes running Survey.Api
for /f "tokens=2" %%a in ('tasklist ^| findstr "dotnet.exe"') do (
    taskkill /PID %%a /F >nul 2>&1
)

REM Kill node processes (ng serve)
for /f "tokens=2" %%a in ('tasklist ^| findstr "node.exe"') do (
    taskkill /PID %%a /F >nul 2>&1
)

echo [SUCCESS] All services stopped.
echo.
goto end

:help
echo.
echo Survey Application Runner (Windows)
echo.
echo Usage: run.bat [command]
echo.
echo Commands:
echo   backend   - Run only the backend API (https://localhost:5001)
echo   frontend  - Run only the frontend UI (http://localhost:4200)
echo   all       - Run both backend and frontend in separate windows
echo   stop      - Stop all running services
echo   help      - Show this help message
echo.
echo Examples:
echo   run.bat backend    # Start backend API only
echo   run.bat frontend   # Start frontend UI only
echo   run.bat all        # Start both services
echo   run.bat stop       # Stop all services
echo.
goto end

:end
endlocal
