## Pylon 1.6.1

### Fixed
- **Picture in picture on Linux (#60).** Switching to picture in picture (Ctrl+P) turned the video black, and it stayed black after going back to the normal window until Pylon was restarted. On X11, turning on "stay on top" made Qt rebuild the window, and VLC lost the window it draws the video into. Pylon now changes the window's settings without rebuilding it, so the video keeps playing in picture in picture and after. Windows and macOS work as before.
- **Bars left behind when moving the window (#59).** While the window was dragged, the top and bottom bars stayed where they were or trailed behind it, more so with videos on a network share. The bars are separate windows that float over the video, and on Linux the system doesn't tell Pylon the window has moved until the drag ends. Pylon now checks where the window really is, hides the bars while it moves and brings them back over the video when it stops. Bars kept on screen with **Keep the controls visible when not in fullscreen** (Preferences > Interface) move with the window instead of hiding.

### Downloads
| | Download |
|---|---|
| Windows 10/11 (64-bit) | `Pylon-Setup-1.6.1.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.6.1-x86_64.AppImage` |
| macOS 14+ (experimental) | `Pylon-1.6.1-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
Both bugs were reproduced on Linux with X11 (Xvfb with the Openbox window manager) and the real VLC 3.0.20 engine, the same VLC as Linux Mint 22.3 in the reports. In 1.6.0, picture in picture went black and stayed black afterwards, and the bars stayed put while the window was dragged by its title bar. With the fix, the video plays in picture in picture, after leaving it, after doing it twice, and after starting from full screen. During a drag the bars are hidden, and they're back over the video once it stops. Pinned bars move with the window.

Automated checks cover picture in picture on Linux (the window gets the borderless and stay-on-top settings and loses them again, without being rebuilt and without VLC being handed a new window, also twice in a row), Windows still using the old way, the bars hiding while the window moves and coming back when it stops, pinned bars following straight away, a drag the system doesn't report (hidden bars, pinned bars following it), tiny differences from display scaling being ignored, and full screen not hiding the bars. All 34 test files pass on Linux, both offscreen and on X11. Cinnamon's window manager (Muffin) and Windows haven't been tried yet.
