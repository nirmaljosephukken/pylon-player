## Pylon 1.3.6 (beta)

### Mouse controls
- Configure left click, left double-click, middle click and standard Back/Forward buttons in Preferences > Controls (#25).
- Available actions: play/pause, fullscreen, mute, next/previous in queue and jump back/forward 10 seconds. Bindings apply over the video; scroll and right-click retain volume and menu controls.
- Disable **Left double-click** for immediate single-click playback (#27). When a double-click action is enabled, Pylon waits for the system double-click interval to distinguish the gestures.
- Fixed an unintended play/pause action after the final release of a double-click.
- Additional buttons work when the mouse driver exposes standard mouse-button events. Proprietary buttons and vendor macros are not guaranteed.

### Fixes
- Fullscreen cursor hiding is now limited to the video surface, preventing it from hiding the cursor in Preferences and other dialogs (#26).
- Linux AppImage now uses zstd compression supported by its bundled runtime, fixing the reported xz compression startup failure (#28). Packaging now rejects unsupported SquashFS compression.

Interactive DVD ISO menus (#29) are not included and require separate implementation and testing.

### Downloads
- Windows 10/11 (64-bit): Pylon-Setup-1.3.6.exe
- Linux x86-64: Pylon-1.3.6-x86_64.AppImage
- macOS 14+ (experimental): Pylon-1.3.6-macOS.zip

VLC must be installed separately. SHA256SUMS.txt contains package checksums. SOURCE-MANIFEST.json records the packaged application source hashes.

### Validation
Automated checks cover mouse event sequences including fullscreen transitions, preference persistence, dialog cursor isolation, existing privacy/library/playlist/layout/Mac loader regressions and SquashFS compression compatibility. Package checks verify application source, version metadata, archive integrity, runtime preservation, executable permissions and symlinks.

Linux and macOS application execution, physical extra-button mice, and a complete installer/auto-update cycle have not been tested for this build. These checks do not guarantee that every system is unaffected.
