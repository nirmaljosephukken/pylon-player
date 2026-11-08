## Pylon 1.6.4

### Fixed
- **Close button after picture in picture (#71).** On Windows, after you left picture in picture, the window's ✕ button stayed greyed out and only Menu > Quit closed Pylon. Leaving picture in picture now gives the window back exactly the frame it had before, close button included, and tells Windows directly to turn the ✕ back on.
- **Seek bar keeps following the pointer (#72).** If you held the button on the seek bar and then Alt+Tabbed away, or let go of the button outside Pylon, the bar never heard that you let go and kept following the pointer. The drag now ends when Pylon loses focus, when the bars hide, or as soon as the pointer moves with the button already up. The bar stays where you dragged it.
- **Repeat a part while minimized (#73).** With Repeat a part set, playback ran past the end point while Pylon was minimized and only jumped back once you restored the window. The end point is now checked whether the window is showing or not.
- **Right-click menu on music (#74).** Right-clicking the music page now opens the same menu as on a video (play and pause, stop, close, audio, speed, repeat, cast, bookmarks, panels, picture in picture), without the video-only items like the Video menu, subtitles and snapshots.
- **Picture in picture with music and the interface hidden (#75).** In picture in picture with music playing and the interface hidden, there was nothing to grab. Dragging the music page now moves the window, and its edges resize it, like a video.
- **First song in Shuffle (#76).** In Shuffle mode, **Play Folder** in the library and **Play** on an album, artist or folder in Music always started with the first song and only shuffled the rest. They now start on a random song. Picking a song yourself (double-clicking it) still starts on that song, and a playlist still picks up where you left off.
- **Recently played shows a stream's saved name (#67).** The Recent tab, the home screen's Recently played section and Open > Recent showed a stream's address (like `index.m3u8`) instead of the name you gave it. They now show the saved name, the name of the channel inside a saved channel list, or the title it was played under.

### Downloads
| | Download |
|---|---|
| Windows 10/11 (64-bit) | `Pylon-Setup-1.6.4.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.6.4-x86_64.AppImage` |
| macOS 14+ | `Pylon-1.6.4-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
New automated checks (`tests/check_pip_seek_ab_music.py`) cover the following:
- **Close button:** leaving picture in picture restores the window's original flags with the close button and without borderless or stay-on-top, a frame that lost its close button gets it back, and the Windows call turns the Close item of the system menu on and redraws the frame.
- **Seek bar:** a move with the button up, losing the window, Pylon going to the background and the bar hiding each end a drag where it got to, and dragging with the button down still follows the pointer.
- **Repeat a part:** the loop jumps back to its start while the window is minimized or hidden.
- **Music:** right-clicking the music page opens the menu without the video-only items (the video menu is unchanged), and in picture in picture the page moves the window and shows the resize pointer at the edges, with the interface hidden too.
- **Shuffle:** Play Folder and Play on songs start on a random song in Shuffle, in order otherwise, and a picked song or a playlist's resume point is kept.

`tests/check_recently_played_names.py` covers the Recently played names.

All 38 test files pass on Linux (offscreen, with VLC and ffmpeg installed). Windows hasn't been tried by hand: the close button (#71) and seek bar (#72) fixes in particular need a check on Windows.
