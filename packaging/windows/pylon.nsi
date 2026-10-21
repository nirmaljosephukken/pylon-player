; Pylon Windows installer (NSIS 3). Build:  makensis -DSRC=<staged Pylon folder> pylon.nsi
; Per-user install: no admin rights needed. VLC is not included; setup checks for it.
Unicode true
!include "MUI2.nsh"
!include "FileFunc.nsh"

!define APP "Pylon"
!define VERSION "1.5.0"
!ifndef SRC
  !define SRC "Pylon"
!endif
!define UNKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\Pylon"

Name "${APP}"
OutFile "Pylon-Setup-${VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\Pylon"
InstallDirRegKey HKCU "Software\Pylon" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
BrandingText "Pylon ${VERSION}"

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "Pylon"
VIAddVersionKey "FileDescription" "Pylon Setup"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "MIT licence, (c) 2026 Nirmal Joseph Ukken"

!define MUI_ICON "${SRC}\pylon.ico"
!define MUI_UNICON "${SRC}\pylon.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Welcome to Pylon ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "Pylon is a calmer, redesigned interface for the VLC engine.$\r$\n$\r$\nIt plays your files with the VLC you have installed. If VLC isn't on this PC yet, setup will point you to it at the end.$\r$\n$\r$\nNo admin rights are needed: Pylon installs just for you."
!define MUI_LICENSEPAGE_TEXT_TOP "Pylon is free and open source (MIT). The bundled Python, Qt and python-vlc have their own licences, listed below and in the licenses folder."
!define MUI_COMPONENTSPAGE_SMALLDESC
!define MUI_FINISHPAGE_RUN "$INSTDIR\Pylon.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Start Pylon"
!define MUI_FINISHPAGE_SHOWREADME "https://github.com/nirmaljosephukken/pylon-player"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Open Pylon's page on GitHub"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "license-summary.txt"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function CloseRunningPylon
  ; a running Pylon locks its files; close copies that run from the install folder
  nsExec::Exec `powershell -NoProfile -Command "Get-Process pythonw,python -ErrorAction SilentlyContinue | Where-Object { $$_.Path -like '$INSTDIR\*' } | Stop-Process -Force"`
  Pop $0
FunctionEnd

Section "Pylon (required)" SecMain
  SectionIn RO
  Call CloseRunningPylon
  SetOutPath "$INSTDIR"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\Python"
  File /r /x "__pycache__" /x "*.pyc" "${SRC}\*.*"
  WriteUninstaller "$INSTDIR\Uninstall Pylon.exe"
  WriteRegStr HKCU "Software\Pylon" "InstallDir" "$INSTDIR"

  CreateShortcut "$SMPROGRAMS\Pylon.lnk" "$INSTDIR\Pylon.exe" "" "$INSTDIR\Pylon.exe" 0 SW_SHOWNORMAL "" "Pylon media player"

  WriteRegStr HKCU "${UNKEY}" "DisplayName" "Pylon"
  WriteRegStr HKCU "${UNKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNKEY}" "Publisher" "Nirmal Joseph Ukken"
  WriteRegStr HKCU "${UNKEY}" "DisplayIcon" "$INSTDIR\Pylon.exe,0"
  WriteRegStr HKCU "${UNKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNKEY}" "URLInfoAbout" "https://github.com/nirmaljosephukken/pylon-player"
  WriteRegStr HKCU "${UNKEY}" "UninstallString" '"$INSTDIR\Uninstall Pylon.exe"'
  WriteRegStr HKCU "${UNKEY}" "QuietUninstallString" '"$INSTDIR\Uninstall Pylon.exe" /S'
  WriteRegDWORD HKCU "${UNKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNKEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNKEY}" "EstimatedSize" "$0"
SectionEnd

Section "Desktop shortcut" SecDesktop
  CreateShortcut "$DESKTOP\Pylon.lnk" "$INSTDIR\Pylon.exe" "" "$INSTDIR\Pylon.exe" 0 SW_SHOWNORMAL "" "Pylon media player"
SectionEnd

Section "Offer Pylon for videos and music (Open with)" SecAssoc
  WriteRegStr HKCU "Software\Classes\Pylon.Media" "" "Media file"
  WriteRegStr HKCU "Software\Classes\Pylon.Media\DefaultIcon" "" "$INSTDIR\pylon.ico,0"
  WriteRegStr HKCU "Software\Classes\Pylon.Media\shell" "" "open"
  WriteRegStr HKCU "Software\Classes\Pylon.Media\shell\open" "FriendlyAppName" "Pylon"
  WriteRegStr HKCU "Software\Classes\Pylon.Media\shell\open\command" "" '"$INSTDIR\Pylon.exe" "%1"'
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe" "FriendlyAppName" "Pylon"
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\DefaultIcon" "" "$INSTDIR\pylon.ico,0"
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\shell\open" "FriendlyAppName" "Pylon"
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\shell\open\command" "" '"$INSTDIR\Pylon.exe" "%1"'
  WriteRegStr HKCU "Software\Pylon\Capabilities" "ApplicationName" "Pylon"
  WriteRegStr HKCU "Software\Pylon\Capabilities" "ApplicationDescription" "Pylon media player (VLC engine)"
  WriteRegStr HKCU "Software\Pylon\Capabilities" "ApplicationIcon" "$INSTDIR\pylon.ico,0"
  WriteRegStr HKCU "Software\RegisteredApplications" "Pylon" "Software\Pylon\Capabilities"
  WriteRegStr HKCU "Software\Classes\.3gp\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".3gp" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".3gp" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.aac\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".aac" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".aac" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.ac3\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".ac3" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".ac3" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.aiff\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".aiff" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".aiff" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.alac\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".alac" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".alac" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.ape\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".ape" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".ape" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.asf\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".asf" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".asf" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.avi\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".avi" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".avi" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.divx\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".divx" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".divx" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.dts\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".dts" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".dts" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.f4v\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".f4v" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".f4v" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.flac\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".flac" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".flac" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.flv\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".flv" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".flv" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.m2ts\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".m2ts" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".m2ts" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.m4a\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".m4a" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".m4a" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.m4v\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".m4v" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".m4v" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.mka\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".mka" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".mka" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.mkv\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".mkv" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".mkv" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.mov\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".mov" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".mov" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.mp3\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".mp3" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".mp3" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.mp4\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".mp4" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".mp4" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.mpeg\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".mpeg" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".mpeg" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.mpg\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".mpg" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".mpg" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.mts\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".mts" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".mts" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.ogg\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".ogg" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".ogg" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.ogv\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".ogv" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".ogv" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.opus\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".opus" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".opus" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.rmvb\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".rmvb" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".rmvb" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.ts\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".ts" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".ts" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.vob\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".vob" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".vob" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.wav\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".wav" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".wav" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.webm\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".webm" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".webm" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.wma\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".wma" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".wma" "Pylon.Media"
  WriteRegStr HKCU "Software\Classes\.wmv\OpenWithProgids" "Pylon.Media" ""
  WriteRegStr HKCU "Software\Classes\Applications\Pylon.exe\SupportedTypes" ".wmv" ""
  WriteRegStr HKCU "Software\Pylon\Capabilities\FileAssociations" ".wmv" "Pylon.Media"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
SectionEnd

!macro TryVLC DIR
  StrCmp $1 "" 0 +4
  StrCmp "${DIR}" "" +3
  IfFileExists "${DIR}\libvlc.dll" 0 +2
  GetFullPathName $1 "${DIR}"
!macroend

Section "-Check for VLC"
  ; Look where Pylon itself does, so a VLC next to the install folder (or a folder
  ; above it, e.g. E:\Apps\Pylon-1.1\Pylon with E:\Apps\VLC) is found too.
  StrCpy $1 ""
  SetRegView 64
  ReadRegStr $0 HKLM "Software\VideoLAN\VLC" "InstallDir"
  SetRegView lastused
  !insertmacro TryVLC "$0"
  ReadRegStr $0 HKCU "Software\VideoLAN\VLC" "InstallDir"
  !insertmacro TryVLC "$0"
  !insertmacro TryVLC "$PROGRAMFILES64\VideoLAN\VLC"
  !insertmacro TryVLC "$INSTDIR\VLC"
  !insertmacro TryVLC "$INSTDIR\..\VLC"
  !insertmacro TryVLC "$INSTDIR\..\..\VLC"
  !insertmacro TryVLC "$INSTDIR\..\..\..\VLC"
  !insertmacro TryVLC "$INSTDIR\..\VideoLAN\VLC"
  !insertmacro TryVLC "$INSTDIR\..\..\VideoLAN\VLC"
  Delete "$INSTDIR\vlc-path.txt"
  StrCmp $1 "" vlc_missing
  FileOpen $2 "$INSTDIR\vlc-path.txt" w   ; Pylon reads this first
  FileWrite $2 "$1"
  FileClose $2
  Goto vlc_ok
  vlc_missing:
  MessageBox MB_YESNO|MB_ICONINFORMATION "Pylon plays media with VLC, and VLC (64-bit) wasn't found on this PC.$\r$\n$\r$\nOpen the VLC download page now? Install VLC, then start Pylon.$\r$\n$\r$\n(If you use a portable VLC, choose No: Pylon will let you pick its folder.)" /SD IDNO IDNO vlc_ok
  ExecShell "open" "https://www.videolan.org/vlc/download-windows.html"
  vlc_ok:
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} "Pylon with its own private copy of Python and Qt (about 90 MB)."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "Put a Pylon shortcut on your desktop."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecAssoc} "List Pylon under 'Open with' for 34 video and audio types, so you can make it your default player in Windows Settings. Doesn't change your current default."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  Call un.CloseRunningPylon
  Delete "$SMPROGRAMS\Pylon.lnk"
  Delete "$DESKTOP\Pylon.lnk"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\Python"
  RMDir /r "$INSTDIR\licenses"
  RMDir /r "$INSTDIR\logs"
  Delete "$INSTDIR\Pylon.exe"
  Delete "$INSTDIR\main.py"
  Delete "$INSTDIR\pylon.ico"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\THIRD_PARTY_NOTICES.md"
  Delete "$INSTDIR\diag.py"
  Delete "$INSTDIR\diag.bat"
  Delete "$INSTDIR\vlc-path.txt"
  Delete "$INSTDIR\Uninstall Pylon.exe"
  RMDir "$INSTDIR"

  DeleteRegKey HKCU "Software\Classes\Pylon.Media"
  DeleteRegKey HKCU "Software\Classes\Applications\Pylon.exe"
  DeleteRegValue HKCU "Software\RegisteredApplications" "Pylon"
  DeleteRegValue HKCU "Software\Classes\.3gp\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.aac\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.ac3\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.aiff\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.alac\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.ape\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.asf\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.avi\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.divx\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.dts\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.f4v\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.flac\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.flv\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.m2ts\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.m4a\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.m4v\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.mka\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.mkv\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.mov\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.mp3\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.mp4\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.mpeg\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.mpg\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.mts\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.ogg\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.ogv\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.opus\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.rmvb\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.ts\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.vob\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.wav\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.webm\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.wma\OpenWithProgids" "Pylon.Media"
  DeleteRegValue HKCU "Software\Classes\.wmv\OpenWithProgids" "Pylon.Media"
  DeleteRegKey HKCU "Software\Pylon"
  DeleteRegKey HKCU "${UNKEY}"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
  ; your library, history and presets (%APPDATA%\Pylon) are kept
SectionEnd

Function un.CloseRunningPylon
  nsExec::Exec `powershell -NoProfile -Command "Get-Process pythonw,python -ErrorAction SilentlyContinue | Where-Object { $$_.Path -like '$INSTDIR\*' } | Stop-Process -Force"`
  Pop $0
FunctionEnd
