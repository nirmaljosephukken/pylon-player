## Pylon 1.3.10

### Fixed
- **Episodes in order.** Files dropped onto Pylon or opened with Windows' "Open with" played in the order Windows handed them over, which could put episodes out of sequence. They're now sorted by name, the same way as opening a folder (#43).
- **Super Resolution and resizing (Windows).** With RTX Video Super Resolution on, VLC 3 doesn't redraw the picture at a new size. Opening or closing a panel left the picture at the wrong size, and in full screen it could go black while the audio kept playing. Pylon now nudges VLC to redraw at the new size once the resize settles, without restarting or interrupting playback. With the option off nothing changes (#42).
- **Linux AppImage.** As a precaution, the AppImage now ignores a system Qt add-on folder, so it can't mix in add-ons built for a different Qt. The startup log also records the desktop and any Qt settings. This doesn't yet fix the Fedora KDE crash in #28, which still needs the reporter's log to pin down (#28).

### New
- **Rename and copy streams.** Right-click a saved stream in the library to rename it or copy its link. Right-click a stream in the queue to copy its link (#44).
- **More subtitle sites.** Find online now opens a menu of OpenSubtitles.com, OpenSubtitles.org, SubDL, SubSource and Addic7ed. The site you used last is listed first. It searches for the show or film name instead of the full file name, with episode numbers and release tags left out, so results match better (#46).
- **Reset one equalizer band.** Double-click any band or the preamp in the custom equalizer to put just that slider back to 0 dB. Flat still resets everything (#45).
- **Consistent names.** Shortcuts and menus now say "library panel" and "settings panel" instead of mixing "sidebar" and "side panel" (#45).

Thanks to @UserSpringRoll for the suggestions, @boxdr21-netizen for testing Super Resolution, and @butter-fly04 for testing on Fedora and Mint.

### Downloads
| | Download |
|---|---|
| Windows 10/11 (64-bit) | `Pylon-Setup-1.3.10.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.3.10-x86_64.AppImage` |
| macOS 14+ (experimental) | `Pylon-1.3.10-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
Tested on Windows 11 with the installer, upgrading over 1.3.9:
- **Super Resolution:** with the option on, opened and closed the settings and library panels in a window and in full screen, paused and playing. The picture stayed visible and went back to full size every time.
- **Subtitle sites:** the Find online menu lists all five sites. Their search pages were checked in a browser, apart from OpenSubtitles.com, which shows a bot check to automated browsers.
- **Wording:** the new "library panel" and "settings panel" names.

Automated checks cover the episode order for dropped files, renaming streams and copying their links, the equalizer double-click reset, the subtitle search text, and the Super Resolution redraw. All 18 test files pass. The Linux AppImage was started on Ubuntu 24.04 and on Fedora 44 with KDE's Qt add-ons installed, without crashing, but the Fedora KDE crash in #28 hasn't been reproduced yet. The macOS package was checked for contents and version, but hasn't been run on a real Mac.
