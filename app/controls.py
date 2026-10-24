"""The two auto-hiding bars that float over the video.

Top bar:    [library] [show / folder chip]   title   [PiP] [fullscreen] [menu]
Bottom bar: [prev][PLAY][next] time   (continue chip)   speed [subs][audio][queue][vol][cone][tune]
            ================ thick seek bar along the bottom edge =================
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from . import theme
from .util import fmt_time
from .widgets import ConeVolume, IconButton, OverlayWindow, SeekBar


class TopBar(OverlayWindow):
    library_clicked = Signal()
    folder_clicked = Signal()
    pip_clicked = Signal()
    fullscreen_clicked = Signal()
    menu_clicked = Signal()

    HEIGHT = 48

    def __init__(self, owner):
        super().__init__(owner, gradient="down")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(4)
        self.btn_library = IconButton("sidebar_left", "Library (Ctrl+L)", checkable=True)
        self.btn_library.clicked.connect(self.library_clicked)
        self.folder_chip = QPushButton("")
        self.folder_chip.setObjectName("Chip")
        self.folder_chip.setCursor(Qt.PointingHandCursor)
        self.folder_chip.setFocusPolicy(Qt.NoFocus)
        self.folder_chip.setToolTip("Open this folder in the library")
        self.folder_chip.clicked.connect(self.folder_clicked)
        self.title = QLabel("")
        self.title.setStyleSheet("font-size: 14px; font-weight: 600; background: transparent;")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.btn_pip = IconButton("pip", "Picture in picture (Ctrl+P)", checkable=True)
        self.btn_pip.clicked.connect(self.pip_clicked)
        self.btn_full = IconButton("fullscreen", "Fullscreen (F)")
        self.btn_full.clicked.connect(self.fullscreen_clicked)
        self.btn_menu = IconButton("menu", "Menu")
        self.btn_menu.clicked.connect(self.menu_clicked)
        self.cast_chip = QPushButton("")
        self.cast_chip.setObjectName("Chip")
        self.cast_chip.setFocusPolicy(Qt.NoFocus)
        self.cast_chip.setCursor(Qt.PointingHandCursor)
        self.cast_chip.clicked.connect(self.menu_clicked)
        self.cast_chip.hide()
        lay.addWidget(self.btn_library)
        lay.addWidget(self.folder_chip)
        lay.addSpacing(8)
        lay.addWidget(self.title, 1)
        lay.addSpacing(8)
        lay.addWidget(self.cast_chip)
        lay.addWidget(self.btn_pip)
        lay.addWidget(self.btn_full)
        lay.addWidget(self.btn_menu)
        self._full_title = ""

    def set_title(self, text: str):
        self._full_title = text
        self._elide()

    def set_folder(self, name: str):
        self.folder_chip.setText(f"{name}  ›" if name else "")
        self.folder_chip.setVisible(bool(name))

    def set_casting(self, name: str):
        """While casting, a chip says where the video is playing."""
        from .icons import icon
        self.cast_chip.setText(f"  {name}" if name else "")
        self.cast_chip.setIcon(icon("cast", theme.accent(), 14))
        self.cast_chip.setToolTip(f"Playing on {name}. Open the menu to stop casting" if name else "")
        self.cast_chip.setVisible(bool(name))

    def set_fullscreen(self, on: bool):
        self.btn_full.set_icon("exit_fullscreen" if on else "fullscreen")
        self.btn_full.setToolTip("Leave fullscreen (F)" if on else "Fullscreen (F)")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        fm = QFontMetrics(self.title.font())
        self.title.setText(fm.elidedText(self._full_title, Qt.ElideMiddle, max(60, self.title.width() - 4)))
        self.title.setToolTip(self._full_title)


class BottomBar(OverlayWindow):
    play_clicked = Signal()
    prev_clicked = Signal()
    next_clicked = Signal()
    subs_clicked = Signal()
    audio_clicked = Signal()
    queue_clicked = Signal()
    sidebar_clicked = Signal()
    mute_clicked = Signal()
    resume_clicked = Signal()
    speed_clicked = Signal()

    HEIGHT = 74

    def __init__(self, owner):
        super().__init__(owner, gradient="up")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 6, 12, 8)
        outer.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(2)
        self.btn_prev = IconButton("prev", "Previous (P)", size=18)
        self.btn_play = IconButton("play", "Play / pause (Space)", size=20, box=40, color=theme.on_accent)
        self.btn_play.setObjectName("PlayButton")
        self.btn_play.setFixedSize(50, 36)
        self.apply_glow()
        self.btn_next = IconButton("next", "Next (N)", size=18)
        self.btn_prev.clicked.connect(self.prev_clicked)
        self.btn_play.clicked.connect(self.play_clicked)
        self.btn_next.clicked.connect(self.next_clicked)
        self.time = QPushButton("0:00 / 0:00")
        self.time.setFlat(True)
        self.time.setFocusPolicy(Qt.NoFocus)
        self.time.setCursor(Qt.PointingHandCursor)
        self.time.setToolTip("Click to show remaining time")
        self.time.setStyleSheet("QPushButton { background: transparent; border: none; color: #EDEDED;"
                                " padding: 0 8px; }")
        self.time.clicked.connect(self._toggle_remaining)
        self.show_remaining = False

        self.resume = QPushButton("")
        self.resume.setObjectName("ResumeChip")
        self.resume.setCursor(Qt.PointingHandCursor)
        self.resume.setFocusPolicy(Qt.NoFocus)
        self.resume.clicked.connect(self.resume_clicked)
        self.resume.hide()

        self.speed = QPushButton("1x")
        self.speed.setObjectName("Chip")
        self.speed.setFocusPolicy(Qt.NoFocus)
        self.speed.setCursor(Qt.PointingHandCursor)
        self.speed.setToolTip("Playback speed  ([ and ])")
        self.speed.clicked.connect(self.speed_clicked)
        self.speed.hide()

        self.btn_subs = IconButton("subtitles", "Subtitles (V)")
        self.btn_audio = IconButton("audio", "Audio tracks and output (B)")
        self.btn_queue = IconButton("queue", "Queue (Ctrl+Q)", checkable=True)
        self.btn_mute = IconButton("volume", "Mute (M)", size=18)
        self.cone = ConeVolume()
        self.btn_tune = IconButton("tune", "Subtitle, audio, video and playback settings (Ctrl+T)", checkable=True)
        self.btn_subs.clicked.connect(self.subs_clicked)
        self.btn_audio.clicked.connect(self.audio_clicked)
        self.btn_queue.clicked.connect(self.queue_clicked)
        self.btn_mute.clicked.connect(self.mute_clicked)
        self.btn_tune.clicked.connect(self.sidebar_clicked)

        row.addWidget(self.btn_prev)
        row.addWidget(self.btn_play)
        row.addWidget(self.btn_next)
        row.addWidget(self.time)
        row.addStretch(1)
        row.addWidget(self.resume)
        row.addStretch(1)
        row.addWidget(self.speed)
        row.addSpacing(4)
        row.addWidget(self.btn_subs)
        row.addWidget(self.btn_audio)
        row.addWidget(self.btn_queue)
        row.addSpacing(6)
        row.addWidget(self.btn_mute)
        row.addWidget(self.cone)
        row.addSpacing(6)
        row.addWidget(self.btn_tune)
        outer.addLayout(row)
        self.seek = SeekBar()
        outer.addWidget(self.seek)
        self._pos = self._len = 0

    def apply_glow(self):
        """Neon themes: a soft coloured glow around the play button."""
        if theme.glow():
            from PySide6.QtGui import QColor
            from PySide6.QtWidgets import QGraphicsDropShadowEffect
            fx = QGraphicsDropShadowEffect(self.btn_play)
            fx.setBlurRadius(22)
            fx.setOffset(0, 0)
            c = QColor(theme.accent2())
            c.setAlpha(200)
            fx.setColor(c)
            self.btn_play.setGraphicsEffect(fx)
        else:
            self.btn_play.setGraphicsEffect(None)

    def set_playing(self, playing: bool):
        self.btn_play.set_icon("pause" if playing else "play")

    def set_time(self, pos: int, length: int):
        self._pos, self._len = pos, length
        force_h = length >= 3_600_000
        if self.show_remaining and length:
            left = f"-{fmt_time(max(0, length - pos), force_h)}"
            self.time.setText(f"{left} / {fmt_time(length, force_h)}")
        else:
            self.time.setText(f"{fmt_time(pos, force_h)} / {fmt_time(length, force_h)}")
        self.seek.set_length(length)
        self.seek.set_position(pos)

    def _toggle_remaining(self):
        self.show_remaining = not self.show_remaining
        self.time.setToolTip("Click to show elapsed time" if self.show_remaining else "Click to show remaining time")
        self.set_time(self._pos, self._len)

    def set_speed(self, rate: float):
        self.speed.setText(f"{rate:g}x")
        self.speed.setVisible(abs(rate - 1.0) > 1e-3)

    def set_volume(self, v: int, muted: bool):
        self.cone.set_value(v, muted)
        self.btn_mute.set_icon("volume_mute" if muted or v == 0 else "volume")
