# Third-party notices

Pylon's own code is under the MIT licence (see `LICENSE`).

**VLC is never included.** You install VLC yourself from videolan.org (Windows,
macOS) or your package manager (Linux), and Pylon uses it from there.

**Source-code downloads** (from GitHub) include nothing else: `setup.bat` installs
the Python packages from PyPI.

**The Windows installer, Linux AppImage and macOS app** include a private copy of
Python and of the Python packages below, unchanged, as separate files. Their
licence texts are in the `licenses` folder inside each download.

| Component | Used for | Licence | Source |
| --- | --- | --- | --- |
| libVLC (VLC media player 3.0) | All playback, decoding and streaming | LGPL 2.1 or later (some VLC plugins are GPL) | https://www.videolan.org/vlc/ · https://code.videolan.org/videolan/vlc |
| python-vlc | Python bindings for libVLC | LGPL 2.1 or later | https://github.com/oaubert/python-vlc |
| Qt for Python (PySide6-Essentials, Shiboken6) | The user interface | LGPL v3 (or commercial) | https://www.qt.io/qt-for-python · https://code.qt.io/cgit/pyside/pyside-setup.git |
| Python | Runs Pylon | PSF License | https://www.python.org |

### Versions included in Pylon 1.1.0 downloads, and where to get their source

* Python 3.14.8 (Windows: the python.org build; Linux and macOS: python-build-standalone, https://github.com/astral-sh/python-build-standalone): https://www.python.org/downloads/source/
* PySide6-Essentials 6.12.0 and Shiboken6 6.12.0 (Qt for Python): https://download.qt.io/official_releases/QtForPython/pyside6/
  and the Qt 6.12.0 sources they are built from: https://download.qt.io/official_releases/qt/6.12/
* python-vlc 3.0.21203: https://pypi.org/project/python-vlc/3.0.21203/#files
* Linux AppImage only: xcb-util, xcb-util-cursor, xcb-util-image, xcb-util-keysyms,
  xcb-util-renderutil, xcb-util-wm and libxkbcommon-x11 (MIT/X11-style licences),
  copied unchanged from Ubuntu 24.04: https://xcb.freedesktop.org/ and https://xkbcommon.org/

Qt and python-vlc are used as separate, replaceable libraries: you can swap the
files in the bundled `Python` folder for your own builds of the same libraries.
On request we will also provide a copy of the corresponding source for the
versions shipped, for at least three years from each release.

If you redistribute Pylon bundled together with any of these (for example a
single-file build that includes Python, Qt or VLC), you must follow their
licences: ship their licence texts, keep them replaceable as separate
libraries, and point to their source code.

## Design credit

Pylon's interface adapts ideas from the VLC redesign concept by Juxtopposed
(https://www.youtube.com/@juxtopposed), published free on Figma Community under
CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Pylon re-implements the
ideas in code with changes; it contains no files or artwork from that design.

## Content you play

Pylon is a player. It doesn't include, host or link to any films, shows,
music or streams. You're responsible for having the right to play what you open.

## Trademarks

VLC and the VLC traffic-cone logo are trademarks of VideoLAN. Pylon is an
independent project and is not affiliated with, sponsored or endorsed by
VideoLAN. Pylon's icon is an original design. Other names mentioned
(for example OpenSubtitles, Windows, Python, Qt) belong to their owners.
