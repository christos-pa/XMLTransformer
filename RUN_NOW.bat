@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "TOOL_DIR=%~dp0"
set "EXE="

for /f "delims=" %%F in ('dir /b /s "%TOOL_DIR%xmltransformer*.exe" 2^>nul') do (
  if not defined EXE set "EXE=%%F"
)

if not defined EXE (
  echo ERROR: Could not find xmltransformer*.exe under:
  echo   "%TOOL_DIR%"
  pause
  exit /b 1
)

for %%D in ("%EXE%") do set "EXE_DIR=%%~dpD"

pushd "%EXE_DIR%"
"%EXE%"
set "ERR=%ERRORLEVEL%"
popd

echo.
echo Exit code: %ERR%
pause
exit /b %ERR%
