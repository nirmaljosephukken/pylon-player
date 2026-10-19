## Pylon 1.3.9

### Fixed
- **Zoom fills the window.** After a few zoom steps the picture could turn into a box of the wrong shape, a thin strip, or a short band with black around it. VLC 3 reads one of its crop formats as edges instead of a size, so Pylon asked for the wrong part of the picture. Zoom now uses the format VLC reads correctly. Every step fills the window, and the point under the mouse stays put (#41).
- **Top bar in full screen on Mac.** macOS could push the top bar about 30 pixels down, leaving a gap above it. Pylon now puts the bar back if the system moves it (#40).

### New
- **Borderless picture in picture.** Picture in picture no longer has a title bar. Drag the video to move it, drag an edge or corner to resize it, and it can now be made smaller. Clicks still play and pause, and Esc returns to the full window (#42).
- **RTX Video Super Resolution (Windows).** Preferences > Performance can turn on VLC's Super Resolution upscaling, so NVIDIA RTX and Intel graphics can sharpen lower-resolution video on a bigger screen. On NVIDIA, Video Super Resolution also has to be on in the NVIDIA app. Other graphics cards play as before. The change applies straight away and playback continues from the same point (#42).

Thanks to @jackblk, @kimyvgy and @boxdr21-netizen for the reports, and to @jackblk for confirming that 1.3.8 starts on an Apple Silicon Mac (#13).

### Downloads
| | Download |
|---|---|
| Windows 10/11 (64-bit) | `Pylon-Setup-1.3.9.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.3.9-x86_64.AppImage` |
| macOS 14+ (experimental) | `Pylon-1.3.9-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
Tested on Windows 11 with the installer, upgrading over 1.3.8:
- **Zoom:** stepped in with the keyboard up to 244%, zoomed around the mouse pointer with Ctrl+scroll, and dragged to the corners of the picture. The picture filled the window every time.
- **Picture in picture:** moved by dragging, resized from a corner, and returned with Esc. Clicks still play and pause, and drags don't.
- **Super Resolution option:** turned on and off while paused. The frame stayed put and playback continued normally.

Not yet tested:
- **The upscaling effect itself.** It needs an RTX or Intel graphics card.
- **The Mac top bar fix.** It's covered by an automated check that simulates macOS moving the bar, but hasn't been run on a real Mac.
