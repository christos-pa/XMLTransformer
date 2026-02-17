@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "TOOL_DIR=%~dp0"

set "EXE="
set "MULTI="

for /f "delims=" %%F in ('dir /b /s "%TOOL_DIR%xmltransformer*.exe" 2^>nul') do (
  if not defined EXE (
    set "EXE=%%F"
  ) else (
    set "MULTI=1"
  )
)

if not defined EXE (
  echo ERROR: Could not find xmltransformer*.exe under:
  echo   "%TOOL_DIR%"
  pause
  exit /b 1
)

if defined MULTI (
  echo WARNING: Multiple xmltransformer*.exe found. Using:
  echo   "%EXE%"
)

for %%D in ("%EXE%") do set "EXE_DIR=%%~dpD"
set "TASK_NAME=XMLTransformer"
set "RUN_TIME=05:00"

REM Run in the exe folder so config.json/logs resolve properly
set "TASK_CMD=cmd.exe /c ""pushd ""%EXE_DIR%"" ^&^& ""%EXE%"" """

echo Creating scheduled task "%TASK_NAME%" (DAILY %RUN_TIME%)...
schtasks /Create /F ^
  /TN "%TASK_NAME%" ^
  /SC DAILY ^
  /ST %RUN_TIME% ^
  /RL HIGHEST ^
  /TR "%TASK_CMD%" >nul 2>&1

if errorlevel 1 (
  echo ERROR: Failed to create scheduled task.
  echo Try right-clicking INSTALL.bat and "Run as administrator".
  pause
  exit /b 1
)

echo SUCCESS: Installed "%TASK_NAME%".
echo It will run daily at %RUN_TIME%.
pause
exit /b 0
