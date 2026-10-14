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

## macOS: `Pylon-<version>-macOS.zip` (experimental)

1. Pythons: python-build-standalone `aarch64-apple-darwin` and `x86_64-apple-darwin` 3.14.8 become
   `Pylon.app/Contents/Resources/python-arm64` and `python-x86_64`.
2. Unzip the `macosx_14_0_universal2` wheels once into `Contents/Resources/site-packages` (shared by
   both Pythons via `PYTHONPATH`), trim as above. Don't strip: arm64 code must keep its signature.
3. Pylon's files go in `Contents/Resources/pylon/`; add `macos/Info.plist`, `macos/pylon.icns`, and
   `macos/Pylon-launcher.sh` as `Contents/MacOS/Pylon` (executable). The launcher picks the Python
   matching the Mac, or the Intel one under Rosetta when the installed VLC is Intel-only.
4. `zip -ry Pylon-<version>-macOS.zip Pylon.app` (keeps the framework symlinks).

Uses `/Applications/VLC.app`. The app isn't signed or notarized by Apple.
