@echo off
setlocal
cd /d "%~dp0.."

set "DEFAULT_TARGET=%USERPROFILE%\My Drive\sessiontosong\alarms"
set /p TARGET_DIR=Alarm sync folder [%DEFAULT_TARGET%]: 
if "%TARGET_DIR%"=="" set "TARGET_DIR=%DEFAULT_TARGET%"

set "DEFAULT_TIME=03:30"
set /p RUN_TIME=Daily update time, 24-hour HH:MM [%DEFAULT_TIME%]: 
if "%RUN_TIME%"=="" set "RUN_TIME=%DEFAULT_TIME%"

if not exist "%TARGET_DIR%" (
  echo.
  echo Folder does not exist:
  echo %TARGET_DIR%
  echo.
  echo Create/select the synced folder first, then run this again.
  pause
  exit /b 1
)

set "REPO_ROOT=%CD%"
set "TASK_NAME=SessionToSong Morning Alarm"
set "ACTION=powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\scripts\run_morning_alarm.ps1" -RepoRoot "%REPO_ROOT%" -TargetDir "%TARGET_DIR%" -Python "%REPO_ROOT%\.venv\Scripts\python.exe""

echo.
echo Creating scheduled task:
echo %TASK_NAME%
echo Time: %RUN_TIME%
echo Target folder: %TARGET_DIR%
echo.

schtasks /Create /TN "%TASK_NAME%" /SC DAILY /ST %RUN_TIME% /TR "%ACTION%" /F
if errorlevel 1 goto failed

echo.
echo Morning alarm task installed.
echo It will update S2S-morning.mp3 every day at %RUN_TIME%.
pause
exit /b 0

:failed
echo.
echo Failed to create scheduled task. Try running this script as your normal logged-in Windows user.
pause
exit /b 1
