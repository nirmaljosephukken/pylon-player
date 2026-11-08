"""Main window: the library on the left and the settings sidebar on the right.

Each panel lives in a PanelSlot, a holder that opens and closes by changing its own width while the
panel inside keeps its full width, so the panel slides in from its edge instead of popping in (#54,
#63). The slot sits in the window's layout and the video makes room for it.

In full screen with Super Resolution on, the slots float over the video instead (#42): Super
Resolution only shows a picture while VLC's video covers the whole screen, so the video keeps the
whole screen and the panel covers part of it. A floating slot is a native child window, so it can sit
above the native window VLC draws into."""
from PySide6.QtCore import QEasingCurve, QRect, Qt, QVariantAnimation
from PySide6.QtWidgets import QWidget

PANEL_SLIDE_MS = 170


class PanelSlot(QWidget):
    def __init__(self, panel: QWidget, side: str, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.side = side                  # "left" or "right": the edge the panel slides from
        self.full = panel.WIDTH
        self.is_open = False
        self.floating = False
        self._float_rect = QRect()        # the area over the video a floating slot sits in
        panel.setParent(self)
        panel.hide()
        self.setFixedWidth(0)
        self.hide()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(PANEL_SLIDE_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(lambda v: self._set_width(int(v)))
        self._anim.finished.connect(self._settled)

    def shown_width(self) -> int:
        """How much room the slot takes now (its final width once a slide ends)."""
        return self.full if self.is_open else 0

    def set_open(self, on: bool, animate: bool):
        if on == self.is_open and self._anim.state() != QVariantAnimation.Running:
            return
        self.is_open = on
        self._anim.stop()
        if on:
            self.panel.show()
            self.show()
            if self.floating:
                self.raise_()
        start = self.width() if self.isVisible() else 0
        end = self.full if on else 0
        if not animate or start == end:
            self._set_width(end)
            self._settled()
            return
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.start()

    def finish(self):
        """Jump to the end of a slide (used before the layout changes under it)."""
        if self._anim.state() == QVariantAnimation.Running:
            self._anim.stop()
            self._set_width(self.full if self.is_open else 0)
            self._settled()

    def _set_width(self, w: int):
        w = max(0, min(self.full, w))
        if self.floating:
            r = self._float_rect
            x = r.left() if self.side == "left" else r.right() + 1 - w
            self.setGeometry(x, r.top(), w, r.height())
        else:
            self.setFixedWidth(w)
        self._place_panel()

    def _settled(self):
        if not self.is_open:
            self.hide()
            self.panel.hide()
        if hasattr(self.window(), "_panel_settled"):
            self.window()._panel_settled(self)

    def set_floating(self, on: bool, rect: QRect | None = None):
        if on:
            if not self.floating:
                self.setAttribute(Qt.WA_NativeWindow, True)       # above VLC's native window
                self.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
                self.setMinimumWidth(0)
                self.setMaximumWidth(16777215)
            self.floating = True
            self._float_rect = QRect(rect) if rect is not None else self._float_rect
            self._set_width(self.width() if self._anim.state() == QVariantAnimation.Running else self.shown_width())
            if self.isVisible():
                self.raise_()
        elif self.floating:
            self.floating = False
            self._set_width(self.shown_width())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_panel()

    def _place_panel(self):
        # The panel keeps its full width and slides: the library from the left edge, the settings from the right.
        x = self.width() - self.full if self.side == "left" else 0
        self.panel.setGeometry(x, 0, self.full, self.height())


class PanelsMixin:
    def _make_panel_slots(self):
        self.lib_slot = PanelSlot(self.library, "left")
        self.side_slot = PanelSlot(self.sidebar, "right")
        self._panels_floating = False

    def _animate_panels(self) -> bool:
        if not bool(self.store.setting("animate_panels")) or not self.isVisible() or self._pip:
            return False
        # Each step resizes the video; with Super Resolution on that redraws the picture every time.
        return self._panels_floating or not self._vsr_active()

    def toggle_library(self, on=None):
        on = (not self.lib_slot.is_open) if on is None else on
        if self._pip and on:
            return
        self.lib_slot.set_open(on, self._animate_panels())
        self._update_panel_minimum()
        self._vsr_resized()           # the picture may not resize if the panel only covers it
        self.top.btn_library.setChecked(on)
        if on:
            self.library.refresh_library()
            self.library.refresh_queue()

    def toggle_queue(self, on=None):
        on = (not self.lib_slot.is_open) if on is None else on
        self.toggle_library(on)
        self.bottom.btn_queue.setChecked(on)

    def toggle_sidebar(self, on=None):
        on = (not self.side_slot.is_open) if on is None else on
        if self._pip and on:
            return
        self.side_slot.set_open(on, self._animate_panels())
        self._update_panel_minimum()
        self._vsr_resized()
        self.bottom.btn_tune.setChecked(on)
        if on:
            self.sidebar.refresh_tracks()

    def toggle_panels(self):
        """Library and settings together (#34): hide both if either is open, else show both."""
        on = not self.lib_slot.is_open and not self.side_slot.is_open
        if self._pip and on:
            return
        self.toggle_library(on)
        if not on:
            self.bottom.btn_queue.setChecked(False)
        self.toggle_sidebar(on)

    def open_sidebar_tab(self, tab):
        """Open the settings panel on a tab: a name from Sidebar.TABS ("subtitles", "audio"...) or its index."""
        self.toggle_sidebar(True)
        self.sidebar.tabs.setCurrentIndex(self.sidebar.TABS.index(tab) if isinstance(tab, str) else tab)

    def _update_panel_minimum(self):
        """Keep both side panels and the compact player inside the window."""
        panel_width = 0 if self._panels_floating else self.lib_slot.shown_width() + self.side_slot.shown_width()
        self.setMinimumWidth(max(640, panel_width + self.stage.minimumWidth()))
        self._overlay_geo = None

    def _panel_settled(self, _slot):
        self._overlay_geo = None

    # ---------------------------------------------------------------- floating over the video (#42)
    def _want_floating_panels(self) -> bool:
        return self.isFullScreen() and self._vsr_on() and not self._pip

    def _sync_panel_mode(self):
        """Float the panels over the video in full screen with Super Resolution on, else lay them out."""
        want = self._want_floating_panels()
        if want == self._panels_floating:
            if want:
                self._place_floating_panels()
            return
        self._panels_floating = want
        lay = self.centralWidget().layout()
        for slot in (self.lib_slot, self.side_slot):
            slot.finish()
        if want:
            for slot in (self.lib_slot, self.side_slot):
                lay.removeWidget(slot)
            self._place_floating_panels()
        else:
            for slot in (self.lib_slot, self.side_slot):
                slot.set_floating(False)
            lay.insertWidget(0, self.lib_slot)
            lay.addWidget(self.side_slot)
        self._update_panel_minimum()

    def _place_floating_panels(self):
        if not self._panels_floating:
            return
        r = self.middle.geometry()
        for slot in (self.lib_slot, self.side_slot):
            slot.set_floating(True, r)

    def _panel_cover(self) -> tuple[int, int]:
        """(left, right) pixels of the stage that floating panels cover, so the bars can stay clear of them."""
        if not self._panels_floating:
            return 0, 0
        return self.lib_slot.shown_width(), self.side_slot.shown_width()
