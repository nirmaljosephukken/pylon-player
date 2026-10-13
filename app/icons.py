"""Monochrome line icons drawn as small SVGs, recolored on the fly.

All icons are original 24x24 line drawings. `icon(name, color)` returns a
QIcon; `pixmap(name, color, size)` returns a QPixmap.
"""
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_S = 'fill="none" stroke="{c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'
_F = 'fill="{c}" stroke="none"'

ICONS = {
    "play": f'<path {_F} d="M7 4.5v15a.8.8 0 0 0 1.2.7l12-7.5a.8.8 0 0 0 0-1.4l-12-7.5A.8.8 0 0 0 7 4.5z"/>',
    "pause": f'<rect {_F} x="6" y="4.5" width="4.2" height="15" rx="1"/><rect {_F} x="13.8" y="4.5" width="4.2" height="15" rx="1"/>',
    "prev": f'<path {_F} d="M18 5.5v13a.7.7 0 0 1-1.1.6L8 12.6a.7.7 0 0 1 0-1.2l8.9-6.5a.7.7 0 0 1 1.1.6z"/><rect {_F} x="5" y="5" width="2.2" height="14" rx=".8"/>',
    "next": f'<path {_F} d="M6 5.5v13a.7.7 0 0 0 1.1.6l8.9-6.5a.7.7 0 0 0 0-1.2L7.1 4.9A.7.7 0 0 0 6 5.5z"/><rect {_F} x="16.8" y="5" width="2.2" height="14" rx=".8"/>',
    "stop": f'<rect {_F} x="6" y="6" width="12" height="12" rx="1.2"/>',
    "fullscreen": f'<path {_S} d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4"/>',
    "exit_fullscreen": f'<path {_S} d="M9 4v4a1 1 0 0 1-1 1H4M20 9h-4a1 1 0 0 1-1-1V4M15 20v-4a1 1 0 0 1 1-1h4M4 15h4a1 1 0 0 1 1 1v4"/>',
    "pip": f'<rect {_S} x="3" y="5" width="18" height="14" rx="1.5"/><rect {_F} x="12" y="11.5" width="7" height="5.5" rx="1"/>',
    "menu": f'<path {_S} d="M4 7h16M4 12h16M4 17h16"/>',
    "more": f'<circle {_F} cx="5.5" cy="12" r="1.7"/><circle {_F} cx="12" cy="12" r="1.7"/><circle {_F} cx="18.5" cy="12" r="1.7"/>',
    "sidebar_left": f'<rect {_S} x="3" y="4" width="18" height="16" rx="1.5"/><path {_S} d="M9 4v16"/>',
    "sidebar_right": f'<rect {_S} x="3" y="4" width="18" height="16" rx="1.5"/><path {_S} d="M15 4v16"/>',
    "queue": f'<path {_S} d="M4 6h11M4 11h11M4 16h6"/><path {_F} d="M15 13.5v6.5l5.5-3.25z"/>',
    "subtitles": f'<rect {_S} x="3" y="5" width="18" height="14" rx="1.5"/><path {_S} d="M7 12h3M13 12h4M7 15.5h6M15.5 15.5h1.5"/>',
    "audio": f'<path {_S} d="M4 14v-2a8 8 0 0 1 16 0v2"/><rect {_S} x="3.5" y="14" width="4" height="6" rx="1"/><rect {_S} x="16.5" y="14" width="4" height="6" rx="1"/>',
    "volume": f'<path {_F} d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path {_S} d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
    "volume_mute": f'<path {_F} d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path {_S} d="M16 9.5l5 5M21 9.5l-5 5"/>',
    "tune": f'<path {_S} d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle {_S} cx="15" cy="7" r="2"/><circle {_S} cx="9" cy="17" r="2"/>',
    "video": f'<rect {_S} x="3" y="6" width="13" height="12" rx="1.5"/><path {_S} d="M16 10.5l5-3v9l-5-3"/>',
    "speed": f'<path {_S} d="M4.5 17a8 8 0 1 1 15 0"/><path {_S} d="M12 13l4-4"/><circle {_F} cx="12" cy="13" r="1.4"/>',
    "bookmark": f'<path {_S} d="M7 4h10a1 1 0 0 1 1 1v15l-6-4-6 4V5a1 1 0 0 1 1-1z"/>',
    "bookmark_add": f'<path {_S} d="M7 4h10a1 1 0 0 1 1 1v15l-6-4-6 4V5a1 1 0 0 1 1-1z"/><path {_S} d="M12 7.5v5M9.5 10h5"/>',
    "folder": f'<path {_S} d="M3.5 7a1.5 1.5 0 0 1 1.5-1.5h4l2 2h8a1.5 1.5 0 0 1 1.5 1.5v8.5A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/>',
    "folder_add": f'<path {_S} d="M3.5 7a1.5 1.5 0 0 1 1.5-1.5h4l2 2h8a1.5 1.5 0 0 1 1.5 1.5v8.5A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5z"/><path {_S} d="M12 10.5v5M9.5 13h5"/>',
    "file": f'<path {_S} d="M6 3.5h8l4 4V20a.5.5 0 0 1-.5.5h-11A.5.5 0 0 1 6 20z"/><path {_S} d="M14 3.5V8h4"/>',
    "home": f'<path {_S} d="M4 11l8-6.5 8 6.5V19a1 1 0 0 1-1 1h-4.5v-5h-5v5H5a1 1 0 0 1-1-1z"/>',
    "library": f'<path {_S} d="M5 4v16M9.5 4v16"/><path {_S} d="M14 5l4.5 14.5"/>',
    "music": f'<path {_S} d="M9 18V6l11-2v12"/><circle {_S} cx="6.5" cy="18" r="2.5"/><circle {_S} cx="17.5" cy="16" r="2.5"/>',
    "stream": f'<circle {_F} cx="12" cy="12" r="2"/><path {_S} d="M8.5 8.5a5 5 0 0 0 0 7M15.5 8.5a5 5 0 0 1 0 7M5.5 5.5a9.2 9.2 0 0 0 0 13M18.5 5.5a9.2 9.2 0 0 1 0 13"/>',
    "playlist": f'<path {_S} d="M4 6h12M4 11h12M4 16h7"/><path {_S} d="M15 18.5V13l5 1.5"/><circle {_S} cx="13.5" cy="18.5" r="1.8"/>',
    "clock": f'<circle {_S} cx="12" cy="12" r="8.5"/><path {_S} d="M12 7v5l3.5 2"/>',
    "pin": f'<path {_S} d="M9 4h6l-1 5 3 3H7l3-3zM12 12v8"/>',
    "plus": f'<path {_S} d="M12 5v14M5 12h14"/>',
    "minus": f'<path {_S} d="M5 12h14"/>',
    "close": f'<path {_S} d="M6 6l12 12M18 6L6 18"/>',
    "search": f'<circle {_S} cx="11" cy="11" r="6.5"/><path {_S} d="M16 16l4 4"/>',
    "sort": f'<path {_S} d="M7 5v14M4 16l3 3 3-3M17 19V5M14 8l3-3 3 3"/>',
    "check": f'<path {_S} d="M5 12.5l4.5 4.5L19 7.5"/>',
    "trash": f'<path {_S} d="M5 7h14M10 7V5h4v2M7 7l1 13h8l1-13"/>',
    "chevron_right": f'<path {_S} d="M9.5 6l6 6-6 6"/>',
    "chevron_left": f'<path {_S} d="M14.5 6l-6 6 6 6"/>',
    "chevron_down": f'<path {_S} d="M6 9.5l6 6 6-6"/>',
    "arrow_up": f'<path {_S} d="M12 19V6M6.5 11.5L12 6l5.5 5.5"/>',
    "keyboard": f'<rect {_S} x="2.5" y="6" width="19" height="12" rx="1.5"/><path {_S} d="M6 10h.01M9.5 10h.01M13 10h.01M16.5 10h.01M8 14.5h8"/>',
    "settings": f'<circle {_S} cx="12" cy="12" r="3"/><path {_S} d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8"/>',
    "eye_off": f'<path {_S} d="M3 12s3.5-6 9-6c1.5 0 2.8.4 4 1M21 12s-3.5 6-9 6c-1.5 0-2.8-.4-4-1M4 20L20 4"/>',
    "timer": f'<circle {_S} cx="12" cy="13.5" r="7"/><path {_S} d="M12 10v3.5l2 2M9.5 3h5"/>',
    "repeat": f'<path {_S} d="M17 3.5l3 3-3 3M4 11.5v-1a4 4 0 0 1 4-4h12M7 20.5l-3-3 3-3M20 12.5v1a4 4 0 0 1-4 4H4"/>',
    "shuffle": f'<path {_S} d="M16.5 4h3.5v3.5M4 19.5L20 4M20 16.5V20h-3.5M14.5 14.5L20 20M4 4.5l5 5"/>',
    "cast": f'<path {_S} d="M3 16.5a4.5 4.5 0 0 1 4.5 4.5M3 12.5A8.5 8.5 0 0 1 11.5 21M3 8.5V6a1 1 0 0 1 1-1h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1h-5.5"/><circle {_F} cx="3.5" cy="20.5" r="1"/>',
    "globe": f'<circle {_S} cx="12" cy="12" r="8.5"/><path {_S} d="M3.5 12h17M12 3.5c2.5 2.5 3.5 5.5 3.5 8.5s-1 6-3.5 8.5c-2.5-2.5-3.5-5.5-3.5-8.5s1-6 3.5-8.5z"/>',
    "info": f'<circle {_S} cx="12" cy="12" r="8.5"/><path {_S} d="M12 11v5.5M12 7.8h.01"/>',
    "eq": f'<path {_S} d="M6 4v16M12 4v16M18 4v16"/><rect {_F} x="4" y="13" width="4" height="2.4" rx=".6"/><rect {_F} x="10" y="7" width="4" height="2.4" rx=".6"/><rect {_F} x="16" y="15" width="4" height="2.4" rx=".6"/>',
    "rotate": f'<path {_S} d="M20 12a8 8 0 1 1-2.4-5.7M20 4v4.5h-4.5"/>',
    "snapshot": f'<path {_S} d="M4 8a1.5 1.5 0 0 1 1.5-1.5h2L9 4.5h6l1.5 2h2A1.5 1.5 0 0 1 20 8v10a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18z"/><circle {_S} cx="12" cy="13" r="3.5"/>',
    "save": f'<path {_S} d="M5 4h11l3 3v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z"/><path {_S} d="M8 4v5h7V4M8 20v-6h8v6"/>',
    "drag": f'<circle {_F} cx="9" cy="6" r="1.4"/><circle {_F} cx="15" cy="6" r="1.4"/><circle {_F} cx="9" cy="12" r="1.4"/><circle {_F} cx="15" cy="12" r="1.4"/><circle {_F} cx="9" cy="18" r="1.4"/><circle {_F} cx="15" cy="18" r="1.4"/>',
    # App mark: an accent tile with a striped play arrow (original design, not the VLC logo)
    "cone": '<rect fill="{c}" x="2" y="2" width="20" height="20" rx="4.5"/><path fill="#111111" d="M9 6.8v10.4a.7.7 0 0 0 1.05.6l8.2-5.2a.7.7 0 0 0 0-1.2l-8.2-5.2A.7.7 0 0 0 9 6.8z"/><path fill="{c}" d="M8.6 9.75h6.9v1.35H8.6zM8.6 12.9h6.9v1.35H8.6z"/>',
}


def _svg(name: str, color: str) -> bytes:
    body = ICONS.get(name, ICONS["info"]).replace("{c}", color)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'.encode()


@lru_cache(maxsize=1024)
def pixmap(name: str, color: str = "#EDEDED", size: int = 20, dpr: float = 2.0) -> QPixmap:
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(_svg(name, color)))
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    px.setDevicePixelRatio(dpr)
    return px


def icon(name: str, color: str = "#EDEDED", size: int = 20, active: str | None = None) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal, QIcon.Off)
    ic.addPixmap(pixmap(name, "#5E5E5E", size), QIcon.Disabled, QIcon.Off)
    if active:
        ic.addPixmap(pixmap(name, active, size), QIcon.Normal, QIcon.On)
    return ic
