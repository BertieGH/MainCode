@echo off
REM ============================================================
REM  Survey Application - Start
REM  Launches both backend and frontend
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   Survey Application - Starting...
echo ============================================================
echo.

REM ---- Check node_modules ----
if not exist "survey-ui\node_modules" (
    echo [WARNING] Frontend dependencies not installed!
    echo          Run install.bat first.
    echo.
    pause
    exit /b 1
)

REM ---- Start Backend ----
echo [1/2] Starting Backend API...
start "Survey API - https://localhost:5001" /D "%~dp0src\Survey.Api" cmd /k "title Survey API - https://localhost:5001 && color 0A && echo. && echo   Survey Backend API && echo   =================== && echo   URL: https://localhost:5001 && echo   Swagger: https://localhost:5001/swagger && echo   Press Ctrl+C to stop && echo. && dotnet run"

REM Wait for backend to initialize
echo       Waiting for backend to start...
timeout /t 8 /nobreak >nul

REM ---- Start Frontend ----
echo [2/2] Starting Frontend UI...
start "Survey UI - http://localhost:4200" /D "%~dp0survey-ui" cmd /k "title Survey UI - http://localhost:4200 && color 0B && echo. && echo   Survey Frontend UI && echo   ================== && echo   URL: http://localhost:4200 && echo   Press Ctrl+C to stop && echo. && npm start"

echo.
echo ============================================================
echo   Survey Application is starting!
echo ============================================================
echo.
echo   Backend API:  https://localhost:5001
echo   Swagger UI:   https://localhost:5001/swagger
echo   Frontend UI:  http://localhost:4200
echo.
echo   Two new windows opened for backend and frontend.
echo   Wait ~15 seconds for everything to be ready.
echo.
echo   To stop: close both windows or run stop.bat
echo ============================================================
echo.

REM ---- Auto-open browser after delay ----
timeout /t 15 /nobreak >nul
echo Opening browser...
start "" "http://localhost:4200"
