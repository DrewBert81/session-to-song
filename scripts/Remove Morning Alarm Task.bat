@echo off
setlocal
set "TASK_NAME=SessionToSong Morning Alarm"

echo Removing scheduled task: %TASK_NAME%
schtasks /Delete /TN "%TASK_NAME%" /F
if errorlevel 1 goto failed

echo Removed.
pause
exit /b 0

:failed
echo Could not remove the task. It may not exist.
pause
exit /b 1
