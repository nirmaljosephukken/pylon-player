"""1.8.0: synced lyrics in the music view.

A .lrc file with the same name as the song (any letter case) shows next to the cover: the line being sung is
bright and kept in the middle, clicking a line jumps there, and the wheel scrolls before the lyrics follow the
song again. Several time tags on one line, [offset:], word timings and three-digit fractions are understood;
lyrics without times are shown as plain lines. Preferences > Playback can turn them off.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QCheckBox
from app import engine
engine.vlc = None
from app.home import LyricsView
from app.store import Store
from app.util import find_lyrics, lyric_index, parse_lrc, read_lyrics
from app.window import MainWindow

app = QApplication.instance() or QApplication([])

LRC = """[ti:Song]
[ar:Band]
[offset:+200]
[00:01.50][00:20.00]Chorus <00:01.80>line
[00:05.123]Second line
[00:09]Third line
[00:12.5]
"""


def wait(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Parsing(unittest.TestCase):
    def test_times_offset_and_repeats(self):
        lines = parse_lrc(LRC)
        self.assertEqual(lines, [(1300, "Chorus line"), (4923, "Second line"), (8800, "Third line"),
                                 (12300, ""), (19800, "Chorus line")])

    def test_which_line_is_sung(self):
        lines = parse_lrc(LRC)
        self.assertEqual(lyric_index(lines, 0), -1)
        self.assertEqual(lyric_index(lines, 1300), 0)
        self.assertEqual(lyric_index(lines, 6000), 1)
        self.assertEqual(lyric_index(lines, 999_999), 4)
        self.assertEqual(lyric_index([], 5), -1)

    def test_untimed_lyrics(self):
        self.assertEqual(parse_lrc("[ar:Band]\nFirst\n\nSecond\n"), [(None, "First"), (None, "Second")])
        self.assertEqual(lyric_index(parse_lrc("a\nb"), 5000), -1)

    def test_found_next_to_the_song_in_any_case(self):
        with tempfile.TemporaryDirectory() as d:
            song = os.path.join(d, "01 Song.mp3")
            Path(song).write_bytes(b"")
            self.assertEqual(find_lyrics(song), "")
            Path(d, "01 song.LRC").write_text(LRC, encoding="utf-8-sig")
            self.assertEqual(find_lyrics(song), os.path.join(d, "01 song.LRC"))
            self.assertEqual(read_lyrics(song)[0], (1300, "Chorus line"))
        self.assertEqual(find_lyrics("http://radio.test/live"), "")


class View(unittest.TestCase):
    def setUp(self):
        self.v = LyricsView()
        self.v.resize(300, 400)
        self.v.show()
        self.v.set_lines(parse_lrc(LRC))
        wait(30)
        self.jumps = []
        self.v.jump.connect(self.jumps.append)

    def tearDown(self):
        self.v.close()

    def test_current_line_in_the_middle(self):
        self.v.set_time(6000)
        wait(400)                                   # after the slide
        self.assertEqual(self.v.current, 1)
        self.assertEqual(self.v.row_at(self.v.height() / 2), 1)
        self.assertEqual(self.v.row_at(self.v.height() / 2 + self.v.row_height()), 2)

    def test_click_a_line_to_jump(self):
        self.v.set_time(6000)
        wait(400)
        y = self.v.height() / 2 + self.v.row_height()
        pos = QPointF(150, y)
        app.sendEvent(self.v, QMouseEvent(QEvent.MouseButtonPress, pos, self.v.mapToGlobal(pos), Qt.LeftButton,
                                          Qt.LeftButton, Qt.NoModifier))
        self.assertEqual(self.jumps, [8800])

    def test_wheel_scrolls_then_follows_again(self):
        self.v.FOLLOW_AGAIN_MS = 200
        self.v.set_time(6000)
        wait(400)
        pos = QPointF(150, 200)
        ev = QWheelEvent(pos, self.v.mapToGlobal(pos), QPoint(), QPoint(0, -240), Qt.NoButton, Qt.NoModifier,
                         Qt.NoScrollPhase, False)
        app.sendEvent(self.v, ev)
        self.assertEqual(self.v._y, 3.0)
        self.v.set_time(9000)                       # sung on, but you're reading further down
        self.assertEqual(self.v._y, 3.0)
        wait(700)
        self.assertEqual(self.v._y, 2.0)            # following the song again

    def test_untimed_lyrics_are_not_clickable(self):
        self.v.set_lines(parse_lrc("a\nb\nc"))
        self.v.set_time(5000)
        pos = QPointF(150, 200)
        app.sendEvent(self.v, QMouseEvent(QEvent.MouseButtonPress, pos, self.v.mapToGlobal(pos), Qt.LeftButton,
                                          Qt.LeftButton, Qt.NoModifier))
        self.assertEqual(self.jumps, [])
        self.assertEqual(self.v.current, -1)


class MusicView(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.resize(900, 600)
        self.win.show()
        wait(100)
        self.song = os.path.join(self.temp.name, "Song.mp3")
        Path(self.song).write_bytes(b"")
        Path(self.temp.name, "Song.lrc").write_text(LRC, encoding="utf-8")
        self.plain = os.path.join(self.temp.name, "Other.mp3")
        Path(self.plain).write_bytes(b"")

    def tearDown(self):
        self.win.engine.current = None
        self.store._save_timer.stop()
        self.win.close()
        self.temp.cleanup()

    def test_shown_with_a_song_that_has_them(self):
        np = self.win.now_playing
        np.load(self.song, {})
        self.assertTrue(np.lyrics.isVisibleTo(np))
        np.load(self.plain, {})
        self.assertFalse(np.lyrics.isVisibleTo(np))

    def test_follows_the_song_and_click_seeks(self):
        w, np = self.win, self.win.now_playing
        seeks = []
        w.engine.current = self.song
        w.engine.seek = seeks.append
        w.stage.setCurrentWidget(np)
        np.load(self.song, {})
        wait(30)
        w.engine.time = lambda: 6000
        w._time_tick()
        self.assertEqual(np.lyrics.current, 1)
        np.lyrics.jump.emit(8800)
        self.assertEqual(seeks, [8800])

    def test_setting_turns_them_off(self):
        from app.dialogs import PreferencesDialog
        np = self.win.now_playing
        np.load(self.song, {"title": "Song", "artist": "Band"})
        dlg = PreferencesDialog(self.win)
        box = dlg.findChild(QCheckBox, "lyrics")
        box.setChecked(False)
        self.assertFalse(np.lyrics.isVisibleTo(np))
        self.assertEqual(np.sub.text(), "Band")             # the rest of the page is unchanged
        box.setChecked(True)
        self.assertTrue(np.lyrics.isVisibleTo(np))
        dlg.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
