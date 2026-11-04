## Pylon 1.6.5

### Fixed
- **Super Resolution goes black with a panel open in full screen (#42).** Thanks to the tests on this issue, the cause is now clear: VLC's Super Resolution turns the picture black whenever it has to add black bars around an upscaled picture, even bars one pixel wide. That happened in full screen with a panel open, in a maximized window, and with any aspect ratio that doesn't match the screen. With Super Resolution on, Pylon now draws the black bars itself and gives VLC an area exactly the shape of the picture, so VLC never adds bars of its own. This works with aspect ratios, crops and zoom too. Panels now stay in full screen (1.6.0 to 1.6.4 switched to a maximized window), the picture no longer zooms in from the middle, and closing a panel no longer takes a moment to bring the picture back.
- **Keep the controls visible covers the video (#68, #78).** With **Preferences > Interface > Keep the controls visible when not in fullscreen** on, the bars stayed put but still covered the top and bottom of the picture. The setting never actually made room for them. The video now sits between the bars, so nothing is cut off.

### New
- **Arrow keys on sliders (#79).** Click a slider in the settings panel (brightness, contrast, saturation, gamma, hue, sharpen, the equalizer, speed, subtitle and audio delay, and the rest) and **Left** and **Right** move it one step at a time, so exact values are easy to reach. The selected slider's handle turns the accent colour. Click the video or press **Esc** and the arrow keys jump through the video again.

### Downloads
| | Download |
|---|---|
| Windows 10/11 (64-bit) | `Pylon-Setup-1.6.5.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.6.5-x86_64.AppImage` |
| macOS 14+ | `Pylon-1.6.5-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
New automated checks (`tests/check_vsr_fit_pin_sliders.py`) cover the following:
- **Super Resolution:** Pylon's copy of VLC 3's picture placement (`vout_display_PlacePicture`) confirms that the aspect ratio Pylon sends fills the area to the pixel for 3,000 random window sizes and seven source sizes, and for 1,000 random crops, without overflowing VLC's 32-bit sums. Crop ratios are cut the way VLC cuts them, a fixed zoom is left to VLC, the video area is centred and refitted when a panel opens or the aspect ratio changes, it fills the page again with Super Resolution off, and the redraw nudge swaps between two exact ratios instead of cropping for a moment.
- **Keep the controls visible:** the video sits exactly between the top and bottom bars, and fills the page again when the setting is off.
- **Sliders:** a clicked slider takes Left and Right one step at a time (also on the equalizer), Ctrl+Left and Ctrl+Right still jump a minute, and clicking the video or Esc gives the keys back.

The Super Resolution change was also checked with real VLC 3.0 on Linux (X11, both the X11 and OpenGL outputs): with a white test video, the picture filled VLC's area to the pixel in ten layouts (window, one and two panels, aspect ratios 4:3 and 2.39:1, crop 2.35:1, zoom 2x, an odd window size, after a redraw) for a 1080p MP4, an anamorphic PAL MKV and an MPEG-2 TS, where before it was letterboxed in every one of them. Clicks, double-clicks and the wheel still reach the video. Super Resolution itself needs an NVIDIA RTX card, so it hasn't been tried with Super Resolution actually running.

All 40 test files pass on Linux (offscreen, with VLC and ffmpeg installed).
