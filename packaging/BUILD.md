# How the Pylon downloads are built

Every download contains the same three things: Pylon's code (`main.py`, `app/`), a private copy of
**Python 3.14.8**, and the Python packages **PySide6-Essentials 6.12.0**, **Shiboken6 6.12.0** and
**python-vlc 3.0.21203**, unpacked unchanged into that Python's `site-packages`. VLC is never included.

To keep downloads small, Qt modules Pylon doesn't use are deleted (whole files only; nothing is modified
or recompiled). Pylon imports only `QtCore`, `QtGui`, `QtWidgets`, `QtSvg` and `QtNetwork`. The Qt
libraries kept are exactly those these modules and the kept plugins load, found by reading each
binary's import table (PE on Windows, ELF `DT_NEEDED` on Linux, Mach-O load commands on macOS).

Licence texts go in a `licenses/` folder in each download, next to `LICENSE` and
`THIRD_PARTY_NOTICES.md`.

## Windows: `Pylon-Setup-<version>.exe`

1. Python: the official NuGet package `python` 3.14.8 (the `tools/` folder) becomes `Python/`.
2. Unzip the three `win_amd64` / `py3-none-any` wheels into `Python/Lib/site-packages`.
3. Delete unused Qt DLLs, `.pyd` modules, tools (`designer.exe`, …), `qml/`, `resources/`, unused
   plugins, and Python's `test`, `tkinter`, `idlelib`, `ensurepip`, `pip`.
4. Stage: `Pylon/` = `Python/`, `app/`, `main.py`, `Pylon.exe` (from `launcher/`), `pylon.ico`,
   `LICENSE`, `THIRD_PARTY_NOTICES.md`, `diag.py`, `diag.bat`, `licenses/`.
5. `makensis -DSRC=path/to/Pylon windows/pylon.nsi` (NSIS 3). Per-user install, no admin rights.

## Linux: `Pylon-<version>-x86_64.AppImage`

1. Python: python-build-standalone `cpython-3.14.8+20261009-x86_64-unknown-linux-gnu-install_only`
   becomes `Pylon.AppDir/usr/python`.
2. Unzip the `manylinux_2_34_x86_64` wheels into `usr/python/lib/python3.14/site-packages`, trim as
   above, strip debug symbols.
3. Copy the X11 helper libraries Qt's xcb plugin needs but some distributions lack
   (`libxcb-cursor0`, `-icccm4`, `-image0`, `-keysyms1`, `-render-util0`, `-util1`,
   `libxkbcommon-x11-0`) into `usr/lib`, with their copyright files.
4. Pylon's files go in `usr/share/pylon/`; add `linux/AppRun`, `linux/pylon.desktop`, `pylon.png`
   and the AppStream file in `usr/share/metainfo/`.
5. `ARCH=x86_64 appimagetool Pylon.AppDir Pylon-<version>-x86_64.AppImage`

Uses the system's `libvlc.so.5` (install the `vlc` package).

## macOS: `Pylon-<version>-macOS.zip`

1. Pythons: python-build-standalone `aarch64-apple-darwin` and `x86_64-apple-darwin` 3.14.8 become
   `Pylon.app/Contents/Resources/python-arm64` and `python-x86_64`.
2. Unzip the `macosx_14_0_universal2` wheels once into `Contents/Resources/site-packages` (shared by
   both Pythons via `PYTHONPATH`), trim as above. Don't strip: arm64 code must keep its signature.
3. Pylon's files go in `Contents/Resources/pylon/`; add `macos/Info.plist`, `macos/pylon.icns`, and
   `macos/Pylon-launcher.sh` as `Contents/MacOS/Pylon` (executable). The launcher picks the Python
   matching the Mac, or the Intel one under Rosetta when the installed VLC is Intel-only.
4. `zip -ry Pylon-<version>-macOS.zip Pylon.app` (keeps the framework symlinks).

Uses `/Applications/VLC.app`. The app isn't signed or notarized by Apple.

## Repacking the 1.3.3 release on Windows

`repack_release.py` preserves the bundled runtime from the local 1.3.2 release
and replaces the application with the current repository source. It checks the
baseline files against that release's SHA256SUMS.txt before use. This is a
maintenance repack, not a fresh dependency build.

Build tools used: Zig 0.15.2 (PyPI), NSIS 3.12 (conda-forge), and
squashfs-tools-ng 1.3.2 (the upstream Windows binary package). Keep these under
`build/tools` (ignored by Git). All outputs go to the sibling
`Pylon-1.3.3/Downloads` folder.

- macOS: `python packaging/repack_release.py macos`. ZIP Unix mode bits and
  symlink entries are preserved; both bundled Python architectures and Qt
  binaries are retained unchanged. No signing or notarization is performed.
- Linux: retain the first 944632 bytes of the 1.3.2 AppImage as
  `build/linux-runtime`; the following SquashFS becomes `build/linux-old.sqfs`.
  Export it with `sqfs2tar` into `build/linux-old.tar`, using binary-safe
  subprocess redirection. Run `python packaging/repack_release.py linux`.
  The script patches a tar archive and runs `tar2sqfs`, preserving file modes
  and symlink targets rather than extracting Linux files onto NTFS.
  Use **zstd** compression. The bundled runtime supports zlib/zstd, not xz;
  xz repacks fail before Pylon starts. The script checks the SquashFS compressor
  before writing an AppImage. Run `python tests/check_appimage_compression.py`.
- Windows: build `Pylon.exe` using `launcher/build.md`, then run
  `python packaging/repack_release.py windows`. This stages Python and licences
  from the installed `Pylon-1.1/Pylon` copy, plus current repository files.
  Compile `packaging/windows/pylon.nsi` with NSIS and define SRC as the absolute
  `build/windows/Pylon` path. The compiler writes the installer next to the NSI
  script; move it to Downloads after compilation succeeds.

No VLC libraries are bundled. Check the packaged application files against the
repository, Windows PE version resources, macOS plist, Linux AppStream XML,
archive integrity, executable modes and symlinks. Generate SHA256SUMS.txt only
after all packages are final. SOURCE-MANIFEST.json records the exact source and
launcher hashes used. Windows staging was smoke-tested; Linux and macOS runtime
testing remains outstanding. See RELEASE-NOTES-1.3.3.md for the known Mac issue.


### 1.3.4 maintenance release

The repack script now reads APP_VERSION from app/__init__.py and names the output
folder and packages accordingly. Version 1.3.4 reuses the same verified 1.3.2
runtime baseline as 1.3.3; it replaces Pylon application files and platform
version metadata. Rebuild the Windows launcher before staging. The Windows
installer excludes generated __pycache__ directories and .pyc files.

Regression checks: `python tests/check_music_playlists.py` and
`python tests/check_minimum_layout.py`. These use temporary settings and exercise
Qt; run them in a desktop session (or with an available headless Qt plugin).
See RELEASE-NOTES-1.3.4.md for scope and known platform limitations.
