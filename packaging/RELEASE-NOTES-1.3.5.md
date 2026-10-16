## Pylon 1.3.5 (beta)

[Download Pylon](https://nirmaljosephukken.github.io/pylon-player/)

### Privacy and home screen
- Separate switches in Preferences > Privacy hide Continue watching and Recently played on the home screen (#20). Defaults remain visible. Hiding does not erase history or resume positions, stop history recording, or hide the library's Recent tab.
- Home cards now have right-click actions appropriate to files, folders, playlists and streams (#24). No action deletes media files. Removing an item from history explicitly includes its resume position.
- An Open data folder button is available in Privacy (#21).

### Library and queue
- Music, playlists and saved streams have persistent sorting choices: default order, name A-Z and name Z-A. Playlists also offer Most items. Result counts appear beside the sort controls and update when searching (#21).
- Preferences > Interface has an optional simplified queue-name setting. Video filenames are cleaned for display; playback paths remain unchanged and tooltips retain the original paths. Music metadata and stream labels are preserved (#22).
- Saving a folder as a playlist suggests its folder name, which you can edit (#24).

### Visual fixes and Mac support
- Both neon colour dots fit inside their icon canvas. Custom colour/tint choices use compact buttons and show a swatch only when a custom colour is available (#22).
- Includes the Mac VLC core-before-engine loading correction and original loader-error reporting from the revised 1.3.4 macOS package (#13). Reporters confirmed success with that rebuild; this 1.3.5 package has not been run on a Mac here.

Thanks to @MarioSertorio and @UserSpringRoll for the feedback, and to the Mac reporters for testing.

Ratings (#23) and the music-cover redesign are not included.

### Downloads
- Windows 10/11 (64-bit): Pylon-Setup-1.3.5.exe
- Linux x86-64: Pylon-1.3.5-x86_64.AppImage
- macOS 14+ (experimental): Pylon-1.3.5-macOS.zip

VLC must be installed separately. Upgrading keeps your settings and library. SHA256SUMS.txt contains SHA-256 checksums. SOURCE-MANIFEST.json identifies packaged application source files.

### Validation limits
Automated Qt checks cover history visibility and preservation, queue display, playlist naming, sorting/counts, home-card action logic and colour swatches, alongside the earlier playlist/artist and minimum-layout regressions. Preferences pages were visually inspected. Package source, version metadata, archive integrity, runtime preservation, permissions and symlinks are checked. Linux/macOS runtime testing and a complete fresh-install/auto-update test remain outstanding.

Free and MIT licensed. Inspired by Juxtopposed's VLC redesign, with attribution in the app and repository. Not affiliated with VideoLAN.
