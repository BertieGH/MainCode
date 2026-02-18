@echo off
setlocal enabledelayedexpansion

echo ============================================
echo  SurveyHub - Build Deployment Package
echo ============================================
echo.

set "ROOT=%~dp0.."
set "OUTPUT=%ROOT%\SurveyHub-Deploy"
set "API_DIR=%ROOT%\src\Survey.Api"
set "UI_DIR=%ROOT%\survey-ui"

:: Step 1: Build Angular frontend
echo [1/4] Building Angular frontend...
cd /d "%UI_DIR%"
call npx ng build --configuration production
if errorlevel 1 (
    echo ERROR: Angular build failed!
    exit /b 1
)
echo       Angular build complete.
echo.

:: Step 2: Copy Angular dist into wwwroot
echo [2/4] Copying frontend to wwwroot...
if exist "%API_DIR%\wwwroot" rmdir /s /q "%API_DIR%\wwwroot"
mkdir "%API_DIR%\wwwroot"
xcopy /s /e /q /y "%UI_DIR%\dist\survey-ui\browser\*" "%API_DIR%\wwwroot\"
if errorlevel 1 (
    echo ERROR: Failed to copy Angular build output!
    exit /b 1
)
echo       Frontend copied to wwwroot.
echo.

:: Step 3: Publish .NET as self-contained Windows x64
echo [3/4] Publishing .NET API (self-contained, win-x64)...
cd /d "%API_DIR%"
dotnet publish -c Release -r win-x64 --self-contained -o "%API_DIR%\publish" /p:PublishSingleFile=false
if errorlevel 1 (
    echo ERROR: dotnet publish failed!
    exit /b 1
)
echo       .NET publish complete.
echo.

:: Step 4: Assemble deployment package
echo [4/4] Assembling SurveyHub-Deploy package...
if exist "%OUTPUT%" rmdir /s /q "%OUTPUT%"
mkdir "%OUTPUT%"
mkdir "%OUTPUT%\database"
mkdir "%OUTPUT%\logs"

:: Copy published output (exe + dlls + wwwroot)
xcopy /s /e /q /y "%API_DIR%\publish\*" "%OUTPUT%\"

:: Copy database script
copy /y "%ROOT%\sql\init.sql" "%OUTPUT%\database\init.sql" >nul

:: Copy install script and README
copy /y "%ROOT%\deploy\install.bat" "%OUTPUT%\install.bat" >nul
copy /y "%ROOT%\deploy\README.txt" "%OUTPUT%\README.txt" >nul

:: Rename exe to SurveyHub.exe
if exist "%OUTPUT%\Survey.Api.exe" (
    move /y "%OUTPUT%\Survey.Api.exe" "%OUTPUT%\SurveyHub.exe" >nul
)

echo.
echo ============================================
echo  BUILD COMPLETE!
echo ============================================
echo.
echo  Package location: %OUTPUT%
echo.
echo  Contents:
dir /b "%OUTPUT%"
echo.
echo  To deploy: copy SurveyHub-Deploy folder to target machine
echo  Then run:  install.bat
echo ============================================

endlocal
