@echo off
title LeadPulse Launcher
echo ============================================
echo   LeadPulse Application Launcher
echo ============================================
echo.

:: 0. Kill any existing LeadPulse processes
echo [0/4] Stopping previous instances...
taskkill /im LeadPulse.Api.exe /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq LeadPulse API*" /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq LeadPulse Web*" /f >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5051" ^| findstr "LISTENING"') do taskkill /pid %%a /f >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":4200" ^| findstr "LISTENING"') do taskkill /pid %%a /f >nul 2>&1
timeout /t 3 /nobreak >nul
:: Clean locked output files
del /f /q "C:\Users\19254\MainCode\LeadPulse\src\LeadPulse.Api\bin\Debug\net8.0\LeadPulse.Api.exe" >nul 2>&1
del /f /q "C:\Users\19254\MainCode\LeadPulse\src\LeadPulse.Api\bin\Debug\net8.0\LeadPulse.Api.dll" >nul 2>&1
echo       Done.
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
dotnet build --verbosity quiet
if %errorlevel% neq 0 (
    echo       Build failed, trying clean build...
    dotnet clean --verbosity quiet >nul 2>&1
    dotnet build --verbosity quiet
    if %errorlevel% neq 0 (
        echo       ERROR: API build failed.
        pause
        exit /b 1
    )
)
echo       API build successful.
echo.

:: 3. Start API in background
echo [3/4] Starting API on port 5051...
start "LeadPulse API" /min cmd /k "cd /d C:\Users\19254\MainCode\LeadPulse\src\LeadPulse.Api && dotnet run --no-build --urls http://localhost:5051"
echo       API starting in background...
echo.

:: 4. Start Angular in background
echo [4/4] Starting Angular on port 4200...
start "LeadPulse Web" cmd /k "cd /d C:\Users\19254\MainCode\LeadPulse\src\LeadPulse.Web && call node_modules\.bin\ng.cmd analytics disable && call node_modules\.bin\ng.cmd serve --port 4200 --open"
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
