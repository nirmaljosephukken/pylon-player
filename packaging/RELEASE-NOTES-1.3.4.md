## Pylon 1.3.4 (beta)

[Download Pylon](https://nirmaljosephukken.github.io/pylon-player/)

### Improved
- **Choose a playlist destination.** Saving a library folder or the current queue now lets you create a new playlist or add to an existing one. Appending skips files already present. Entering an existing playlist name no longer silently replaces its contents (#18).
- **Better collaboration artist browsing.** Artist browsing uses track credits separately from album ownership. Repeated artist names and letter-case variations consolidate, and collaboration tracks appear under the participating artists when the tags provide enough evidence. Album grouping stays intact, and opening an album from an artist view shows that artist's tracks (#19).
- **Conservative name parsing.** Explicit semicolon and feat./ft./featuring credits are separated. Commas and ampersands are separated only when names are independently present in the library or a name repeats within a credit. Ambiguous credits remain together rather than risking splitting a band name. No audio-file tags are changed.

The compact music layout is retained. Large album cards and circular artist images are not part of this release.

Thanks to @UserSpringRoll for the suggestions and examples.

### Downloads
- Windows 10/11 (64-bit): Pylon-Setup-1.3.4.exe
- Linux x86-64: Pylon-1.3.4-x86_64.AppImage
- macOS 14+ (experimental): Pylon-1.3.4-macOS.zip

VLC must be installed separately. Your library and settings are preserved when upgrading. SHA256SUMS.txt contains the package checksums.

### Known issue
The macOS VLC startup problem in #13 remains open pending the reporter's system and error details. This release does not claim to fix it.

### Validation
Regression checks cover playlist destinations, append deduplication, cancellation, existing-name protection, artist membership, album stability and artist-specific browsing. Linux and macOS archive contents, metadata, runtime files, permissions and symlinks are checked; runtime testing on those systems remains outstanding.

Free and open source. Inspired by Juxtopposed's VLC redesign. Not affiliated with VideoLAN.
