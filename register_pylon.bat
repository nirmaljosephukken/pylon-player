@echo off
rem Registers Pylon with Windows (for your user account only) so it appears in
rem "Open with" and in Settings > Apps > Default apps. No admin rights needed.
setlocal
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
set "EXE=%HERE%\Pylon.exe"
set "ICO=%HERE%\pylon.ico"
if not exist "%EXE%" (echo Can't find %EXE%& pause & exit /b 1)
set "CMD=\"%EXE%\" \"%%1\""
set "K=HKCU\Software\Classes"
set "C=HKCU\Software\Pylon\Capabilities"

echo Registering Pylon...
rem The file type Pylon opens
reg add "%K%\Pylon.Media" /ve /d "Media file" /f >nul
reg add "%K%\Pylon.Media\DefaultIcon" /ve /d "%ICO%,0" /f >nul
reg add "%K%\Pylon.Media\shell" /ve /d "open" /f >nul
reg add "%K%\Pylon.Media\shell\open" /v FriendlyAppName /d "Pylon" /f >nul
reg add "%K%\Pylon.Media\shell\open\command" /ve /d "%CMD%" /f >nul

rem Pylon.exe itself, so Windows shows it by name with its icon
reg add "%K%\Applications\Pylon.exe" /v FriendlyAppName /d "Pylon" /f >nul
reg add "%K%\Applications\Pylon.exe\DefaultIcon" /ve /d "%ICO%,0" /f >nul
reg add "%K%\Applications\Pylon.exe\shell\open" /v FriendlyAppName /d "Pylon" /f >nul
reg add "%K%\Applications\Pylon.exe\shell\open\command" /ve /d "%CMD%" /f >nul

rem Capabilities, so Pylon is listed in Settings > Apps > Default apps
reg add "%C%" /v ApplicationName /d "Pylon" /f >nul
reg add "%C%" /v ApplicationDescription /d "Pylon media player (VLC engine)" /f >nul
reg add "%C%" /v ApplicationIcon /d "%ICO%,0" /f >nul
reg add "HKCU\Software\RegisteredApplications" /v Pylon /d "Software\Pylon\Capabilities" /f >nul

for %%E in (.3gp .aac .ac3 .aiff .alac .ape .asf .avi .divx .dts .f4v .flac .flv .m2ts .m4a .m4v .mka .mkv .mov .mp3 .mp4 .mpeg .mpg .mts .ogg .ogv .opus .rmvb .ts .vob .wav .webm .wma .wmv) do (
    reg add "%K%\%%E\OpenWithProgids" /v Pylon.Media /t REG_NONE /f >nul
    reg add "%K%\Applications\Pylon.exe\SupportedTypes" /v %%E /t REG_SZ /d "" /f >nul
    reg add "%C%\FileAssociations" /v %%E /d Pylon.Media /f >nul
)

rem Tell Explorer that file associations changed
powershell -NoProfile -Command "Add-Type -Namespace W -Name S -MemberDefinition '[DllImport(\"shell32.dll\")] public static extern void SHChangeNotify(int e,int f,System.IntPtr a,System.IntPtr b);'; [W.S]::SHChangeNotify(0x08000000,0,[System.IntPtr]::Zero,[System.IntPtr]::Zero)" >nul 2>nul

echo.
echo Done. Pylon is registered for 34 video and audio types.
echo Opening Default apps: search for Pylon there, or right-click a video,
echo Open with, Choose another app, Pylon, Always.
start "" ms-settings:defaultapps
if not "%~1"=="nopause" pause
