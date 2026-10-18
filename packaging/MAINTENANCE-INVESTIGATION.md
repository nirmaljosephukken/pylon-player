# Maintenance work after 1.3.6

## Linux startup, #28

The xz/runtime mismatch was corrected in 1.3.6, but the reporter now reports a
segmentation fault on Fedora 44 KDE and ambiguous behaviour on Mint 22.3.
The native crash is **not diagnosed or confirmed fixed**. No Linux runtime is
available on this Windows host (WSL is not installed).

The bundled AppRun and helper libraries were inspected. No speculative changes
to graphics drivers, VLC plugins or bundled runtimes have been made. An early
standard-library-only startup logger now runs before Qt imports. It records
startup phases and enables Python's native-fault traceback handler, which can
help distinguish a Qt import failure from main-window/VLC startup or shutdown.
This cannot catch faults in the AppImage runtime before Python starts.

`packaging/linux/diagnose-startup.sh` can also test the existing 1.3.6 AppImage:

```sh
bash diagnose-startup.sh /path/to/Pylon-1.3.6-x86_64.AppImage
```

The helper extracts into a fresh temporary folder and launches AppRun directly,
bypassing FUSE, with Qt plugin logging and Python fault reporting enabled. It
does not replace the installed app, but launching Pylon uses its normal settings.
It saves the package checksum, machine/session details, extraction output,
console log and exit status. Logs should be checked for private paths before
sharing. Later builds also save `startup.log` in the Pylon data folder's `logs/`.

Reporter information still needed: exact filename/checksum; CPU architecture;
VLC version and whether installed natively or via Flatpak/Snap; whether Fedora
fails before a window appears; and whether Mint exits cleanly or segfaults on
close. Compare normal AppImage startup with extracted AppRun and capture logs.

## Mac architecture, #13

The reporter's dlopen message says ARM VLC is being loaded into an Intel
process. The previous launcher trusts `uname -m`, which can return x86_64 for a
process running under Rosetta. It also silently falls back to Intel Python if
the native interpreter is missing.

The launcher now detects Apple Silicon hardware using `hw.optional.arm64`,
selects an interpreter matching the available VLC library and explicitly invokes
`arch -arm64` or `arch -x86_64`. A missing selected interpreter produces an
explicit error instead of silent cross-architecture fallback. Existing Intel-VLC
support on Apple Silicon is retained and requires Rosetta as before.

Five launcher scenarios execute under Bash with simulated macOS system tools:
Rosetta + ARM VLC, Intel VLC on Apple Silicon, universal VLC, Intel Mac and a
missing selected interpreter. Both packaged Python binaries were inspected and
have the advertised architecture. These checks are not a real Mac launch. A
reporter still needs to test an updated Mac package.

## Focused UI fixes, #30–#33

- Persist the colour picker's custom palette across sessions for accent, tint
  and subtitle dialogs. The selected accent/theme remains independently saved.
- Preferences pages scroll vertically so controls and long data paths remain
  accessible at small window sizes.
- Separate startup-tab choices for each sidebar, including Last used. Normal
  sidebar reopening retains the current tab; explicit tab-opening actions win.
- Add the selected folder as a library root through its context menu, without
  pinning it. Resolve equivalent paths to avoid duplicate roots.
- Apply name/date-modified sorting at the library root while retaining the
  separate pinned order; persist the chosen folder sort mode. Home folder cards
  follow the same ordering.
- Add Most items for music artists/albums using song counts. Disable that choice
  when viewing individual songs. Music date sorting explicitly means file
  modification time, or the newest member file for grouped views.

Playlist completion sorting, music watched-state sorting, playlist/stream
creation-date migration and DVD ISO navigation remain out of scope.

Prepared as local 1.3.7 packages in the sibling Pylon-1.3.7/Downloads folder.
Published packages and GitHub issue states are unchanged.

## Verification performed

- Five Mac launcher scenarios under Bash using simulated OS commands; four
  existing Mac dynamic-loader tests.
- Five preference/library tests, including a fresh settings reload, palette
  cancellation, startup tabs, same-session sidebar reopening, explicit tab
  actions, duplicate roots, root/home sorting and meaningful music sorting.
- Existing home/privacy checks (five), music/playlist checks (four), mouse
  controls (six), and all four minimum-window panel combinations.
- Early log and traceback checks in a separate Python process; diagnostic
  helper tests with simulated success and exit 139. No actual Linux segfault
  was reproduced on this Windows host.
- A Windows smoke test with the actual installed VLC engine and isolated
  settings: main window opened and shutdown completed cleanly.
- Small-window Privacy/Interface renders inspected. Both remain usable, and
  the full data path is accessible.
- Synthetic Mac/Linux baseline repacks include newly added application modules
  and retain existing executable permissions and symlink metadata.

## Reporter follow-up drafts

For #28, before calling this resolved:

> Thanks for testing both distributions. Could you confirm the exact AppImage
> filename and checksum, whether Fedora crashes before showing a window, and
> whether Mint's segmentation fault happens during use or only when closing?
> Please also share your CPU architecture, VLC version and whether VLC is
> installed through the distribution packages or Flatpak/Snap. We have a startup
> diagnostic helper that tests the extracted app without FUSE and records Qt
> plugin output and the exit status. That should help locate the failure; the
> compression correction alone has not resolved this report.

For #13, once an updated test Mac package is available:

> Your error shows ARM VLC being loaded into an Intel Python process. We found a
> launcher path that can select Intel when Pylon starts under Rosetta and have
> changed it to detect Apple Silicon hardware and explicitly select the matching
> interpreter. The selection tests pass, but we still need a real Mac test.
> Please test the updated package and confirm whether it starts and plays a local
> video. If it still fails, please share the full error and startup.log.

These are drafts only; no comments have been posted.
