## Pylon 1.3.8

### New
- **Custom equalizer.** Audio > Sound now has a **Custom** choice with a preamp and VLC's 10 bands (31 Hz to 16 kHz, -20 to +20 dB). It starts from the preset you were on, changes the sound live as you drag, and is remembered. Per-show presets save the curve too (#38).
- **Equalizer descriptions.** Hover any equalizer preset for a one-line description of how it shapes the sound (#38).
- **Interactive zoom.** Hold Ctrl and scroll over the video to zoom in or out around the mouse pointer, or use Ctrl+= and Ctrl+-. While zoomed in, drag to look around; Ctrl+0 resets. Plain scrolling still changes the volume, and every new file starts unzoomed (#39).
- **Both panels at once.** Ctrl+Shift+L shows or hides the library and the settings sidebar together. Like every shortcut, it can be changed with F1 (#34).
- **Back to the start.** Clicking the Library or Music tab you're already on takes you back to its first page. Back still returns you to where you were (#35).
- **Newest first.** Playlists and streams now list the most recently created first, with Oldest first, Name and Most items still available. Home follows the same order. Renaming a playlist keeps its place, and can no longer overwrite another playlist with the same name (#37).

### Fixed
- **Sharpening while paused.** Changing sharpening used to play a few frames before pausing again. The paused frame now stays exactly where it was, and the time display no longer jumps (#36).
- **Finer sharpening.** The slider now goes from 0 to 1.5 in steps of 0.05 for more precise control. Saved presets above 1.5 use 1.5 (#36).
- **Linux packaging.** The build keeps the keyboard-library fix from 1.3.7 even when rebuilding from an older base package.

Thanks to @UserSpringRoll and @jackblk for the suggestions!

### Downloads
| | Download |
|---|---|
| Windows 10/11 (64-bit) | `Pylon-Setup-1.3.8.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.3.8-x86_64.AppImage` |
| macOS 14+ (experimental) | `Pylon-1.3.8-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
Tested with VLC on Linux: the paused frame staying put after a sharpening change, the custom equalizer changing real audio output, and zooming and panning while playing and while paused. Automated checks cover the shortcuts, tab navigation, playlist ordering and renaming, the equalizer and the zoom maths. The Linux AppImage was started on Fedora 44 and Ubuntu 24.04. The Windows and macOS packages were checked for contents and version; macOS hasn't been run on a real Mac.
