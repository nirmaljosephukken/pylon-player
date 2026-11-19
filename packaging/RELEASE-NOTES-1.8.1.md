## Pylon 1.8.1

Audio only, the picture's quality beside the time, a cap on stream quality and a bigger network buffer for streams, a battery saver, a Right click row and a minimize button in full screen, folders left out of the music scan, and a tidier library when a folder is gone. Most of this release comes from your issues: thank you.

### New
- **Audio only (#95).** Settings > Audio > **Play the sound only, without the picture**, or **Audio only** in the right-click menu. Pylon doesn't decode the picture at all, so it uses less power and data, and Now Playing shows instead of a black screen. It stays on for every file until you turn it off. You can give it a key in Keyboard shortcuts (`F1` opens them).
- **The picture's quality beside the time (#94).** The control bar shows **480p**, **720p**, **1080p** or **4K** next to the time, worked out from the picture's size (a wide film cropped to 1920×800 still counts as 1080p). Hover it for the exact size. For a stream that changes quality as it plays, the badge follows it.
- **Highest stream quality (#94).** Preferences > Playback > **Highest stream quality**: Best available, 1080p, 720p or 480p. It applies to streams that come in several qualities (HLS and DASH links, such as those from the Open in VLC browser extension), so you can be sure a stream plays in SD to save data.
- **Network buffer (#95).** Preferences > Playback > **Network buffer for streams**: 1 second (VLC's default), 3, 5, 10, 30 or 60 seconds. More helps on a slow or patchy connection; a live stream then starts that much later.
- **Battery saver (#97).** Preferences > Performance > **Battery saver: lighter video decoding**. For older laptops and running on battery, Pylon skips some of the smoothing in H.264 video and lets the decoder take shortcuts, so the processor works less and the fan stays quieter. The picture can look a little blockier, and Super Resolution is off while it's on. Hardware decoding, where it works, still saves the most.
- **Right click, Minimize and Quit (#93).** Preferences > Controls has a **Right click** row. Its default, **Open menu**, works as before; pick another action and right-click does that instead, while the menu button in the top bar (and the keyboard's menu key) still open the menu. Every mouse row now also offers **Minimize** and **Quit Pylon**, and both can have keys of their own. In full screen the top bar has a **minimize button**; when you come back, Pylon is still in full screen.
- **Leave a folder out of the music scan (#96).** In the library panel, right-click a folder and choose **Leave out of the music scan** (or right-click an album in the Music tab). Its songs leave the Music tab straight away, and the folders inside it are left out too. Preferences > Interface lists these folders, with **Include in the music scan again**.
- **Extra VLC options (#95).** For advanced users: Preferences > Performance > **Extra VLC options** takes VLC command-line options, the same as the `PYLON_VLC_ARGS` environment variable. If VLC won't start with them, Pylon starts it without them and says so there.

### Fixed
- **Library folders that are gone.** A library folder that was moved, deleted or is on a drive that isn't plugged in is greyed out on the home screen and in the library panel, and says **Folder not found**. Its card's right-click menu has **Remove from library** (every library folder card has it now), and opening it offers **Remove from library** instead of only an error.
- **Downloaded installers stayed in the temporary folder (#92).** The installer that **Update now** downloads (`Pylon-Setup-x.y.z.exe` in `%LOCALAPPDATA%\Temp`) can't delete itself while it runs, so Pylon now deletes it the next time it starts, along with any unfinished download.
- **Zoom with Ctrl and + (#39).** Besides `Ctrl+=` and `Ctrl` with the mouse wheel, `Ctrl` with the `+` key (on the keypad or keyboards where + has its own key) now zooms in too.

### Downloads
| | Download |
|---|---|
| Windows 10/11 (64-bit) | `Pylon-Setup-1.8.1.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.8.1-x86_64.AppImage` |
| macOS 14+ | `Pylon-1.8.1-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
New automated checks for 1.8.1:
- `tests/check_updater_cleanup.py` (#92): installers for this version and older ones, finished or not, are deleted; a newer one, other files and a missing folder are left alone; a file still in use is tried again next time; the window runs it at startup on Windows.
- `tests/check_right_click_minimize.py` (#93, #39): right-click opens the menu by default and runs the chosen action otherwise, the keyboard's menu key still opens the menu, the middle and back buttons can quit and minimize; Preferences shows the Right click row, Minimize and Quit in every row and the new note; the minimize button shows only in full screen; minimizing from full screen comes back in full screen; `Ctrl` and `+` zooms in, unless that key is given to something else.
- `tests/check_stream_quality_audio_only.py` (#94, #95, #97): quality names for common sizes (cropped films, portrait video, 4K); typed VLC options with quotes and stray words; the network buffer and quality cap reach VLC for links only; audio only reaches VLC for every file and shows Now Playing; battery saver's options, with Super Resolution off; Preferences rows; the badge follows the picture; and with real VLC, an unknown extra option starts VLC without it and says so, while good ones start normally.
- `tests/check_music_skip_home_missing.py` (#96, home): a folder left out leaves the Music tab at once and later scans skip it and its subfolders, also when a scan was already running; taking it back in scans again; the library panel menu and the Preferences list; home cards have Remove from library; a missing folder is greyed out, has only Remove from library, and opening it offers to remove it.

All 62 test files pass on Linux under X11 (Xvfb) with real VLC 3.0, at 100% and 150% display scaling, and with Pylon's Windows-only engine paths switched on. Minimize in full screen and the installer clean-up need a try on Windows.
