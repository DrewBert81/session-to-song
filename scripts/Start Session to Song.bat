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

start "" "http://127.0.0.1:8311"
echo Starting Session to Song...
echo Keep this window open while using the app.
"%VPY%" -m session_to_song.web_app
if errorlevel 1 goto failed

echo.
echo Session to Song stopped.
pause
exit /b 0

:failed
echo.
echo Session to Song failed. Copy the error above when asking for help.
pause
exit /b 1
