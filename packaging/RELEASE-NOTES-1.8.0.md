## Pylon 1.8.0

Media keys and your system's media controls, night mode, 2× while you hold, typing a time to jump to, subtitles downloaded inside Pylon, synced lyrics for songs and a volume to start at. Plus sound at the start of a file above 100% on Windows, two lower volume limits, playlists from other players that open properly, and fixes from a full code review.

### New
- **Media keys and system media controls.** The keyboard's play/pause, next, previous and stop keys work with Pylon on every system. On **Windows**, the media overlay that appears with the volume keys (and on the lock screen) shows what's playing, and its buttons, headset buttons and media keys control Pylon even while another app is in front. On **Linux**, Pylon appears in desktop media widgets and works with headset buttons and `playerctl` (MPRIS). On **macOS**, the media keys work while Pylon is in front. Preferences > Playback can turn this off.
- **Night mode** (Settings > Audio, or `Shift+N`). Loud scenes are turned down and quiet talk is brought up, for watching at night. Pylon reads the file's sound in the background first (a few seconds for a film), then turns the volume down just before a loud part arrives and brings it back up slowly afterwards. The volume control keeps showing your own volume. It works for files on your computer, not streams or discs. (VLC's own compressor can't be switched on from inside an app with VLC 3, so Pylon does the levelling itself.)
- **Hold for 2× speed.** Hold the left button on the video, or hold `Shift+Space`, to play at 2× until you let go; then the speed you had comes back. Holding isn't a click, so it doesn't pause.
- **Type a time to jump to.** Click the time next to the play controls, or press `Ctrl+G`, and type `1:02:10`, `62:10`, `130` (1:30), `+30`, `-10` or `50%`. Right-clicking the time switches to the time remaining.
- **Download subtitles inside Pylon (OpenSubtitles.com).** Find online > **Download in Pylon** in the Subtitles tab, or `Shift+D`, searches for the playing file and lists the results with the ones **made for this exact file** first and marked ✓, so you can pick the right one without trying them. The subtitle is saved next to the video as `<name>.<language>.srt` and used straight away. In **Add subtitles**, **Download…** does the same for one file, or fetches the best match for every video in a folder or the queue and pairs them as usual. OpenSubtitles.com needs a free API key: make an account at opensubtitles.com, create a key on your profile's **API consumers** page, and paste it in Preferences > Subtitles (or set `PYLON_OPENSUBTITLES_KEY`). Signing in there with your OpenSubtitles.com account raises the daily download limit.
- **Synced lyrics.** A song with a `.lrc` file of the same name shows its lyrics next to the cover. The line being sung stays in the middle; click a line to jump there, or scroll to read ahead. Lyrics without times are shown as plain text. Preferences > Playback can turn them off.
- **Volume when Pylon starts** (Preferences > Playback): the volume it had when it closed, as before, or a fixed 30%, 50%, 70%, 85% or 100% so a loud film never starts at full blast.

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
| Windows 10/11 (64-bit) | `Pylon-Setup-1.8.0.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.8.0-x86_64.AppImage` |
| macOS 14+ | `Pylon-1.8.0-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
New automated checks for 1.8.0:
- `tests/check_media_controls.py`: one key press reaching Pylon twice counts once; media keys become play/pause, next, previous and stop, and do nothing when nothing is open; the song or video shown; turning the setting off stops them; on Linux, `playerctl` sees Pylon's title, artist, status and position and can skip, pause and seek (on a private D-Bus session); on Windows, the media overlay is made for a real window, shows a song and a video, and closes.
- `tests/check_night_mode.py`: loudness measured every quarter second; loud parts turned down ahead of time and quiet talk brought up, silence left alone, coming back up gradually; the volume shown stays yours and returns when night mode is off; another file's loudness is ignored; the switch, `Shift+N` and the Audio tab agree; the sound is read for night mode even with the waveform off.
- `tests/check_hold_jump_start_volume.py`: holding the mouse still on the video plays at 2× and the release isn't a click, moving isn't holding; `Shift+Space` ends when the key (not an auto-repeat) is released or Pylon loses focus; the previous speed comes back; typed times (clock, digits, `+`/`-`, `%`, out of range, nonsense); the box opens from the time and `Ctrl+G`; the start volume, capped at the maximum.
- `tests/check_opensubtitles.py` (no internet, the API is faked): the request (API key header, sorted lower-case parameters, the file's hash, season and episode); exact matches first, other episodes dropped; downloading with and without an account (signing in once); messages for a wrong key, no downloads left, too many requests and no connection; the hash; saving next to the video or in Pylon's folder; the key never built in; the pick-one dialog, the folder download and the Preferences fields.
- `tests/check_lyrics.py`: `.lrc` times, several tags on a line, `[offset:]`, word timings and untimed lyrics; found next to the song in any letter case; the line being sung kept in the middle, a click jumps, the wheel scrolls then follows again; shown only for songs that have them, and turned off from Preferences.

From the 1.7.2 fixes, `tests/check_playlists_presets.py` covers:
- **Playlists:** .m3u8 with `file:///` entries, relative paths and links; .pls (in file number order) and .xspf with titles; an HLS stream, a missing file and an older text encoding; a playlist dropped on the queue lands in place, and one opened or queued with other files, or added to a saved playlist, brings its entries.
- **Presets:** a file from another folder with no preset starts with the default picture while your speed carries on; the next episode keeps what you set; going back to the first show applies its preset again.
- **Edge cases:** a stream's end records nothing, nothing is recorded with history off, Home counts progress like the Playlists tab, and nothing is marked playing after Close.

`tests/check_volume_start_limits.py` covers:
- **The hold for each file:** a file opened 0.2 s after the last one started stays at 100% until its own start; a file that fails, or Close, ends the hold; changing the audio device holds and restores.
- **#82:** at 150% and 200% a new file starts at 100% and reaches the real volume once it has played for a moment, while the controls show the real volume; 100% or less is never changed; a volume dragged while the file opens wins over the held one; switching audio tracks holds and restores it too; Linux and macOS start at the real volume as before.
- **#89:** Preferences offers 85%, 100%, 125%, 150% and 200%; lowering the limit to 85% brings the volume down and caps it; the volume cone reaches 85% at its wide end and draws no 100% mark.
- **Download links:** the README names this version's files, `sync_metadata.py` rewrites older names, and every managed file is in sync.

All 57 test files pass on Linux under X11 (Xvfb) with real VLC 3.0, at 100% and 150% display scaling. The sound fix itself is for VLC's Windows audio output, so it needs a try on Windows with the volume above 100%.
