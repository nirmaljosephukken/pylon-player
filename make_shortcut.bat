@echo off
rem Creates (or refreshes) the "Pylon" shortcut on your desktop.
setlocal
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
powershell -NoProfile -Command "$h='%HERE%'; $d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Pylon.lnk')); $s.TargetPath=(Join-Path $h 'Pylon.exe'); $s.Arguments=''; $s.WorkingDirectory=$h; $s.IconLocation=(Join-Path $h 'Pylon.exe') + ',0'; $s.Description='Pylon media player'; $s.Save()"
if errorlevel 1 (echo Couldn't update the shortcut.& pause & exit /b 1)
ie4uinit.exe -show >nul 2>nul
echo Desktop shortcut "Pylon" is ready.
if not "%~1"=="nopause" timeout /t 3 >nul
