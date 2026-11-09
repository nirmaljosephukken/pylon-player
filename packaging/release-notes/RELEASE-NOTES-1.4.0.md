## Pylon 1.4.0

### Fixed
- **Linux crash on Fedora and other PipeWire systems.** Pylon crashed on startup with a segmentation fault on Fedora KDE. The crash log showed the cause: VLC's PipeWire audio add-on can crash when the volume is set before anything has played, which Pylon does as it starts. Pylon now uses VLC's PulseAudio output on Linux, which PipeWire also serves, and holds early volume changes until the audio output is ready. To use a different output, set `PYLON_VLC_ARGS`, for example `PYLON_VLC_ARGS=--aout=pipewire` (#28).
- **Subtitle timeline label.** The offset shown above the white playhead line in the subtitle timeline is no longer cut off at the top. The Windows installer for 1.3.10 already had this fix. The Linux and macOS downloads of 1.3.10 didn't, and they didn't match the 1.3.10 checksum file either. All three 1.4.0 downloads are built together and match `SHA256SUMS.txt`.
- **Broken streams don't skip ahead.** When a stream couldn't play, Pylon jumped to the next item in the queue, even with "play the next file" turned off, and the queue list scrolled back to the top. A stream that fails now stays selected so you can pick another one. A file that fails in a queue still moves on to the next file (#50).
- **Streams sort the right way round.** "Newest first" and "Oldest first" were reversed in the Streams list (#44).
- **The queue keeps its place.** The queue list no longer jumps back to the top when it updates. It only scrolls to show the playing item when a different one starts.

### New
- **Queue mode button.** The shuffle button above the queue now switches between four modes, as suggested in #48: **Stop** (grey, stops when the item ends), **Shuffle**, **In order** and **Loop** (plays the item again). The active mode shows in the accent colour, the same choice is in the settings panel under Playback, and Preferences > Playback sets the mode Pylon starts in. It starts in In order, so nothing changes unless you pick another mode. Repeating the whole queue is still there, as "Start the queue again when it reaches the end" in the settings panel, and it works with Shuffle too (#48).
- **Search the queue.** Long queues (more than 8 items) get a search box, handy for big channel lists (#44).
- **Maximum volume.** Preferences > Playback can raise the maximum volume to 150% or 200%, like VLC, for quiet audio or laptop speakers. It stays at 125% unless you change it (#47).
- **Preferences shortcut.** Ctrl+, opens Preferences. Like every shortcut, it can be changed with F1 (#49).

Thanks to @butter-fly04 for the crash log that pinned down #28, and to @UserSpringRoll and @Darkdevworker for the reports and suggestions.

### Downloads
| | Download |
|---|---|
| Windows 10/11 (64-bit) | `Pylon-Setup-1.4.0.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.4.0-x86_64.AppImage` |
| macOS 14+ (experimental) | `Pylon-1.4.0-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
Tested on Fedora 44 with a PipeWire sound server, the setup in #28. The 1.3.10 AppImage crashed exactly as reported. The fixed build started 8 times out of 8 and played a sound file 3 times out of 3, with VLC using PulseAudio on PipeWire. Automated checks cover the audio output choice, the delayed volume changes on Linux, volume still applying straight away on Windows and macOS, broken streams staying put, the queue keeping its place, queue search, the stream sort order, the Preferences shortcut, the maximum volume, and each queue mode (the button's order, icon and colour, stopping, looping, shuffling and back, new queues in Shuffle, repeating the whole queue, and the Preferences starting mode). All 21 test files pass. The queue mode button and settings were also checked on screen. The macOS package was checked for contents and version, but hasn't been run on a real Mac.
