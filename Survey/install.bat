@echo off
REM ============================================================
REM  Survey Application - Installation & Setup Script
REM  Run this ONCE to install all dependencies
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   Survey Application - Installation Script
echo ============================================================
echo.

REM ---- Check .NET SDK ----
echo [1/5] Checking .NET SDK...
dotnet --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] .NET SDK not found!
    echo         Download from: https://dotnet.microsoft.com/download/dotnet/8.0
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('dotnet --version') do echo        Found: .NET %%v

REM ---- Check Node.js ----
echo [2/5] Checking Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found!
    echo         Download from: https://nodejs.org/
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node --version') do echo        Found: Node.js %%v

REM ---- Check MySQL ----
echo [3/5] Checking MySQL...
mysql --version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] MySQL CLI not found in PATH.
    echo          Make sure MySQL 8.0+ is installed and running.
    echo          You may need to run sql\init.sql manually.
    echo.
) else (
    for /f "tokens=*" %%v in ('mysql --version') do echo        Found: %%v
)

REM ---- Restore .NET packages ----
echo [4/5] Installing backend dependencies...
echo        Restoring NuGet packages...
cd src\Survey.Api
dotnet restore >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Failed to restore .NET packages!
    pause
    exit /b 1
)
echo        Building backend...
dotnet build --no-restore -c Release >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Build had warnings/errors. Will retry at runtime.
) else (
    echo        Backend build successful.
)
cd /d "%~dp0"

REM ---- Install frontend dependencies ----
echo [5/5] Installing frontend dependencies...
echo        Running npm install (this may take a few minutes)...
cd survey-ui
call npm install
if errorlevel 1 (
    echo [ERROR] npm install failed!
    pause
    exit /b 1
)
echo        Frontend dependencies installed.
cd /d "%~dp0"

echo.
echo ============================================================
echo   Installation Complete!
echo ============================================================
echo.
echo   Next steps:
echo.
echo   1. Make sure MySQL is running
echo   2. Setup database:  mysql -u root -p ^< sql\init.sql
echo   3. Check database password in:
echo      src\Survey.Api\appsettings.json
echo   4. Run the app:  start.bat
echo.
echo ============================================================
echo.
pause
