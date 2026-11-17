## Pylon 1.7.2

A small fix release for the volume: sound at the start of a file with the maximum volume above 100%, and two lower volume limits.

### Fixed
- **No sound when a file started above 100% (Windows, #82).** With the maximum volume at 150% or 200% and the volume above 100%, a film could start with no sound until the volume was dragged below 100%. VLC's Windows audio output adds the boost above 100% as extra gain, and a file that starts with it can stay silent. Pylon now starts each file at 100% at most and goes up to your volume half a second after it starts playing. The same happens when you switch audio tracks. The volume control shows your own volume the whole time.
- **The direct download links in the README** named the 1.7.0 files and stopped working when 1.7.1 came out. They name the current release now, and `packaging/sync_metadata.py` keeps them, and the file names in the user guide, up to date with the version.

### Changed
- **Maximum volume of 85% or 100% (#89).** Preferences > Playback > Maximum volume now offers 85% and 100% besides 125%, 150% and 200%, for when loud scenes are too loud. Lowering the limit brings the volume down to it. The default stays 125%.

### Downloads
| | Download |
|---|---|
| Windows 10/11 (64-bit) | `Pylon-Setup-1.7.2.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.7.2-x86_64.AppImage` |
| macOS 14+ | `Pylon-1.7.2-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
New automated checks in `tests/check_volume_start_limits.py` cover:
- **#82:** at 150% and 200% a new file starts at 100% and reaches the real volume once it has played for a moment, while the controls show the real volume; 100% or less is never changed; a volume dragged while the file opens wins over the held one; switching audio tracks holds and restores it too; Linux and macOS start at the real volume as before.
- **#89:** Preferences offers 85%, 100%, 125%, 150% and 200%; lowering the limit to 85% brings the volume down and caps it; the volume cone reaches 85% at its wide end and draws no 100% mark.
- **Download links:** the README names this version's files, `sync_metadata.py` rewrites older names, and every managed file is in sync.

All 51 test files pass on Linux under X11 (Xvfb) with real VLC 3.0, at 100% and 150% display scaling. The sound fix itself is for VLC's Windows audio output, so it needs a try on Windows with the volume above 100%.
