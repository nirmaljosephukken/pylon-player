## Pylon 1.7.1

A fix and cleanup release: Super Resolution works with films that aren't the shape of the screen, and a wide tidy-up from a full code review makes Pylon safer with your data and smoother to use.

### Fixed
- **Super Resolution with films that have their own black bars (#42).** In 1.7.0 Super Resolution was set aside whenever the picture couldn't fill the screen, so a 2.39:1 film or a 4:3 show never got it. Now a video shown the way the file has it keeps Super Resolution in full screen, with the black bars at the top and bottom or the sides, the same way VLC does on its own. If you pick an aspect ratio, crop, zoom, rotation or flip that leaves bars, Super Resolution is still set aside with a short message, and it comes back when the picture fills the screen again.
- **Black picture with Super Resolution in a window (#82).** In a normal window Super Resolution could show the subtitles over a black picture. Pylon now sets it aside, without a message, while the window would make the video bigger than it really is, and turns it back on in full screen. A video shown smaller than its own size is left alone, so opening a panel or resizing the window doesn't restart VLC. For a low-resolution video, VLC restarts once when you go into full screen and once when you leave it, and carries on from the same point.
- **Pylon closed at the end of a song with the 3D spectrum visualization (Windows).** VLC's 3D spectrum crashes on Windows as soon as the song it shows is stopped or changed, which took Pylon down with it. It's no longer offered on Windows, and if it was picked, the visualization is set to Off. The other five visualizations are unchanged.
- **A damaged `data.json` is no longer wiped.** Pylon keeps the bad file as `data.json.corrupt-<time>` and starts from `data.json.bak`, which it now writes on every successful save. Values of the wrong type (from a hand edit, for example) fall back to the defaults. Resume positions and play counts keep the latest 2,000.
- **Clearing a saved subtitle pairing** now really removes it.
- **Online channel lists** open without freezing the window ("Opening…" shows while they load). If you open a second link while the first is still loading, the first one's late answer is ignored.
- **Every key shown in a menu or tooltip** follows your own shortcuts. Before, only one menu entry changed after a key was remapped.
- **Removing a library folder** works however the folder was spelled when it was added (through a link, or with different letter case on Windows), and its pin goes with it.
- **Exporting a playlist or channel list** to a folder that can't be written shows a message instead of an error, and a successful export shows a toast.
- **Two Pylons starting at the same moment** can no longer take each other's single-instance socket.

### Changed
- **Updates are checked.** The downloaded installer's SHA-256 must match the `SHA256SUMS.txt` published with each release, and pre-releases are never offered.
- **Faster start:** VLC starts once at launch instead of twice.
- **Hardware decoding** applies as soon as you change it, like Super Resolution: VLC restarts and carries on from the same point.
- **The Library tab sorts like the other tabs**, with a drop-down and a direction arrow: by name, date modified or watched, either way round. The sort you saved in 1.7.0 carries over.
- **Snapshots** go to your Pictures folder (the XDG one on Linux), in `Pylon`, named `Pylon <date time>.png`, and the message names the real folder.
- **"Show in Explorer"** reads "Show in Finder" on macOS and "Show in folder" on Linux.
- **"Open with"** lists Pylon for playlists (`.m3u`, `.m3u8`, `.pls`, `.xspf`) on every system. The made-up `.alac` type is gone.
- **A setting changed in Preferences** shows in the sidebar at once.
- **Logs** (`error.log`, `vlc.log`, `startup.log`) that grow too big are kept as `<name>.previous` instead of being deleted, and crashes are written to both `error.log` and `startup.log`.
- **Smoother in the background:** thumbnails, waveforms and the music scan share one background worker, cancelling it no longer makes the window wait, and Chromecast devices found by VLC are handled on the window's thread.
- **Under the hood:** one source for the version, file types and other shared rules, written into every installer and desktop file by `packaging/sync_metadata.py`, and duplicated or unused code removed. Older release notes moved to `packaging/release-notes/`.

### Downloads
| | Download |
|---|---|
| Windows 10/11 (64-bit) | `Pylon-Setup-1.7.1.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.7.1-x86_64.AppImage` |
| macOS 14+ | `Pylon-1.7.1-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
New automated checks in `tests/check_overlays_panels_vsr.py` cover:
- **#42:** a 2.39:1 film shown as it is keeps Super Resolution in full screen, with VLC given the whole screen to add the bars itself; an aspect ratio, crop, fixed zoom or flip that leaves bars still sets it aside, and the "back" message only follows a "paused" one.
- **3D spectrum:** not offered on Windows (offered on Linux and macOS), and a saved choice that isn't offered becomes Off.
- **#82:** in a window a video smaller than the page sets Super Resolution aside quietly and it comes back in full screen; a video bigger than the page leaves it alone, and coming back to a smaller size doesn't restart VLC; the "upscaled" test matches VLC's own.

New checks from the code review: `check_store_safety`, `check_pyflakes`, `check_single_sources`, `check_metadata_sync`, `check_updater`, `check_threading`, `check_state_flow` and `check_structure`.

All 50 test files pass on Linux under X11 (Xvfb) with real VLC 3.0, at 100% and 150% display scaling. Super Resolution itself needs an NVIDIA RTX card, so it hasn't been tried with Super Resolution actually running.
