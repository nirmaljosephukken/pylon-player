@echo off
rem Removes everything register_pylon.bat added. Your media files are not touched.
setlocal
set "K=HKCU\Software\Classes"
reg delete "%K%\Pylon.Media" /f >nul 2>nul
reg delete "%K%\Applications\Pylon.exe" /f >nul 2>nul
reg delete "HKCU\Software\Pylon" /f >nul 2>nul
reg delete "HKCU\Software\RegisteredApplications" /v Pylon /f >nul 2>nul
for %%E in (.3gp .aac .ac3 .aiff .alac .ape .asf .avi .divx .dts .f4v .flac .flv .m2ts .m4a .m4v .mka .mkv .mov .mp3 .mp4 .mpeg .mpg .mts .ogg .ogv .opus .rmvb .ts .vob .wav .webm .wma .wmv) do reg delete "%K%\%%E\OpenWithProgids" /v Pylon.Media /f >nul 2>nul
echo Pylon is no longer registered with Windows.
pause
