# Third-party notices

Pylon's own code is under the MIT licence (see `LICENSE`). Pylon does **not**
include or redistribute any of the software below. `setup.bat` installs the
Python packages from PyPI, and you install VLC yourself.

| Component | Used for | Licence | Source |
| --- | --- | --- | --- |
| libVLC (VLC media player 3.0) | All playback, decoding and streaming | LGPL 2.1 or later (some VLC plugins are GPL) | https://www.videolan.org/vlc/ · https://code.videolan.org/videolan/vlc |
| python-vlc | Python bindings for libVLC | LGPL 2.1 or later | https://github.com/oaubert/python-vlc |
| Qt for Python (PySide6-Essentials, Shiboken6) | The user interface | LGPL v3 (or commercial) | https://www.qt.io/qt-for-python · https://code.qt.io/cgit/pyside/pyside-setup.git |
| Python | Runs Pylon | PSF License | https://www.python.org |

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
