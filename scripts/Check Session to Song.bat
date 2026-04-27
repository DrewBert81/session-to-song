@echo off
setlocal
cd /d "%~dp0.."

set "VPY=.venv\Scripts\python.exe"
if not exist "%VPY%" (
  echo Local app environment was not found.
  echo Run "Install Session to Song.bat" first.
  pause
  exit /b 1
)

"%VPY%" -m session_to_song.cli doctor
if errorlevel 1 goto failed
echo.
pause
exit /b 0

:failed
echo.
echo Setup check found a problem. Copy the message above when asking for help.
pause
exit /b 1
