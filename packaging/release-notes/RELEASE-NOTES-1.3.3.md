## Pylon 1.3.3 (beta)

[Download page](https://nirmaljosephukken.github.io/pylon-player/)

### Changes
- Preferences stays open when changing themes and accent colours. Colour choices have consistent buttons and rounded swatches. The play button hover outline uses antialiased drawing (#14).
- Right-click a library folder to save its current playable files as a playlist. This is an independent snapshot, in the folder's normal sorted order. Added playlist and stream search, and music search labels matching the current view (#15).
- Click a seek preview to seek to its recorded time. Its timestamp now follows the cached image. Previews remain sampled, and VLC seeking is not guaranteed frame-perfect. Old preview caches regenerate once to record timestamps (#16).
- Playback bars stay within the player area instead of covering side panels. Narrow player areas retain essential controls; widen the window or close a side panel to restore additional buttons. Keyboard shortcuts remain available. With both side panels open, the window now has a minimum width of 900 pixels to prevent their content from being clipped; closing the panels restores the 640-pixel minimum (#17).

Thanks to @UserSpringRoll for the reports and screenshots.

### Downloads
- Windows 10/11 (64-bit): Pylon-Setup-1.3.3.exe
- Linux x86-64: Pylon-1.3.3-x86_64.AppImage
- macOS 14+ (experimental): Pylon-1.3.3-macOS.zip

VLC must be installed separately. An automatic VLC installer is not included in this release. Library and settings are kept when upgrading. SHA-256 checksums are in SHA256SUMS.txt.

### Known issue
The macOS VLC startup failure in #13 remains open pending the reporter's system and error details. This release does not claim to fix it. The Mac build remains experimental and untested on a real Mac.

### Validation
Windows Qt checks passed for live theme changes, search, playlists, preview clicks and panel layouts at 640, 900, 1200 and 1600 pixel widths. Real Windows libVLC checks passed for thumbnail capture, timestamp cache reload and seeking. Linux and Mac package contents are checked; runtime testing on those systems is outstanding.

Pylon is MIT licensed. Design inspiration: Juxtopposed, credited in the app and repository. Not affiliated with VideoLAN.
