## Pylon 1.7.2

A fix release: sound at the start of a file with the volume above 100%, two lower volume limits, playlists from other players that open properly, and fixes from a full code review.

### Fixed
- **No sound when a file started above 100% (Windows, #82).** With the maximum volume at 150% or 200% and the volume above 100%, a film could start with no sound until the volume was dragged below 100%. VLC's Windows audio output adds the boost above 100% as extra gain, and a file that starts with it can stay silent. Pylon now starts each file at 100% at most and goes up to your volume half a second after it starts playing. The same happens when you switch audio tracks. The volume control shows your own volume the whole time.
- **.pls and .xspf playlists** opened as a queue of lines of text that couldn't play. Pylon now reads them itself, with their titles.
- **Playlists saved by VLC, foobar2000 and other players**, whose entries are written as `file:///` addresses, couldn't play any of their items. They play now, and entries written relative to the playlist's folder are found too. Playlists in an older text encoding open as well.
- **A playlist dropped on the queue**, picked in the Open window with other files, added with "Add to queue" or added to one of your playlists became one item that couldn't play. It now brings its entries, in place.
- **Picture settings carried over to another show.** When the next file came from a folder with no preset, it kept the last show's aspect ratio, crop, zoom and colours. A file from another folder now starts from the defaults (its own preset still applies, and settings you change carry on to the next episode in the same folder). Colours from a preset are also switched off properly when the next file has none.
- **The volume above 100% after skipping quickly.** Pressing Next within half a second of a file starting, changing the audio device, or a file that failed to open could still start the next file silent or keep the volume capped. Each file's audio now waits for its own start.
- **The subtitle look** in the settings panel showed the default style until something played, so changing it then could replace your saved look.
- **Streams** no longer get a resume point or a "watched" mark when they end, and nothing is recorded when "Remember recent files and where I stopped" is off.
- **Opening a file while Pylon is already open** waits until the open Pylon has the whole file list, so a file double-clicked while the computer is busy isn't lost.
- **Linux:** a read-only or full home folder no longer stops Pylon starting (adding it to the applications menu just fails), "Show in folder" works without `xdg-open`, and a window closing at the wrong moment can't end Pylon through an X11 error.
- **Smaller fixes:** Home and the Playlists tab count a playlist's progress the same way; songs added to the queue from Music show "Title · Artist", like songs you play; picture in picture opened from full screen comes back to a maximized window if it was one; after Close, no queue item is marked as playing; a jump made just after a paused file reopens isn't undone.
- **Under the hood:** the waveform reads its sound once instead of twice, Pylon's own folder is worked out in one place, and unused code is removed.
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
New automated checks in `tests/check_playlists_presets.py` cover:
- **Playlists:** .m3u8 with `file:///` entries, relative paths and links; .pls (in file number order) and .xspf with titles; an HLS stream, a missing file and an older text encoding; a playlist dropped on the queue lands in place, and one opened or queued with other files, or added to a saved playlist, brings its entries.
- **Presets:** a file from another folder with no preset starts with the default picture while your speed carries on; the next episode keeps what you set; going back to the first show applies its preset again.
- **Edge cases:** a stream's end records nothing, nothing is recorded with history off, Home counts progress like the Playlists tab, and nothing is marked playing after Close.

`tests/check_volume_start_limits.py` covers:
- **The hold for each file:** a file opened 0.2 s after the last one started stays at 100% until its own start; a file that fails, or Close, ends the hold; changing the audio device holds and restores.
- **#82:** at 150% and 200% a new file starts at 100% and reaches the real volume once it has played for a moment, while the controls show the real volume; 100% or less is never changed; a volume dragged while the file opens wins over the held one; switching audio tracks holds and restores it too; Linux and macOS start at the real volume as before.
- **#89:** Preferences offers 85%, 100%, 125%, 150% and 200%; lowering the limit to 85% brings the volume down and caps it; the volume cone reaches 85% at its wide end and draws no 100% mark.
- **Download links:** the README names this version's files, `sync_metadata.py` rewrites older names, and every managed file is in sync.

All 52 test files pass on Linux under X11 (Xvfb) with real VLC 3.0, at 100% and 150% display scaling. The sound fix itself is for VLC's Windows audio output, so it needs a try on Windows with the volume above 100%.
