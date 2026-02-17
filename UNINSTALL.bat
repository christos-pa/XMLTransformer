@echo off
setlocal

set "TASK_NAME=XMLTransformer"

echo Removing scheduled task "%TASK_NAME%"...

schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>&1

if errorlevel 1 (
    echo Task not found or removal failed.
    pause
    exit /b 1
)

echo SUCCESS: Scheduled task "%TASK_NAME%" removed.
pause
exit /b 0
