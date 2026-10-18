## Pylon 1.3.7

### Preferences and library
- Save the colour picker's custom palette across sessions for accent, tint and subtitle colours (#33).
- Scroll Preferences pages to keep controls and long data paths accessible in smaller windows (#31).
- Choose the startup tab for each sidebar, including Last used (#30).
- Add a folder directly to the library from its context menu, with duplicate-path checks (#32).
- Save library folder sorting and apply name/date-modified ordering to root folders and Home cards (#31).
- Sort music artists and albums by song count or newest member file modification time. Individual songs support file modification date (#31).

### Startup maintenance
- macOS: detect Apple Silicon hardware even when launched through Rosetta, and explicitly select the Python architecture matching VLC (#13). This addresses the reported architecture mismatch; confirmation on an affected Mac is still needed.
- Add early startup logging and native-fault traceback reporting before Qt loads.
- Linux: fix the AppImage crashing at startup with a segmentation fault on newer distributions such as Fedora 44 (#28). Pylon bundled a keyboard library (libxkbcommon-x11) that didn't match the system's newer libxkbcommon, which crashed Qt while connecting to the display. Pylon now uses the system's copy and keeps its own only as a matched fallback. Reproduced and verified fixed on Fedora 44 with VLC 3.0.24, and checked on Ubuntu 24.04.
- Include a separate Linux diagnostic helper to capture extraction, Qt plugin output and exit status.

### Downloads
- Windows 10/11, 64-bit: Pylon-Setup-1.3.7.exe
- Linux x86-64: Pylon-1.3.7-x86_64.AppImage
- macOS 14+, experimental: Pylon-1.3.7-macOS.zip

Install VLC separately. SHA256SUMS.txt covers the packages and diagnostic helper. SOURCE-MANIFEST.json records packaged source hashes.

For Linux diagnostics, place diagnose-startup.sh beside the AppImage and run:
```sh
bash diagnose-startup.sh ./Pylon-1.3.7-x86_64.AppImage
```
Close Pylon if it opens, then review the generated logs for private paths before sharing them.

### Validation and limitations
Automated checks cover preferences, palette persistence, sidebar startup choices, library/music sorting, mouse controls, minimum-window layouts, startup logging, simulated Mac launcher selection and diagnostic script behaviour. Package checks verify source contents, metadata, archive integrity, executable modes, symlinks and retained runtimes.

Windows startup with VLC was smoke-tested. The Linux AppImage was run on Fedora 44 and Ubuntu 24.04 (virtual display). Native macOS execution and a full installer/update cycle have not been tested. DVD ISO navigation and broader feature requests are not included.
