@echo off
setlocal
cd /d "%~dp0.."

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  set "PY=py -3"
) else (
  where python >nul 2>nul
  if %ERRORLEVEL% EQU 0 (
    set "PY=python"
  ) else (
    echo Python 3 is required.
    echo Install it from https://www.python.org/downloads/ and check "Add python.exe to PATH".
    pause
    exit /b 1
  )
)

echo Creating local app environment...
%PY% -m venv .venv
if errorlevel 1 goto failed

set "VPY=.venv\Scripts\python.exe"
if not exist "%VPY%" goto failed

echo Installing Session to Song...
"%VPY%" -m pip install --upgrade pip
if errorlevel 1 goto failed
"%VPY%" -m pip install -e ".[google-audio]"
if errorlevel 1 goto failed
"%VPY%" -m session_to_song.cli init
if errorlevel 1 goto failed

echo.
echo Install complete.
echo Double-click "Start Session to Song.bat" to open the app.
pause
exit /b 0

:failed
echo.
echo Install failed. Copy the error above when asking for help.
pause
exit /b 1
