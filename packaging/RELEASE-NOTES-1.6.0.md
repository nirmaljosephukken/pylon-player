## Pylon 1.6.0

### New
- **DVDs.** Pylon now plays DVD images (`.iso`) and copied DVD folders (a `VIDEO_TS` folder, or a folder that holds one). Before, `.iso` files weren't offered in the Open window, the library or "Open with", and a DVD folder opened as a pile of separate `.vob` files. A disc now opens at its own menu. In the menu, the arrow keys move between the buttons and Enter (or Space, or a click on the video) chooses one. The Playback tab of the settings panel gets a **Disc** section with the disc's titles, arrow buttons and **Disc menu**, and the right-click menu has a **Disc** menu too. DVD folders in the library show a disc icon and play with a double-click. Pylon remembers which title you were watching and where, and picks up there next time. Seek previews and the waveform are skipped for discs.
- **Waveform in the seek bar.** For music, the seek bar can show the song's loud and quiet parts, so you can find a chorus or the start of the next track. Pylon reads the sound in the background (well under a second for a song, a few seconds for a film) and keeps it for next time. Choose **For music**, **For music and videos** or **Off** in Preferences > Interface.
- **Repeat a part (A–B).** Press **L** at the start of a part and **L** again at its end, and Pylon plays that part over and over until you press **L** a third time. The part is tinted in the seek bar. It can also be set from the Playback tab or the right-click menu (**Repeat a part**).
- **Step back a frame.** **Shift+E** pauses and goes back one frame, the opposite of **E**. It doesn't work on DVDs, which can only jump to about every half second.
- **Cast to a Chromecast.** Menu > **Cast to** looks for Chromecasts on your network and sends the video there, from the point you were at. While casting, the top bar says where it's playing. **This computer** brings it back. Pylon only looks for devices once you open the Cast menu.
- **Shuffle all in Music.** The shuffle button next to the search box plays every song in the view (an album, an artist or all your music) in a random order. Albums, artists and songs also have **Shuffle** in their right-click menu.
- **Sort music by Recently played and Most played.** Pylon now counts how often you play each song (only on your computer, and cleared with Clear history).
- **Sort playlists by how much you've watched**: **Least watched first** or **Most watched first**. Hover a playlist to see how many of its items you've watched.

### Fixed
- **Playlists and the queue sort by file name (#58).** A folder could end up in the order of its files' tags, and **Sort by name** didn't fix it. Two things caused this. A playlist (`.m3u`) made by another player carries the titles that player read from the tags, and Sort by name sorted by those titles. Now files always sort by file name, and the queue still shows the titles. Also, Windows hands over the files chosen in an Open window in the order you selected them, so they're now put in name order, the same as dropped files (#43). Sorting a playlist also sorts the queue when that playlist is the one playing.
- **Super Resolution in full screen (#42).** In 1.5.1, keeping the picture one pixel short of the bottom edge turned it black as soon as full screen started, so that change is undone. Full screen works again as it did in 1.5.0. A panel opened in full screen still turned the picture black there, while panels work in a window. So with Super Resolution on, opening a panel in full screen now switches to a maximized window, and closing the last panel goes back to full screen. Going into full screen closes any open panels. This couldn't be tested on an RTX card, so please say in #42 whether it helps.

### Changed
- Under the hood, the two largest files (`window.py` and `library.py`) are split into smaller modules: the window's menus, playback and system parts, and the library's Music and queue parts. Nothing changes on screen.

### Downloads
| | Download |
|---|---|
| Windows 10/11 (64-bit) | `Pylon-Setup-1.6.0.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.6.0-x86_64.AppImage` |
| macOS 14+ (experimental) | `Pylon-1.6.0-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
Automated checks cover DVD images and folders (finding them, opening them at the menu with no start time, `dvd://` for folders), the arrow keys and Enter in a disc menu and as normal in a title, the Disc section and Disc menu, saving the title and time but not the menu loop, resuming at the title then the time, DVD folders in the library, no previews or waveform for discs; the waveform from a WAV (quiet and loud halves, stereo, empty files), Windows paths with spaces in VLC's options, the cache, drawing it with bookmarks and an A–B part, the Preferences choice; A–B repeat with L, the panel and the menu, an end before the start, jumping back at the end without jumping twice, clearing it for a new file; stepping back a frame at 25 and 50 fps and at the start; casting (devices appearing once, going away and being let go of, reopening at the same point, the Cast menu, the top bar chip, a menu refreshing as devices appear); play counts, Recently played and Most played for songs and albums, Shuffle all for all songs and one album, playlist progress sorting; and the module split. Also file name order for `.m3u` entries with tag titles, Open-window picks and sorting a playing playlist, with channels still sorting by name (#58); and full screen with Super Resolution: no margin, a panel opening in a maximized window and closing back to full screen, Esc while a panel is open, panels closed on entering full screen, and nothing changed without Super Resolution or off Windows (#42). All 33 test files pass.

Also run against the real VLC 3.0.20 engine on Linux: a test DVD image with a two-button menu (the menu is found, Down and Enter start the second title, Disc menu goes back to it, and resuming lands on the saved title and time), the waveform of a two-minute video (read in under half a second, quiet and loud halves correct), and stepping back frame by frame in a video (exact 40 ms steps). Casting could not be tried with a real Chromecast. The Windows installer, Linux AppImage and macOS package haven't been built for this version.
