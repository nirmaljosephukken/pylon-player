## Pylon 1.5.0

### New
- **Channel lists in Streams.** Import an `.m3u` channel list with **Import list…** in the Streams tab, or drop `.m3u` files on the list, and Pylon keeps it as one entry with its channel count next to the name. Double-click it to load the channels into the queue, where you can search them. Right-click a list to add more streams (a link or another `.m3u` file), rename it, export it as `.m3u` or remove it. Importing the same file again updates the list instead of adding a copy. A queue made only of streams can also be saved to Streams as a channel list with the save button above the queue. A saved link to an online list, like the Free-TV one, shows its channel count once it has been opened (#44).
- **Pin to top in more tabs.** Right-click a stream, playlist, artist or album and choose **Pin to top**. Pinned items sit in their own group at the top of the tab, whatever the sort order, and pinned streams and playlists also come first on the home screen. The Recent tab is left out, because it is ordered by when you played things (#52).
- **Arrange the home screen.** Preferences > Interface has a new **Home screen sections** list. Drag a section by its handle to move it, and click the eye to show or hide it. Every section can be hidden, and hiding one doesn't delete anything. The home screen also has a new **Music** section with your albums: pinned ones first, then the newest (#53).
- **Recent tab right-click menu.** Items in Recent now have the same choices as files in the Library tab: Play, Add to queue, Play next, Add to playlist, Mark as watched and Show in Explorer. Streams get Copy link and Save to Streams. **Remove from Recent** takes items off the list one at a time (or several at once), along with where you stopped in each (#51).

### Changed
- **Find online keeps the same order.** The subtitle sites menu no longer moves the last site you used to the top. Instead you can choose a preferred site in Preferences > Subtitles, and it gets a star in the menu (#54).
- **Progress bars use your accent colour**, including the download bar when Pylon updates itself (#51).
- **Home screen options moved.** The switches for showing Continue watching, Recently played and Playlists on the home screen are now part of the Home screen sections list in Preferences > Interface, instead of the Privacy tab.

### Fixed
- **Super Resolution in full screen (Windows).** On some PCs the picture could still go black in full screen after opening or closing a panel with RTX Video Super Resolution on. Pylon now redraws again a little later in full screen, and also when a panel opens or closes without changing the picture size (#42).

Thanks to @UserSpringRoll for the suggestions, and to @boxdr21-netizen for testing Super Resolution again.

### Downloads
| | Download |
|---|---|
| Windows 10/11 (64-bit) | `Pylon-Setup-1.5.0.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.5.0-x86_64.AppImage` |
| macOS 14+ (experimental) | `Pylon-1.5.0-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
Automated checks cover the home screen section order, showing and hiding every section (including with a click on the eye), the Music section, the subtitle sites keeping their order with a starred preferred site, the extra Super Resolution redraws in full screen, the Recent menu for files and streams, removing items from Recent, the accent progress bar, pinning and unpinning playlists and streams (including after a rename or delete, with any sort order, and on the home screen), pinned artists and albums, importing a channel list (names, relative paths, importing again, files that aren't lists), dropping a list on the Streams tab, playing a list, adding streams to it without duplicates, exporting it, saving a queue of streams as a list, and the channel count for an online list. All 23 test files pass. The Streams and Playlists tabs with pinned items, the new progress bar, the home screen with its Music section, the Home screen sections list and the Find online menu were also checked on screen. The full-screen Super Resolution fix couldn't be tested on the affected PC. The Linux AppImage was started on Fedora 44 with PipeWire. The macOS package was checked for contents and version, but hasn't been run on a real Mac.
