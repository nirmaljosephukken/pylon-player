"""Right-hand settings sidebar with five tabs: Subtitles, Audio, Video,
Playback, Bookmarks. Everything you tweak while watching lives here instead
of in a dialog that covers the video. A preset row at the top saves the
current tweaks for a show and re-applies them on every episode."""
import os

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFontComboBox,
                               QGridLayout, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QScrollArea,
                               QSizePolicy, QSlider, QSpinBox, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from . import theme
from .colour_dialog import choose_colour
from .engine import CUSTOM_EQ, DEFAULT_SUB_STYLE, EQ_RANGE
from .icons import icon
from .util import (display_name, find_subtitle_candidates, fmt_delay, fmt_time, is_url,
                   match_subtitle, parse_subtitles)
from .widgets import IconButton, SubtitleTimeline, hline


def section(text):
    lab = QLabel(text.upper())
    lab.setObjectName("Section")
    return lab


def muted(text):
    lab = QLabel(text)
    lab.setObjectName("Muted")
    lab.setWordWrap(True)
    return lab


def scroll_page():
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    inner = QWidget()
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(18, 12, 18, 18)
    lay.setSpacing(8)
    sc.setWidget(inner)
    return sc, lay


class ValueSlider(QWidget):
    """Slider with a live value label and optional -/+ nudge buttons."""
    changed = Signal(int)

    def __init__(self, lo, hi, step, value, fmt=str, nudge: int | None = None, reset: int | None = None):
        super().__init__()
        self.fmt = fmt
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setSingleStep(step)
        self.slider.setPageStep(step * 5)
        self.slider.setValue(value)
        self.slider.setFocusPolicy(Qt.NoFocus)
        self.label = QLabel(fmt(value))
        self.label.setObjectName("Value")
        self.label.setMinimumWidth(56)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.step = step
        if nudge:
            b1 = IconButton("minus", f"-{nudge}", size=14, box=24)
            b1.clicked.connect(lambda: self.set_value(self.slider.value() - nudge, emit=True))
            lay.addWidget(b1)
        lay.addWidget(self.slider, 1)
        if nudge:
            b2 = IconButton("plus", f"+{nudge}", size=14, box=24)
            b2.clicked.connect(lambda: self.set_value(self.slider.value() + nudge, emit=True))
            lay.addWidget(b2)
        lay.addWidget(self.label)
        if reset is not None:
            br = IconButton("rotate", "Reset", size=14, box=24)
            br.clicked.connect(lambda: self.set_value(reset, emit=True))
            lay.addWidget(br)
        self.slider.valueChanged.connect(self._on)

    def _on(self, v):
        if self.step > 1:
            snapped = round(v / self.step) * self.step
            if snapped != v:
                self.slider.setValue(snapped)
                return
        self.label.setText(self.fmt(v))
        self.changed.emit(v)

    def set_value(self, v, emit=False):
        v = max(self.slider.minimum(), min(self.slider.maximum(), int(v)))
        if not emit:
            self.slider.blockSignals(True)
        self.slider.setValue(v)
        self.slider.blockSignals(False)
        self.label.setText(self.fmt(v))
        if emit and self.slider.value() == v:
            pass

    def value(self):
        return self.slider.value()


class ChipGroup(QWidget):
    """A row/grid of checkable chips acting as a single choice."""
    picked = Signal(object)

    def __init__(self, options: list[tuple[str, object]], cols=3, icon_name: str | None = None,
                 tips: dict | None = None):
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.values = []
        for i, (label, val) in enumerate(options):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip((tips or {}).get(val, label))
            b.setMinimumWidth(0)
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            b.setCursor(Qt.PointingHandCursor)
            if icon_name:
                b.setIcon(icon(icon_name, theme.MUTED, 14))
            self.group.addButton(b, i)
            self.values.append(val)
            grid.addWidget(b, i // cols, i % cols)
        self.group.idClicked.connect(lambda i: self.picked.emit(self.values[i]))

    def select(self, val):
        for i, v in enumerate(self.values):
            if v == val:
                self.group.button(i).setChecked(True)
                return
        b = self.group.checkedButton()
        if b:
            self.group.setExclusive(False)
            b.setChecked(False)
            self.group.setExclusive(True)


EQ_TIPS = {   # one line per VLC preset, from the shape of its curve (#38)
    "Flat": "every band level, just a little louder.",
    "Classical": "natural lows and mids, softer highs.",
    "Club": "warm, full mids without extra bass.",
    "Dance": "big bass with the upper mids pulled back.",
    "Full bass": "heavy low end, much softer highs.",
    "Full bass and treble": "boosted lows and highs, dipped mids.",
    "Full treble": "bright and crisp, with the bass cut.",
    "Headphones": "extra punch and sparkle for headphones.",
    "Large Hall": "strong bass and low mids, like a big room.",
    "Live": "forward mids for a concert feel.",
    "Party": "only the deepest bass and the top end boosted.",
    "Pop": "vocals forward, slightly softer highs.",
    "Reggae": "a lift around 1 to 2 kHz, lower mids dipped.",
    "Rock": "punchy bass and bright highs, scooped mids.",
    "Ska": "bright highs, light bass.",
    "Soft": "gentle bass and airy highs.",
    "Soft rock": "warm lows, softened upper mids.",
    "Techno": "deep bass and bright highs, dipped mids.",
}


def _freq_label(hz: float) -> str:
    return f"{hz / 1000:g}k" if hz >= 1000 else f"{hz:g}".split(".")[0]


class EqualizerPanel(QWidget):
    """Preamp plus VLC's 10 equalizer bands, in half-dB steps (#38)."""
    changed = Signal(dict)

    def __init__(self, freqs: list[float]):
        super().__init__()
        self.freqs = freqs or [31.25, 62.5, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
        steps = int(EQ_RANGE * 2)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(muted("Preamp"))
        head.addStretch(1)
        reset = QPushButton("Flat")
        reset.setToolTip("Set every band and the preamp back to 0 dB")
        reset.setCursor(Qt.PointingHandCursor)
        reset.clicked.connect(lambda: (self.set_curve({"preamp": 0.0, "bands": [0.0] * 10}), self._emit()))
        head.addWidget(reset)
        lay.addLayout(head)
        self.preamp = ValueSlider(-steps, steps, 1, 0, lambda v: f"{v / 2:+g} dB")
        self.preamp.changed.connect(lambda _v: self._emit())
        lay.addWidget(self.preamp)
        grid = QGridLayout()
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(2)
        self.bands = []
        self.values = []
        for i, hz in enumerate(self.freqs[:10]):
            val = QLabel("0")
            val.setAlignment(Qt.AlignCenter)
            val.setStyleSheet(f"color: {theme.MUTED}; font-size: 10px;")
            sl = QSlider(Qt.Vertical)
            sl.setRange(-steps, steps)
            sl.setPageStep(4)
            sl.setFixedHeight(120)
            sl.setFocusPolicy(Qt.NoFocus)
            sl.setToolTip(f"{_freq_label(hz)}Hz")
            sl.valueChanged.connect(lambda v, lab=val: (lab.setText(f"{v / 2:+g}" if v else "0"), self._emit()))
            name = QLabel(_freq_label(hz))
            name.setAlignment(Qt.AlignCenter)
            name.setStyleSheet(f"color: {theme.FAINT}; font-size: 10px;")
            grid.addWidget(val, 0, i)
            grid.addWidget(sl, 1, i, Qt.AlignHCenter)
            grid.addWidget(name, 2, i)
            self.bands.append(sl)
            self.values.append(val)
        lay.addLayout(grid)
        lay.addWidget(muted("Drag a band up or down, from -20 to +20 dB. "
                            "Saved presets for a show remember this curve too."))
        self._quiet = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)       # apply while dragging, without flooding VLC
        self._timer.timeout.connect(lambda: self.changed.emit(self.curve()))

    def curve(self) -> dict:
        return {"preamp": self.preamp.value() / 2, "bands": [b.value() / 2 for b in self.bands]}

    def set_curve(self, curve: dict | None):
        curve = curve or {"preamp": 0.0, "bands": [0.0] * 10}
        self._quiet = True
        self.preamp.set_value(round(curve["preamp"] * 2))
        for b, lab, v in zip(self.bands, self.values, curve["bands"]):
            b.setValue(round(v * 2))
            lab.setText(f"{round(v * 2) / 2:+g}" if round(v * 2) else "0")
        self._quiet = False

    def _emit(self):
        if not self._quiet:
            self._timer.start()


class SettingsSidebar(QWidget):
    WIDTH = 340

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.engine = win.engine
        self.store = win.store
        self.setObjectName("Panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(self.WIDTH)
        self._cues_path = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # header
        head = QHBoxLayout()
        head.setContentsMargins(18, 10, 10, 6)
        title = QLabel("Settings")
        title.setObjectName("H2")
        head.addWidget(title)
        head.addStretch(1)
        close = IconButton("close", "Close", size=16)
        close.clicked.connect(lambda: win.toggle_sidebar(False))
        head.addWidget(close)
        root.addLayout(head)

        # preset row
        pr = QHBoxLayout()
        pr.setContentsMargins(18, 0, 18, 10)
        pr.setSpacing(6)
        self.preset_combo = QComboBox()
        self.preset_combo.setToolTip("Presets keep subtitle timing, styles, tracks and filters for a show")
        self.preset_combo.activated.connect(self._preset_picked)
        save = IconButton("save", "Save current settings as a preset for this show", size=16)
        save.clicked.connect(self.save_preset)
        delete = IconButton("trash", "Delete this preset", size=16)
        delete.clicked.connect(self.delete_preset)
        pr.addWidget(QLabel("Preset"))
        pr.addWidget(self.preset_combo, 1)
        pr.addWidget(save)
        pr.addWidget(delete)
        root.addLayout(pr)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(True)
        self.tabs.tabBar().setUsesScrollButtons(False)
        self.tabs.tabBar().setElideMode(Qt.ElideNone)
        self.tabs.tabBar().setFocusPolicy(Qt.NoFocus)
        self.tabs.tabBar().setDrawBase(False)       # the base line was drawn half-way across, above the tabs
        root.addWidget(self.tabs, 1)
        self._build_subtitles()
        self._build_audio()
        self._build_video()
        self._build_playback()
        self._build_bookmarks()
        tab_names = ("subtitles", "audio", "video", "playback", "bookmarks")
        selected = self.store.setting("settings_startup_tab")
        if selected == "last":
            selected = self.store.setting("settings_last_tab")
        self.tabs.setCurrentIndex(tab_names.index(selected) if selected in tab_names else 0)
        self.tabs.currentChanged.connect(lambda i: self.store.set_setting("settings_last_tab", tab_names[i]))
        for cb in self.findChildren(QComboBox):     # long track names must not widen the panel
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(8)
            cb.setMinimumWidth(0)
        self.refresh_presets()

        self.engine.tracks_changed.connect(self.refresh_tracks, Qt.QueuedConnection)
        self.engine.media_changed.connect(lambda _: QTimer.singleShot(50, self.on_media_changed))

    # ================================================================ subtitles
    def _build_subtitles(self):
        page, lay = scroll_page()
        self.tabs.addTab(page, "Subtitles")

        lay.addWidget(section("Track"))
        self.sub_combo = QComboBox()
        self.sub_combo.activated.connect(lambda i: self.engine.set_sub(self.sub_combo.itemData(i)))
        lay.addWidget(self.sub_combo)
        row = QHBoxLayout()
        add = QPushButton("Add subtitles…")
        add.setIcon(icon("plus", theme.TEXT, 14))
        add.clicked.connect(lambda: self.win.open_subtitle_dialog())
        online = QPushButton("Find online")
        online.setIcon(icon("globe", theme.TEXT, 14))
        online.setToolTip("Search OpenSubtitles for this title in your browser")
        online.clicked.connect(self._search_online)
        row.addWidget(add)
        row.addWidget(online)
        lay.addLayout(row)

        lay.addWidget(section("Timing"))
        lay.addWidget(muted("Pause when someone starts talking, then drag the timeline until their line sits under the white playhead."))
        self.sub_timeline = SubtitleTimeline()
        self.sub_timeline.delay_changed.connect(self._sub_delay_from_timeline)
        lay.addWidget(self.sub_timeline)
        self.sub_delay = ValueSlider(-10000, 10000, 50, 0, fmt_delay, nudge=50, reset=0)
        self.sub_delay.changed.connect(self._set_sub_delay)
        lay.addWidget(self.sub_delay)

        lay.addWidget(section("Look"))
        mode = QHBoxLayout()
        self.size_rel = QRadioButton("Relative size")
        self.size_px = QRadioButton("Exact size (px)")
        self.size_rel.setChecked(True)
        mode.addWidget(self.size_rel)
        mode.addWidget(self.size_px)
        lay.addLayout(mode)
        self.size_scale = ValueSlider(40, 300, 10, 100, lambda v: f"{v}%")
        self.size_pxv = ValueSlider(10, 120, 1, 32, lambda v: f"{v}px")
        self.size_pxv.hide()
        self.size_rel.toggled.connect(lambda on: (self.size_scale.setVisible(on), self.size_pxv.setVisible(not on)))
        lay.addWidget(self.size_scale)
        lay.addWidget(self.size_pxv)

        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        self.font_combo = QFontComboBox()
        self.font_combo.setEditable(False)
        self.font_default = QCheckBox("Default font")
        self.font_default.setChecked(True)
        self.font_default.toggled.connect(lambda on: self.font_combo.setEnabled(not on))
        self.font_combo.setEnabled(False)
        g.addWidget(QLabel("Font"), 0, 0)
        g.addWidget(self.font_combo, 0, 1)
        g.addWidget(self.font_default, 1, 1)
        self.color_btn = QPushButton()
        self.color_btn.clicked.connect(self._pick_color)
        self._sub_color = "#FFFFFF"
        self._paint_color_btn()
        g.addWidget(QLabel("Color"), 2, 0)
        g.addWidget(self.color_btn, 2, 1)
        self.outline = QComboBox()
        for label, v in (("None", 0), ("Thin", 2), ("Normal", 4), ("Thick", 6)):
            self.outline.addItem(label, v)
        self.outline.setCurrentIndex(2)
        g.addWidget(QLabel("Outline"), 3, 0)
        g.addWidget(self.outline, 3, 1)
        self.bold = QCheckBox("Bold")
        g.addWidget(self.bold, 4, 1)
        lay.addLayout(g)
        lay.addWidget(QLabel("Background box"))
        self.bg = ValueSlider(0, 255, 5, 0, lambda v: f"{round(v / 2.55)}%")
        lay.addWidget(self.bg)
        lay.addWidget(QLabel("Distance from bottom"))
        self.margin = ValueSlider(0, 300, 5, 0, lambda v: f"{v}px")
        lay.addWidget(self.margin)
        apply = QPushButton("Apply look")
        apply.setObjectName("Primary")
        apply.clicked.connect(self.apply_sub_style)
        lay.addWidget(apply)
        lay.addWidget(muted("Applying the look restarts the video at the same spot (the VLC engine reads fonts at start-up)."))

        lay.addWidget(section("Every episode"))
        lay.addWidget(muted("Pick a language to switch to automatically, e.g. eng, en, English. Use \"off\" to start with subtitles off."))
        self.sub_lang = QComboBox()
        self.sub_lang.setEditable(True)
        self.sub_lang.addItems(["", "off", "eng", "English", "hin", "mal", "spa", "fre", "jpn"])
        self.sub_lang.setCurrentText(self.store.setting("sub_lang"))
        self.sub_lang.currentTextChanged.connect(lambda t: self.store.set_setting("sub_lang", t.strip()))
        lay.addWidget(self.sub_lang)
        lay.addStretch(1)

    def _search_online(self):
        name = display_name(self.engine.current or "") or ""
        q = QUrl.toPercentEncoding(name).data().decode()
        QDesktopServices.openUrl(QUrl(f"https://www.opensubtitles.org/en/search2/moviename-{q}/sublanguageid-all"))

    def _set_sub_delay(self, ms):
        self.engine.set_sub_delay(ms)
        self.sub_timeline.set_state(self.engine.time(), ms)

    def _sub_delay_from_timeline(self, ms):
        self.engine.set_sub_delay(ms)
        self.sub_delay.set_value(ms)

    def set_sub_delay_ui(self, ms):
        self.sub_delay.set_value(ms)
        self.sub_timeline.set_state(self.engine.time(), ms)

    def _pick_color(self):
        c = choose_colour(self.store, self._sub_color, self, "Subtitle color")
        if c.isValid():
            self._sub_color = c.name()
            self._paint_color_btn()

    def _paint_color_btn(self):
        from PySide6.QtGui import QIcon, QPixmap
        px = QPixmap(14, 14)
        px.fill(QColor(self._sub_color))
        self.color_btn.setIcon(QIcon(px))
        self.color_btn.setText(self._sub_color.upper())

    def sub_style_from_ui(self) -> dict:
        return {
            "size_mode": "relative" if self.size_rel.isChecked() else "precise",
            "scale": self.size_scale.value(),
            "px": self.size_pxv.value(),
            "font": "" if self.font_default.isChecked() else self.font_combo.currentFont().family(),
            "color": self._sub_color,
            "outline": self.outline.currentData(),
            "background": self.bg.value(),
            "bold": self.bold.isChecked(),
            "margin": self.margin.value(),
        }

    def load_sub_style(self, st: dict):
        st = {**DEFAULT_SUB_STYLE, **(st or {})}
        self.size_rel.setChecked(st["size_mode"] == "relative")
        self.size_px.setChecked(st["size_mode"] == "precise")
        self.size_scale.set_value(st["scale"])
        self.size_pxv.set_value(st["px"])
        self.font_default.setChecked(not st["font"])
        if st["font"]:
            self.font_combo.setCurrentFont(QFont(st["font"]))
        self._sub_color = st["color"]
        self._paint_color_btn()
        i = self.outline.findData(st["outline"])
        self.outline.setCurrentIndex(i if i >= 0 else 2)
        self.bold.setChecked(bool(st["bold"]))
        self.bg.set_value(st["background"])
        self.margin.set_value(st["margin"])

    def apply_sub_style(self):
        self.engine.sub_style = self.sub_style_from_ui()
        self.store.data["settings"]["sub_style"] = self.engine.sub_style
        self.store.save()
        self.engine.rebuild()
        self.win.toast("Subtitle look applied")

    # ================================================================ audio
    def _build_audio(self):
        page, lay = scroll_page()
        self.tabs.addTab(page, "Audio")
        lay.addWidget(section("Track"))
        self.audio_combo = QComboBox()
        self.audio_combo.activated.connect(lambda i: self.engine.set_audio(self.audio_combo.itemData(i)))
        lay.addWidget(self.audio_combo)
        lay.addWidget(section("Output"))
        self.device_combo = QComboBox()
        self.device_combo.activated.connect(lambda i: self.engine.set_device(self.device_combo.itemData(i)))
        lay.addWidget(self.device_combo)
        lay.addWidget(section("Timing"))
        self.audio_delay = ValueSlider(-5000, 5000, 50, 0, fmt_delay, nudge=50, reset=0)
        self.audio_delay.changed.connect(self.engine.set_audio_delay)
        lay.addWidget(self.audio_delay)
        lay.addWidget(section("Sound"))
        names = self.engine.eq_presets()
        short = {"Full bass and treble": "Bass and treble", "Full bass": "Bass boost", "Full treble": "Treble boost"}
        opts = [("Off", -1)] + [(short.get(n, n), i) for i, n in enumerate(names)] + [("Custom", CUSTOM_EQ)]
        tips = {i: f"{n}: {EQ_TIPS[n]}" for i, n in enumerate(names) if n in EQ_TIPS}
        tips[-1] = "Off: the sound as it is in the file."
        tips[CUSTOM_EQ] = "Custom: shape the sound yourself with 10 bands."
        self.eq = ChipGroup(opts, cols=2, tips=tips)
        self.eq.picked.connect(self._set_eq)
        self.eq.select(-1)
        lay.addWidget(self.eq)
        self.eq_custom = EqualizerPanel(self.engine.eq_bands())
        self.eq_custom.changed.connect(self._custom_eq_changed)
        self.eq_custom.hide()
        lay.addWidget(self.eq_custom)
        self._eq_save_timer = QTimer(self)
        self._eq_save_timer.setSingleShot(True)
        self._eq_save_timer.setInterval(600)
        self._eq_save_timer.timeout.connect(
            lambda: self.store.set_setting("eq_custom", self.engine.live.get("eq_custom")))
        lay.addWidget(section("Every episode"))
        lay.addWidget(muted("Audio language to pick automatically, e.g. jpn, eng, Hindi."))
        self.audio_lang = QComboBox()
        self.audio_lang.setEditable(True)
        self.audio_lang.addItems(["", "eng", "English", "jpn", "hin", "mal", "tam", "spa"])
        self.audio_lang.setCurrentText(self.store.setting("audio_lang"))
        self.audio_lang.currentTextChanged.connect(lambda t: self.store.set_setting("audio_lang", t.strip()))
        lay.addWidget(self.audio_lang)
        lay.addStretch(1)

    def _set_eq(self, idx):
        if idx == CUSTOM_EQ:
            e = self.engine
            if e.live["eq"] != CUSTOM_EQ:
                # your saved curve, or else start from the preset you were on
                curve = e.clean_curve(self.store.setting("eq_custom")) or e.eq_preset_curve(e.live["eq"])
                e.live["eq_custom"] = curve
            self.engine.set_eq(CUSTOM_EQ)
            self.eq_custom.set_curve(self.engine.live["eq_custom"])
            self.eq_custom.show()
            self.win.toast("Equalizer: Custom")
            return
        self.eq_custom.hide()
        self.engine.set_eq(idx)
        name = "Off" if idx < 0 else self.engine.eq_presets()[idx]
        self.win.toast(f"Equalizer: {name}")

    def _custom_eq_changed(self, curve):
        self.engine.set_custom_eq(curve)
        self._eq_save_timer.start()

    # ================================================================ video
    def _build_video(self):
        page, lay = scroll_page()
        self.tabs.addTab(page, "Video")
        lay.addWidget(section("Track"))
        self.video_combo = QComboBox()
        self.video_combo.activated.connect(lambda i: self.engine.set_video(self.video_combo.itemData(i)))
        lay.addWidget(self.video_combo)

        lay.addWidget(section("Aspect ratio"))
        self.aspect = ChipGroup([("Auto", ""), ("16:9", "16:9"), ("4:3", "4:3"), ("21:9", "21:9"),
                                 ("2.35:1", "235:100"), ("1:1", "1:1")], cols=3)
        self.aspect.picked.connect(lambda v: (self.engine.set_aspect(v), self.win.toast(f"Aspect ratio: {v or 'Auto'}")))
        self.aspect.select("")
        lay.addWidget(self.aspect)

        lay.addWidget(section("Crop and zoom"))
        self.crop = ChipGroup([("No crop", ""), ("16:9", "16:9"), ("21:9", "21:9"), ("4:3", "4:3"),
                               ("2.39:1", "239:100"), ("1:1", "1:1")], cols=3)
        self.crop.picked.connect(lambda v: (self.engine.set_crop(v), self.win.toast(f"Crop: {v or 'None'}")))
        self.crop.select("")
        lay.addWidget(self.crop)
        self.zoom = ChipGroup([("Fit", 0.0), ("0.5x", 0.5), ("1x", 1.0), ("2x", 2.0)], cols=4)
        self.zoom.picked.connect(lambda v: (self.engine.set_zoom(v), self.win.toast(f"Zoom: {'Fit' if not v else f'{v:g}x'}")))
        self.zoom.select(0.0)
        lay.addWidget(self.zoom)

        lay.addWidget(section("Picture"))
        self.pic_presets = ChipGroup([("Original", "orig"), ("Vivid", "vivid"), ("Bright", "bright"),
                                      ("Cinema", "cinema"), ("Soft", "soft"), ("Mono", "mono")], cols=3)
        self.pic_presets.picked.connect(self._pic_preset)
        self.pic_presets.select("orig")
        lay.addWidget(self.pic_presets)
        self.adj = {}
        for key, label, lo, hi, default in (("brightness", "Brightness", 0, 200, 100),
                                            ("contrast", "Contrast", 0, 200, 100),
                                            ("saturation", "Saturation", 0, 200, 100),
                                            ("gamma", "Gamma", 50, 150, 100),
                                            ("hue", "Hue", -180, 180, 0)):
            lay.addWidget(QLabel(label))
            s = ValueSlider(lo, hi, 1, default, (lambda v: f"{v}°") if key == "hue" else (lambda v: f"{v}%"), reset=default)
            s.changed.connect(self._adjust_changed)
            self.adj[key] = s
            lay.addWidget(s)

        lay.addWidget(section("Sharpen"))
        # 0 to 1.5 in steps of 0.05 (#36): VLC's sharpen strength changes a lot per step
        self.sharpen = ValueSlider(0, 30, 1, 0, lambda v: "Off" if v == 0 else f"{v / 20:.2f}", reset=0)
        self._sharpen_timer = QTimer(self)
        self._sharpen_timer.setSingleShot(True)
        self._sharpen_timer.setInterval(700)
        self._sharpen_timer.timeout.connect(self._apply_sharpen)
        self.sharpen.changed.connect(lambda _v: self._sharpen_timer.start())
        lay.addWidget(self.sharpen)
        lay.addWidget(muted("Makes soft or low-resolution video look crisper. Changing it restarts the video at the same spot."))

        lay.addWidget(section("Rotate and flip"))
        self.transform = ChipGroup([("Normal", ""), ("90°", "90"), ("180°", "180"), ("270°", "270"),
                                    ("Flip H", "hflip"), ("Flip V", "vflip")], cols=3)
        self.transform.picked.connect(self._set_transform)
        self.transform.select("")
        lay.addWidget(self.transform)
        lay.addWidget(muted("Rotating restarts the video at the same spot."))

        lay.addWidget(section("Deinterlace"))
        self.deint = QComboBox()
        for label, v in (("Off", ""), ("Yadif (good)", "yadif"), ("Yadif 2x (smooth)", "yadif2x"),
                         ("Blend", "blend"), ("Bob", "bob"), ("Linear", "linear")):
            self.deint.addItem(label, v)
        self.deint.activated.connect(lambda i: self.engine.set_deinterlace(self.deint.itemData(i)))
        lay.addWidget(self.deint)

        snap = QPushButton("Take a snapshot")
        snap.setIcon(icon("snapshot", theme.TEXT, 14))
        snap.clicked.connect(lambda: self.win.do("snapshot", key=False))
        lay.addWidget(snap)
        lay.addStretch(1)

    _PIC = {
        "orig": None,
        "vivid": {"brightness": 100, "contrast": 112, "saturation": 140, "gamma": 100, "hue": 0},
        "bright": {"brightness": 118, "contrast": 100, "saturation": 105, "gamma": 120, "hue": 0},
        "cinema": {"brightness": 96, "contrast": 120, "saturation": 92, "gamma": 90, "hue": 0},
        "soft": {"brightness": 104, "contrast": 88, "saturation": 90, "gamma": 105, "hue": 0},
        "mono": {"brightness": 100, "contrast": 110, "saturation": 0, "gamma": 100, "hue": 0},
    }

    def _pic_preset(self, key):
        vals = self._PIC[key] or {"brightness": 100, "contrast": 100, "saturation": 100, "gamma": 100, "hue": 0}
        for k, s in self.adj.items():
            s.set_value(vals[k])
        self._adjust_changed(None, from_preset=key == "orig")
        self.win.toast(f"Picture: {key.title() if key != 'orig' else 'Original'}")

    def _adjust_changed(self, _v=None, from_preset=False):
        vals = {k: s.value() for k, s in self.adj.items()}
        if from_preset or vals == {"brightness": 100, "contrast": 100, "saturation": 100, "gamma": 100, "hue": 0}:
            self.engine.set_adjust(None)
            return
        self.engine.set_adjust({"brightness": vals["brightness"] / 100, "contrast": vals["contrast"] / 100,
                                "saturation": vals["saturation"] / 100, "gamma": vals["gamma"] / 100,
                                "hue": float(vals["hue"])})

    def _apply_sharpen(self):
        v = self.sharpen.value() / 20
        if abs(v - self.engine.sharpen) < 0.01:
            return
        self.engine.sharpen = v
        self.engine.rebuild()
        self.win.toast("Sharpen: off" if v == 0 else f"Sharpen: {v:.2f}")

    def _set_transform(self, v):
        self.engine.transform = v
        self.engine.rebuild()
        self.win.toast("Rotation: " + {"": "Normal", "hflip": "Flipped", "vflip": "Flipped vertically"}.get(v, f"{v}°"))

    # ================================================================ playback
    def _build_playback(self):
        page, lay = scroll_page()
        self.tabs.addTab(page, "Playback")
        lay.addWidget(section("Speed"))
        self.speed = ValueSlider(25, 400, 5, 100, lambda v: f"{v / 100:g}x", reset=100)
        self.speed.changed.connect(lambda v: self.win.set_rate(v / 100, from_ui=True))
        lay.addWidget(self.speed)
        self.speed_chips = ChipGroup([("0.5x", 50), ("0.75x", 75), ("1x", 100), ("1.25x", 125), ("1.5x", 150), ("2x", 200)], cols=3)
        self.speed_chips.picked.connect(lambda v: self.win.set_rate(v / 100))
        lay.addWidget(self.speed_chips)

        lay.addWidget(section("Sleep timer"))
        self.sleep = ChipGroup([("Off", 0), ("15 min", 15), ("30 min", 30), ("45 min", 45), ("1 hour", 60),
                                ("End of file", -1)], cols=3)
        self.sleep.picked.connect(self.win.set_sleep_timer)
        self.sleep.select(0)
        lay.addWidget(self.sleep)
        self.sleep_label = muted("")
        lay.addWidget(self.sleep_label)

        lay.addWidget(section("When a file ends"))
        self.binge = QCheckBox("Play the next file in the folder automatically")
        self.binge.setChecked(bool(self.store.setting("binge")))
        self.binge.toggled.connect(lambda on: self.store.set_setting("binge", on))
        lay.addWidget(self.binge)
        self.repeat = ChipGroup([("No repeat", "off"), ("Queue", "all"), ("This file", "one")], cols=3)
        self.repeat.picked.connect(self.win.set_repeat)
        self.repeat.select("off")
        lay.addWidget(self.repeat)

        lay.addWidget(section("Media info"))
        self.meta = QLabel("Nothing playing")
        self.meta.setWordWrap(True)
        self.meta.setMinimumWidth(10)
        from PySide6.QtWidgets import QSizePolicy
        self.meta.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.meta.setStyleSheet(f"color: {theme.MUTED}; line-height: 150%;")
        lay.addWidget(self.meta)
        lay.addStretch(1)

    def set_speed_ui(self, rate):
        self.speed.set_value(int(round(rate * 100)))
        self.speed_chips.select(int(round(rate * 100)))

    def refresh_meta(self):
        e = self.engine
        if not e.current:
            self.meta.setText("Nothing playing")
            return
        m = e.meta()
        w, h = e.video_size()
        rows = []
        for k, label in (("title", "Title"), ("artist", "Artist"), ("album", "Album"), ("genre", "Genre"),
                         ("date", "Year"), ("now_playing", "Now playing")):
            if m.get(k):
                rows.append(f"<b style='color:{theme.TEXT}'>{label}</b>&nbsp;&nbsp;{m[k]}")
        if w and h:
            rows.append(f"<b style='color:{theme.TEXT}'>Resolution</b>&nbsp;&nbsp;{w} × {h}")
        rows.append(f"<b style='color:{theme.TEXT}'>Length</b>&nbsp;&nbsp;{fmt_time(e.length())}")
        loc = e.current.replace("\\", "\\\u200b").replace("/", "/\u200b")
        rows.append(f"<b style='color:{theme.TEXT}'>Location</b>&nbsp;&nbsp;{loc}")
        self.meta.setText("<br>".join(rows))

    # ================================================================ bookmarks
    def _build_bookmarks(self):
        page, lay = scroll_page()
        self.tabs.addTab(page, "Bookmarks")
        add = QPushButton("Add bookmark here   Ctrl+B")
        add.setObjectName("Primary")
        add.setIcon(icon("bookmark_add", "#111111", 14))
        add.clicked.connect(lambda: self.win.do("bookmark", key=False))
        lay.addWidget(add)
        lay.addWidget(muted("Click to jump. Double-click to rename."))
        self.bm_list = QListWidget()
        self.bm_list.setObjectName("InsetList")
        self.bm_list.setSizeAdjustPolicy(QListWidget.AdjustToContents)
        self.bm_list.setMinimumHeight(44)
        self.bm_list.setMaximumHeight(260)
        self.bm_list.itemClicked.connect(lambda it: self.engine.seek(it.data(Qt.UserRole)))
        self.bm_list.itemDoubleClicked.connect(self._rename_bookmark)
        self.bm_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.bm_list.customContextMenuRequested.connect(self._bm_menu)
        lay.addWidget(self.bm_list)
        lay.addWidget(section("Chapters"))
        self.ch_list = QListWidget()
        self.ch_list.setObjectName("InsetList")
        self.ch_list.setSizeAdjustPolicy(QListWidget.AdjustToContents)
        self.ch_list.setMinimumHeight(44)
        self.ch_list.setMaximumHeight(320)
        self.ch_list.itemClicked.connect(self._chapter_clicked)
        lay.addWidget(self.ch_list)
        lay.addStretch(1)

    def refresh_bookmarks(self):
        self.bm_list.clear()
        path = self.engine.current
        items = self.store.bookmarks(path) if path else []
        for b in items:
            it = QListWidgetItem(icon("bookmark", theme.accent(), 16), f"{fmt_time(b['t'])}    {b['name']}")
            it.setData(Qt.UserRole, b["t"])
            self.bm_list.addItem(it)
        if not items:
            it = QListWidgetItem("No bookmarks yet")
            it.setFlags(Qt.NoItemFlags)
            self.bm_list.addItem(it)
        self.win.bottom.seek.markers = [b["t"] for b in items]
        self.win.bottom.seek.update()

    def _rename_bookmark(self, it):
        if it.data(Qt.UserRole) is None:
            return
        path = self.engine.current
        items = self.store.bookmarks(path)
        row = self.bm_list.row(it)
        if row >= len(items):
            return
        name, ok = QInputDialog.getText(self, "Rename bookmark", "Name", text=items[row]["name"])
        if ok and name.strip():
            items[row]["name"] = name.strip()
            self.store.set_bookmarks(path, items)
            self.refresh_bookmarks()

    def _bm_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        it = self.bm_list.itemAt(pos)
        if not it or it.data(Qt.UserRole) is None:
            return
        m = QMenu(self)
        m.addAction("Rename", lambda: self._rename_bookmark(it))
        m.addAction("Delete", lambda: self._delete_bookmark(self.bm_list.row(it)))
        m.exec(self.bm_list.mapToGlobal(pos))

    def _delete_bookmark(self, row):
        path = self.engine.current
        items = self.store.bookmarks(path)
        if 0 <= row < len(items):
            del items[row]
            self.store.set_bookmarks(path, items)
            self.refresh_bookmarks()

    def _chapter_clicked(self, it):
        idx, start = it.data(Qt.UserRole)
        if start >= 0:
            self.engine.seek(start)
        else:
            self.engine.set_chapter(idx)

    def refresh_chapters(self):
        self.ch_list.clear()
        chs = self.engine.chapters()
        for idx, name, start in chs:
            label = f"{fmt_time(start)}    {name}" if start >= 0 else name
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, (idx, start))
            self.ch_list.addItem(it)
        if not chs:
            it = QListWidgetItem("No chapters in this file")
            it.setFlags(Qt.NoItemFlags)
            self.ch_list.addItem(it)
        self.win.bottom.seek.chapters = [s for _, _, s in chs if s > 0]
        self.win.bottom.seek.update()

    # ================================================================ shared
    def on_media_changed(self):
        self.refresh_bookmarks()
        self.refresh_tracks()
        self.refresh_presets()
        self.set_sub_delay_ui(self.engine.live["sub_delay"])
        self.audio_delay.set_value(self.engine.live["audio_delay"])
        self.load_cues()

    def load_cues(self):
        subs = self.engine.extra_subs
        path = subs[-1] if subs else None
        cur = self.engine.current
        if not path and cur and not is_url(cur):
            # VLC loads same-name subtitle files by itself; show those too
            path = match_subtitle(cur, find_subtitle_candidates(cur), "starts")
        if path and path != self._cues_path:
            self.sub_timeline.set_cues(parse_subtitles(path))
        elif not path:
            self.sub_timeline.set_cues([])
        self._cues_path = path

    def refresh_tracks(self):
        def fill(combo, items, current):
            combo.blockSignals(True)
            combo.clear()
            for tid, name in items:
                combo.addItem(name or f"Track {tid}", tid)
            i = combo.findData(current)
            if i >= 0:
                combo.setCurrentIndex(i)
            if not items:
                combo.addItem("None available", -1)
            combo.blockSignals(False)
        fill(self.sub_combo, self.engine.sub_tracks(), self.engine.current_sub())
        fill(self.audio_combo, self.engine.audio_tracks(), self.engine.current_audio())
        fill(self.video_combo, self.engine.video_tracks(), self.engine.current_video())
        devs = self.engine.audio_devices()
        cur = self.engine.current_device()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for dev, desc in devs:
            self.device_combo.addItem(desc or dev or "Default", dev)
        i = self.device_combo.findData(cur)
        if i >= 0:
            self.device_combo.setCurrentIndex(i)
        if not devs:
            self.device_combo.addItem("Default output", "")
        self.device_combo.blockSignals(False)
        self.refresh_chapters()
        self.refresh_meta()
        self.load_cues()

    def tick(self):
        """Called a few times per second while the sidebar is open."""
        if self.tabs.currentIndex() == 0:
            self.sub_timeline.set_state(self.engine.time(), self.engine.live["sub_delay"])

    # ---------------------------------------------------------------- presets
    def refresh_presets(self):
        names = sorted(self.store.data["presets"].keys())
        folder = self.win.current_folder()
        active, _ = self.store.preset_for_folder(folder) if folder else (None, None)
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("No preset", "")
        for n in names:
            self.preset_combo.addItem(n, n)
        i = self.preset_combo.findData(active or "")
        self.preset_combo.setCurrentIndex(max(0, i))
        self.preset_combo.blockSignals(False)

    def current_settings(self) -> dict:
        def track_name(items, cur):
            for tid, name in items:
                if tid == cur:
                    return name
            return ""
        e = self.engine
        return {
            "sub_delay": e.live["sub_delay"],
            "audio_delay": e.live["audio_delay"],
            "rate": e.live["rate"],
            "eq": e.live["eq"],
            "eq_custom": e.live["eq_custom"] if e.live["eq"] == CUSTOM_EQ else None,
            "aspect": e.live["aspect"],
            "crop": e.live["crop"],
            "zoom": e.live["zoom"],
            "adjust": e.live["adjust"],
            "deinterlace": e.live["deinterlace"],
            "sharpen": e.sharpen,
            "sub_style": self.sub_style_from_ui(),
            "sub_track": "off" if e.current_sub() == -1 else track_name(e.sub_tracks(), e.current_sub()),
            "audio_track": track_name(e.audio_tracks(), e.current_audio()),
        }

    def save_preset(self):
        folder = self.win.current_folder()
        suggestion = self.preset_combo.currentData() or (os.path.basename(folder) if folder else "My preset")
        name, ok = QInputDialog.getText(self, "Save preset",
                                        "Name (it will be used for every file in this folder):", text=suggestion)
        if not ok or not name.strip():
            return
        name = name.strip()
        self.store.data["presets"][name] = self.current_settings()
        if folder:
            self.store.data["folder_preset"][folder] = name
        self.store.save("presets")
        self.refresh_presets()
        self.win.toast(f"Preset “{name}” saved for this show")

    def delete_preset(self):
        name = self.preset_combo.currentData()
        if not name:
            return
        if QMessageBox.question(self, "Delete preset", f"Delete the preset “{name}”?") != QMessageBox.Yes:
            return
        self.store.data["presets"].pop(name, None)
        for f, n in list(self.store.data["folder_preset"].items()):
            if n == name:
                del self.store.data["folder_preset"][f]
        self.store.save("presets")
        self.refresh_presets()

    def _preset_picked(self, i):
        name = self.preset_combo.itemData(i)
        folder = self.win.current_folder()
        if folder:
            if name:
                self.store.data["folder_preset"][folder] = name
            else:
                self.store.data["folder_preset"].pop(folder, None)
            self.store.save("presets")
        if name:
            self.win.apply_preset(self.store.data["presets"].get(name, {}), live=True)
            self.win.toast(f"Preset: {name}")

    def sync_from_engine(self):
        """Reflect engine.live in the controls (after a preset is applied)."""
        L = self.engine.live
        self.set_sub_delay_ui(L["sub_delay"])
        self.audio_delay.set_value(L["audio_delay"])
        self.set_speed_ui(L["rate"])
        self.eq.select(L["eq"])
        self.eq_custom.setVisible(L["eq"] == CUSTOM_EQ)
        if L["eq"] == CUSTOM_EQ:
            self.eq_custom.set_curve(self.engine.clean_curve(L.get("eq_custom")) or self.engine.eq_preset_curve(-1))
        self.aspect.select(L["aspect"])
        self.crop.select(L["crop"])
        self.zoom.select(L["zoom"])
        i = self.deint.findData(L["deinterlace"])
        self.deint.setCurrentIndex(max(0, i))
        adj = L["adjust"]
        vals = ({"brightness": 100, "contrast": 100, "saturation": 100, "gamma": 100, "hue": 0} if not adj else
                {"brightness": round(adj["brightness"] * 100), "contrast": round(adj["contrast"] * 100),
                 "saturation": round(adj["saturation"] * 100), "gamma": round(adj["gamma"] * 100),
                 "hue": round(adj["hue"])})
        for k, s in self.adj.items():
            s.set_value(vals[k])
        self.load_sub_style(self.engine.sub_style)
        self.transform.select(self.engine.transform)
        self.sharpen.set_value(round(self.engine.sharpen * 20))
