@echo off
setlocal enabledelayedexpansion

echo ============================================
echo  SurveyHub - Installation Setup
echo ============================================
echo.

set "APP_DIR=%~dp0"

:: Check if mysql is available
where mysql >nul 2>&1
if errorlevel 1 (
    echo WARNING: mysql command not found in PATH.
    echo Please ensure MySQL 8.0+ is installed and mysql.exe is in your PATH.
    echo.
    echo Typical MySQL path: C:\Program Files\MySQL\MySQL Server 8.0\bin
    echo You can add it to PATH or provide the full path below.
    echo.
)

:: Prompt for MySQL connection details
echo --- MySQL Connection Setup ---
echo.
set /p "MYSQL_HOST=MySQL Host [localhost]: " || set "MYSQL_HOST=localhost"
set /p "MYSQL_PORT=MySQL Port [3306]: " || set "MYSQL_PORT=3306"
set /p "MYSQL_USER=MySQL Admin User [root]: " || set "MYSQL_USER=root"
set /p "MYSQL_PASS=MySQL Admin Password: "
echo.

:: Test MySQL connection
echo Testing MySQL connection...
mysql -h %MYSQL_HOST% -P %MYSQL_PORT% -u %MYSQL_USER% -p%MYSQL_PASS% -e "SELECT 1" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Cannot connect to MySQL. Please check your credentials.
    echo.
    pause
    exit /b 1
)
echo MySQL connection successful!
echo.

:: Create database and run init script
echo Setting up database...
mysql -h %MYSQL_HOST% -P %MYSQL_PORT% -u %MYSQL_USER% -p%MYSQL_PASS% < "%APP_DIR%database\init.sql"
if errorlevel 1 (
    echo ERROR: Failed to initialize database!
    pause
    exit /b 1
)
echo Database setup complete!
echo.

:: Create application database user if not exists
echo Creating application database user (surveyapp)...
mysql -h %MYSQL_HOST% -P %MYSQL_PORT% -u %MYSQL_USER% -p%MYSQL_PASS% -e "CREATE USER IF NOT EXISTS 'surveyapp'@'localhost' IDENTIFIED BY 'CGvak123'; GRANT ALL PRIVILEGES ON surveydb.* TO 'surveyapp'@'localhost'; FLUSH PRIVILEGES;"
if errorlevel 1 (
    echo WARNING: Could not create surveyapp user. You may need to update appsettings.json manually.
) else (
    echo Application user created.
)
echo.

:: Update connection string in appsettings.json if host is not localhost
if not "%MYSQL_HOST%"=="localhost" (
    echo NOTE: You are using a non-localhost MySQL host.
    echo Please update the connection string in appsettings.json:
    echo   Server=%MYSQL_HOST%;Port=%MYSQL_PORT%;Database=surveydb;User=surveyapp;Password=CGvak123;
    echo.
)

echo ============================================
echo  INSTALLATION COMPLETE!
echo ============================================
echo.
echo  Starting SurveyHub...
echo  App URL:     http://localhost:5000
echo  Swagger:     http://localhost:5000/swagger
echo  Admin login: admin / Admin123!
echo.
echo  Press Ctrl+C to stop the server.
echo ============================================
echo.

:: Start the application
cd /d "%APP_DIR%"
start "" "http://localhost:5000"
SurveyHub.exe

endlocal
