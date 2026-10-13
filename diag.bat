@echo off
rem Plays the last opened file straight through the VLC engine and writes
rem what happens to logs\diag.txt. Useful when filing a bug report.
cd /d "%~dp0"
if not exist logs mkdir logs
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "Python\python.exe" set "PY=Python\python.exe"
if not defined PY if exist "..\Python\python.exe" set "PY=..\Python\python.exe"
if not defined PY (echo Run setup.bat first.& pause & exit /b 1)
echo Testing playback for about 20 seconds. A plain video window may open twice; that's expected.
"%PY%" -X faulthandler diag.py %* > logs\diag.txt 2>&1
echo Done. The result is in logs\diag.txt
pause
