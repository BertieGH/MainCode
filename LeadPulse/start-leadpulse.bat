@echo off
title LeadPulse Launcher
echo ============================================
echo   LeadPulse Application Launcher
echo ============================================
echo.

:: 1. Check and start MySQL
echo [1/4] Checking MySQL...
sc query mysql80 | find "RUNNING" >nul 2>&1
if %errorlevel% neq 0 (
    echo       Starting MySQL service...
    net start mysql80
    if %errorlevel% neq 0 (
        echo       ERROR: Failed to start MySQL. Try running as Administrator.
        pause
        exit /b 1
    )
    echo       MySQL started.
) else (
    echo       MySQL is already running.
)
echo.

:: 2. Build backend
echo [2/4] Building API...
cd /d C:\Users\19254\MainCode\LeadPulse\src\LeadPulse.Api
dotnet build --no-restore -q
if %errorlevel% neq 0 (
    echo       ERROR: API build failed.
    pause
    exit /b 1
)
echo       API build successful.
echo.

:: 3. Start API in background
echo [3/4] Starting API on port 5051...
start "LeadPulse API" /min cmd /c "cd /d C:\Users\19254\MainCode\LeadPulse\src\LeadPulse.Api && dotnet run --urls http://localhost:5051"
echo       API starting in background...
echo.

:: 4. Start Angular in background
echo [4/4] Starting Angular on port 4200...
start "LeadPulse Web" /min cmd /c "cd /d C:\Users\19254\MainCode\LeadPulse\src\LeadPulse.Web && npx ng serve --port 4200"
echo       Angular starting in background...
echo.

:: 5. Wait for API to be ready
echo Waiting for services to start...
timeout /t 10 /nobreak >nul

echo.
echo ============================================
echo   LeadPulse is running!
echo   API:      http://localhost:5051
echo   Web App:  http://localhost:4200
echo ============================================
echo.
echo Close the "LeadPulse API" and "LeadPulse Web"
echo command windows to stop the application.
echo.
pause
