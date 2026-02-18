@echo off
REM ============================================================
REM  Survey Application - Database Setup
REM  Creates the database and loads seed data
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   Survey Application - Database Setup
echo ============================================================
echo.

mysql --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] MySQL CLI not found in PATH!
    echo         Please add MySQL bin directory to your PATH
    echo         Typical location: C:\Program Files\MySQL\MySQL Server 8.0\bin
    echo.
    echo         Or run the SQL manually:
    echo         Open MySQL Workbench and run: sql\init.sql
    echo.
    pause
    exit /b 1
)

echo This will create/reset the 'surveydb' database with seed data.
echo.
set /p CONFIRM=Continue? (Y/N):
if /i not "%CONFIRM%"=="Y" (
    echo Cancelled.
    pause
    exit /b 0
)

echo.
echo Enter your MySQL root password:
mysql -u root -p < sql\init.sql

if errorlevel 1 (
    echo.
    echo [ERROR] Database setup failed!
    echo         Check your MySQL password and make sure MySQL is running.
) else (
    echo.
    echo [SUCCESS] Database setup complete!
    echo          Database 'surveydb' created with seed data.
)

echo.
pause
