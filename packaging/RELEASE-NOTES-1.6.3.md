## Pylon 1.6.3

### Fixed
- **Adding to the queue in Shuffle (#65).** In Shuffle mode, what you add to the queue (a file, a folder, a playlist or a channel list) used to go in order at the end, and only turning Shuffle off and on again mixed it in. Added items now land at random places after what's playing, including when the queue was empty or just cleared. Turning Shuffle off still puts everything back in name order, and **Play next** and dragging an item to a spot still put it exactly where you chose.
- **Picture in picture stays on top (#66).** On Windows, the picture in picture window could end up behind another app once you clicked it. Pylon now tells both Qt and Windows that the window stays on top, the Windows call is made in a way that works on 64-bit Windows, and switching to another app says it again. (On Linux with Wayland, apps aren't allowed to keep themselves on top, so it depends on your desktop.)
- **Super Resolution and side panels in full screen (#42).** With Super Resolution on, opening a side panel in full screen switches to a maximized window, but the picture could zoom in and then stay black. Pylon now waits for the window to settle and then has VLC build the picture again at the new size, and a window that came from full screen gets the extra redraws that full screen gets. Closing the panel does the same on the way back to full screen. The rebuild only happens while playing; a paused picture comes back when you press play.

### Downloads
| | Download |
|---|---|
| Windows 10/11 (64-bit) | `Pylon-Setup-1.6.3.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.6.3-x86_64.AppImage` |
| macOS 14+ (experimental) | `Pylon-1.6.3-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
New automated checks (`tests/check_shuffle_pip_vsr.py`) cover the following:
- **Shuffle:** an empty queue fills in a random order, added items go after what's playing at random places while the rest keeps its order, channel lists are mixed in too, leaving Shuffle restores name order, and Play next and the other modes are unchanged.
- **Picture in picture:** Qt's stay-on-top flag is set and cleared with picture in picture, the Windows call is made with handle-sized arguments and its result is checked, and another app coming to the front puts it on top again.
- **Super Resolution:** opening and closing a panel in full screen rebuilds the picture once the window has settled, the later redraws run in the window too, and entering full screen on its own doesn't rebuild anything.

All 36 test files pass on Linux (offscreen, with VLC and ffmpeg installed). Windows hasn't been tried by hand, and the Super Resolution fix still needs checking on an RTX card.
