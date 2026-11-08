## Pylon 1.7.0

A feature release: visualizations and silence skipping for music, plus the fixes that were lined up for 1.6.6.

### New
- **Audio visualizations (#85).** **Settings > Audio > Visualization** shows one of VLC's visualizations instead of the cover while a song or other sound without video plays: **Spectrum**, **Scope**, **VU meter**, **Spectrometer**, **Goom** or **3D spectrum**. A song that's playing continues from the same spot with the new one; while a video plays, it starts with the next song. Goom and 3D spectrum aren't in every VLC build (some Linux distributions leave them out), and Pylon says so if the one you picked can't show.
- **Skip silence (#86).** **Settings > Audio > Skip silence at the start and end of songs** jumps past the quiet part before the music starts and moves on to the next song (or stops, loops, or pauses for the sleep timer, as usual) once only silence is left. Pylon finds the silence from the same quick read of the sound it already does for the waveform in the seek bar, so each song is read once and remembered. Gaps shorter than a moment are left alone, a song resumed in the middle isn't sent back, and a repeated part (A–B) always wins. It's off by default.
- **Sliding side panels (#54, #63).** The library and settings panels slide in from their edge and back out instead of appearing at once. Turn it off in **Preferences > Interface > Slide the side panels in and out**. With Super Resolution on in a window, they open at once, because every step would make VLC redraw the picture.

### Fixed
- **Black picture with 10-bit HEVC videos on Windows (#82).** Some graphics drivers showed the subtitles over a black picture for hardware-decoded 10-bit HEVC until VLC's video area changed size, which is why opening the settings panel brought the picture back. Pylon now gives the video area that same tiny change, invisibly, just after a video starts and once more a second later. With Super Resolution on it redraws in a way that never adds black bars. If a file still stays black, turning off **Preferences > Performance > Use the graphics card to decode video** is the fallback.
- **Flip H couldn't be combined with 90° or 270° (#83).** **Rotate and flip** is now a rotation (Normal, 90°, 180°, 270°) plus **Flip H** and **Flip V**, which switch on and off by themselves and mirror the picture as you see it after turning. All eight ways to turn and mirror a picture can be picked.
- **Leaving Shuffle put the queue back in order (#84).** Switching from **Shuffle** to **Stop** or **Loop** now keeps the shuffled order, and going back to Shuffle carries on with it. Only **In order** puts the queue back the way it was.
- **Floating controls in the wrong place on Wayland (#81).** On Wayland desktops Pylon runs through XWayland, and some window managers there (COSMIC, for one) place small floating windows themselves and ignore later moves. The top and bottom bars ended up stacked near the top of the window and didn't follow it when it was resized. Pylon now places them past the window manager on Wayland desktops, the way menus already work, and hides them while another app is active. On other Linux desktops Pylon checks where the bars really went and does the same if the window manager moved them.
- **Super Resolution still black in full screen (#42).** 1.6.5 stopped VLC from adding black bars of its own, but the picture still went black. The tests on this issue point to a simpler rule: RTX Super Resolution only shows a picture while the video covers the whole screen. So, with Super Resolution on:
  - In full screen, the library and settings panels now float over the video instead of shrinking it, so the video keeps the whole screen.
  - When an aspect ratio, crop or fixed zoom leaves black bars in full screen, Pylon sets Super Resolution aside and shows the picture with normal scaling, with a short message. It comes back when the picture fills the screen again. Switching takes a moment, because VLC only reads this setting when the player starts.
  - In a window nothing changes.

### Changed
- **Keep the controls visible** now makes the top and bottom bars part of the window, above and below the video, instead of separate windows held in place over it. They can't drift or lag behind when the window moves.

### Downloads
| | Download |
|---|---|
| Windows 10/11 (64-bit) | `Pylon-Setup-1.7.0.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.7.0-x86_64.AppImage` |
| macOS 14+ | `Pylon-1.7.0-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
New automated checks in `tests/check_rotate_shuffle_visual_trim.py` (30 tests) cover:
- **#82:** on Windows the video area shrinks by two pixels and comes back, twice, after the video output starts; other systems, the music page and Super Resolution (which redraws without letterboxing instead) are left alone.
- **#83:** Flip H with each rotation gives the right VLC value, all eight pictures can be made, every value reads back into the panel, and the panel keeps Flip H on while the rotation changes.
- **#84:** Shuffle to Stop or Loop and back keeps the shuffled order; In order restores it, with what's playing in its place.
- **#85:** VLC is started with the chosen visualization; a song restarts with it, a video waits for the next file; a visualization shows on the video page and the music page comes back when it's off.
- **#86:** the start and end of the sound are found from a WAV with silence at both ends; the cache keeps them (older caches are read again); playback jumps past the start only while still in it, waits for VLC to play, ends the song at the silence, and leaves short gaps, videos and A–B repeats alone.

Checked by hand with real VLC 3.0 on Linux (Xvfb):
- **#83:** snapshots of a test picture with a coloured corner confirm VLC's 90 turns clockwise and transpose swaps the top-right and bottom-left corners, so Flip H after 90° is transpose and after 270° antitranspose.
- **#85:** Spectrum, Scope, VU meter and Spectrometer all draw in Pylon's video page for an MP3. Goom isn't in Debian's VLC and 3D spectrum needs OpenGL, so neither showed there, which is what the "isn't available" message is for.
- **#86:** a song with 1.5 s of silence before a tone and 2 s after it started at the tone and ended where it stopped.
- **#82** needs the reporter's Windows graphics driver; the nudge itself is the same resize that opening the panel caused.

Also from the 1.6.6 work, `tests/check_overlays_panels_vsr.py` (18 tests) covers:
- **Floating controls:** XWayland bypasses the window manager and other platforms don't; `PYLON_OVERLAYS=bypass` or `managed` forces either. When the window manager keeps the bars somewhere else, Pylon switches and the bars land where they belong; bars that are where they belong leave things as they are; bypassing bars hide while another app is active.
- **Pinned bars** are part of the window at their full height and float again in full screen or when the setting is off.
- **Sliding panels:** halfway through, the slot is narrower but the panel keeps its width; toggling mid-slide turns around; the setting turns it off.
- **Super Resolution:** in full screen, panels float as native windows above the video, the video keeps its size and the bars stay clear of the panels; leaving full screen lays the panels out again; a 4:3 picture on a 16:9 screen sets Super Resolution aside (VLC is started without it) and 16:9 brings it back; a window leaves it alone.

Checked by hand on Linux (Xvfb, real VLC 3.0.20):
- **#81:** a small window manager that places windows itself and ignores later moves gave the same picture as the report (bottom bar just under the top bar, both off the window). With 1.7.0 both bars land exactly over the video, also after a resize, whether Pylon detects Wayland or notices the move itself. With Openbox, which honours moves, nothing changes.
- **#42:** in full screen with Super Resolution forced on, both panels float over the playing video and the bars sit between them. Super Resolution itself needs an NVIDIA RTX card, so it hasn't been tried with Super Resolution actually running.

All 42 test files (330 tests) pass on Linux under X11 (Xvfb) with real VLC 3.0. Under Qt's headless offscreen mode, `check_vsr_fit_pin_sliders.py` passes but Python crashes on exit; the same crash happens in a ten-line Qt script without Pylon (a widget moved between a floating window and a window with a native child), and not under X11.
