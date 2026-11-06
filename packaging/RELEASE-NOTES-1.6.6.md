## Pylon 1.6.6

### Fixed
- **Floating controls in the wrong place on Wayland (#81).** On Wayland desktops Pylon runs through XWayland, and some window managers there (COSMIC, for one) place small floating windows themselves and ignore later moves. The top and bottom bars ended up stacked near the top of the window and didn't follow it when it was resized. Pylon now places them past the window manager on Wayland desktops, the way menus already work, and hides them while another app is active. On other Linux desktops Pylon checks where the bars really went and does the same if the window manager moved them.
- **Super Resolution still black in full screen (#42).** 1.6.5 stopped VLC from adding black bars of its own, but the picture still went black. The tests on this issue point to a simpler rule: RTX Super Resolution only shows a picture while the video covers the whole screen. So, with Super Resolution on:
  - In full screen, the library and settings panels now float over the video instead of shrinking it, so the video keeps the whole screen.
  - When an aspect ratio, crop or fixed zoom leaves black bars in full screen, Pylon sets Super Resolution aside and shows the picture with normal scaling, with a short message. It comes back when the picture fills the screen again. Switching takes a moment, because VLC only reads this setting when the player starts.
  - In a window nothing changes.

### Changed
- **Keep the controls visible** now makes the top and bottom bars part of the window, above and below the video, instead of separate windows held in place over it. They can't drift or lag behind when the window moves.

### New
- **Sliding side panels (#54, #63).** The library and settings panels slide in from their edge and back out instead of appearing at once. Turn it off in **Preferences > Interface > Slide the side panels in and out**. With Super Resolution on in a window, they open at once, because every step would make VLC redraw the picture.

### Downloads
| | Download |
|---|---|
| Windows 10/11 (64-bit) | `Pylon-Setup-1.6.6.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.6.6-x86_64.AppImage` |
| macOS 14+ | `Pylon-1.6.6-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
New automated checks (`tests/check_overlays_panels_vsr.py`, 18 tests) cover:
- **Floating controls:** XWayland bypasses the window manager and other platforms don't; `PYLON_OVERLAYS=bypass` or `managed` forces either. When the window manager keeps the bars somewhere else, Pylon switches and the bars land where they belong; bars that are where they belong leave things as they are; bypassing bars hide while another app is active.
- **Pinned bars** are part of the window at their full height and float again in full screen or when the setting is off.
- **Sliding panels:** halfway through, the slot is narrower but the panel keeps its width; toggling mid-slide turns around; the setting turns it off.
- **Super Resolution:** in full screen, panels float as native windows above the video, the video keeps its size and the bars stay clear of the panels; leaving full screen lays the panels out again; a 4:3 picture on a 16:9 screen sets Super Resolution aside (VLC is started without it) and 16:9 brings it back; a window leaves it alone.

Checked by hand on Linux (Xvfb, real VLC 3.0.20):
- **#81:** a small window manager that places windows itself and ignores later moves gave the same picture as the report (bottom bar just under the top bar, both off the window). With 1.6.6 both bars land exactly over the video, also after a resize, whether Pylon detects Wayland or notices the move itself. With Openbox, which honours moves, nothing changes.
- **#42:** in full screen with Super Resolution forced on, both panels float over the playing video and the bars sit between them. Super Resolution itself needs an NVIDIA RTX card, so it hasn't been tried with Super Resolution actually running.

All 41 test files pass on Linux under X11 (Xvfb), except `check_cast.py` and `check_waveform.py`, which need a real VLC with a cast device or audio and were skipped. Under Qt's headless offscreen mode, `check_vsr_fit_pin_sliders.py` passes but Python crashes on exit; the same crash happens in a ten-line Qt script without Pylon (a widget moved between a floating window and a window with a native child), and not under X11.
