@echo off
rem Pylon setup: installs what Pylon needs into a private folder (.venv) here.
rem Needs: 64-bit Python 3.10+ (python.org) and 64-bit VLC 3.0 (videolan.org).
setlocal EnableExtensions
cd /d "%~dp0"
echo.
echo  Pylon setup
echo  -----------
echo.

rem ---- 1. find Python
set "PY="
where py >nul 2>nul && py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && python -c "import sys" >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo Python isn't installed.
    echo Get the 64-bit installer from https://www.python.org/downloads/windows/
    echo and tick "Add python.exe to PATH" during setup. Then run this again.
    start "" https://www.python.org/downloads/windows/
    pause
    exit /b 1
)
%PY% -c "import sys, struct; ok = sys.version_info >= (3, 10) and struct.calcsize('P') == 8; print('Found Python', sys.version.split()[0], '64-bit' if struct.calcsize('P') == 8 else '32-bit'); sys.exit(0 if ok else 1)"
if errorlevel 1 (
    echo Pylon needs 64-bit Python 3.10 or newer.
    pause
    exit /b 1
)

rem ---- 2. private environment + packages
if not exist ".venv\Scripts\pythonw.exe" (
    echo Creating a private Python environment...
    %PY% -m venv .venv || (echo Couldn't create it.& pause & exit /b 1)
)
echo Installing PySide6 and python-vlc (about 80 MB, first time only)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Installing failed. Check your internet connection and run setup.bat again.
    pause
    exit /b 1
)

rem ---- 3. check VLC
echo.
".venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, '.'); import app.engine as e; print('VLC', e.vlc.libvlc_get_version().decode() if e.vlc else 'NOT FOUND'); sys.exit(0 if e.vlc else 1)" 2>nul
if errorlevel 1 (
    echo VLC wasn't found. Install 64-bit VLC 3.0 from https://www.videolan.org
    echo then run setup.bat again.
    start "" https://www.videolan.org/vlc/download-windows.html
    pause
    exit /b 1
)

rem ---- 4. desktop shortcut and "Open with"
echo.
choice /c YN /m "Add a Pylon shortcut to your desktop"
if not errorlevel 2 call "%~dp0make_shortcut.bat" nopause
choice /c YN /m "Register Pylon with Windows so you can make it your default player"
if not errorlevel 2 call "%~dp0register_pylon.bat" nopause

echo.
echo  Pylon is ready. Start it with Pylon.exe or the desktop shortcut.
echo.
pause
