@echo off
title LeadPulse Shutdown
echo Stopping LeadPulse services...
echo.
taskkill /FI "WINDOWTITLE eq LeadPulse API" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq LeadPulse Web" /F >nul 2>&1
for /f "tokens=2" %%a in ('tasklist ^| findstr /i "dotnet.exe"') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=2" %%a in ('tasklist ^| findstr /i "node.exe"') do taskkill /PID %%a /F >nul 2>&1
echo All LeadPulse services stopped.
pause
