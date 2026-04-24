@echo off
REM Launch the arq worker (background tasks + scheduled RSS ingestion).
REM Requires Redis to be reachable at the URL in backend\app\config.py
REM (default: redis://localhost:6379/0).

setlocal
set ROOT=%~dp0

echo Starting arq worker...
cd /d %ROOT%backend
arq app.tasks.worker.WorkerSettings

endlocal
