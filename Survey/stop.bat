@echo off
REM ============================================================
REM  Survey Application - Stop All Services
REM ============================================================
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo   Survey Application - Stopping Services...
echo ============================================================
echo.

REM Kill dotnet processes
echo Stopping backend (dotnet)...
taskkill /FI "WINDOWTITLE eq Survey API*" /F >nul 2>&1
for /f "tokens=2" %%a in ('tasklist ^| findstr "dotnet.exe" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)

REM Kill node processes
echo Stopping frontend (node)...
taskkill /FI "WINDOWTITLE eq Survey UI*" /F >nul 2>&1

echo.
echo [DONE] All services stopped.
echo.
pause
