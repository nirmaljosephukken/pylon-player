"""New episodes join their show in name order, in the queue and in playlists (#57),
and the queue and playlists can be sorted by name on demand."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc = None
from app.store import Store
from app.util import merge_in_name_order
from app.window import MainWindow

app = QApplication.instance() or QApplication([])

# made absolute the way Pylon stores paths, so the test also passes on Windows ("E:\\media\\Show")
SHOW = os.path.abspath("/media/Show")
OTHER = os.path.abspath("/media/Other")


def ep(n, folder=SHOW, name="Show S01E{:02d}.mkv"):
    return os.path.join(folder, name.format(n))


def names(paths):
    return [Path(p).name for p in paths]


class Merge(unittest.TestCase):
    def test_reported_case_slots_two_and_three_after_one(self):
        out = merge_in_name_order([ep(1), ep(5), ep(6), ep(7)], [ep(2), ep(3)])
        self.assertEqual(out, [ep(i) for i in (1, 2, 3, 5, 6, 7)])

    def test_episode_ten_sorts_after_nine_not_after_one(self):
        out = merge_in_name_order([ep(1), ep(9), ep(11)], [ep(10)])
        self.assertEqual(out, [ep(1), ep(9), ep(10), ep(11)])

    def test_new_folder_goes_to_the_end(self):
        out = merge_in_name_order([ep(1), ep(2)], [ep(1, OTHER)])
        self.assertEqual(out, [ep(1), ep(2), ep(1, OTHER)])

    def test_only_its_own_show_is_touched(self):
        start = [ep(1), ep(1, OTHER), ep(4), ep(2, OTHER)]
        out = merge_in_name_order(start, [ep(3)])
        self.assertEqual(out, [ep(1), ep(3), ep(1, OTHER), ep(4), ep(2, OTHER)])   # right after episode 1

    def test_earliest_episode_goes_before_the_first(self):
        out = merge_in_name_order([ep(2), ep(3)], [ep(1)])
        self.assertEqual(out, [ep(1), ep(2), ep(3)])

    def test_an_order_the_user_chose_is_left_alone(self):
        hand = [ep(3), ep(1), ep(2)]
        out = merge_in_name_order(hand, [ep(4)])
        self.assertEqual(out, hand + [ep(4)])

    def test_songs_go_at_the_end(self):
        songs = ["/music/Album/b.mp3", "/music/Album/c.mp3"]
        self.assertEqual(merge_in_name_order(songs, ["/music/Album/a.mp3"]), songs + ["/music/Album/a.mp3"])

    def test_streams_go_at_the_end(self):
        out = merge_in_name_order([ep(1), ep(3)], ["https://example.com/live.m3u8"])
        self.assertEqual(out[-1], "https://example.com/live.m3u8")


class Window(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "data.json"))
        self.store.set_setting("onboarded", True)
        with patch.object(MainWindow, "_welcome", lambda self: None), patch.object(MainWindow, "_vlc_missing"):
            self.win = MainWindow(self.store)
        self.win._vlc_missing = lambda: None
        self.win.play_path = lambda path, **kw: setattr(self.win.engine, "current", path)

    def tearDown(self):
        self.win.close()
        self.temp.cleanup()

    def queue(self):
        return names(q["path"] for q in self.win.queue)

    def test_add_to_queue_slots_episodes_in_and_keeps_playing(self):
        w = self.win
        w.set_queue([{"path": ep(i)} for i in (1, 5, 6, 7)], 0)
        w.enqueue([ep(2), ep(3)])
        self.assertEqual(self.queue(), names(ep(i) for i in (1, 2, 3, 5, 6, 7)))
        self.assertEqual(w.qindex, 0)
        self.assertEqual(w.queue[w.qindex]["path"], ep(1))

    def test_playing_item_is_tracked_when_something_lands_before_it(self):
        w = self.win
        w.set_queue([{"path": ep(i)} for i in (2, 3, 4)], 1)
        w.enqueue([ep(1)])
        self.assertEqual(w.queue[w.qindex]["path"], ep(3))

    def test_play_next_still_goes_right_after_what_is_playing(self):
        w = self.win
        w.set_queue([{"path": ep(i)} for i in (1, 2, 3)], 0)
        w.enqueue([ep(9)], play_next=True)
        self.assertEqual(self.queue()[1], Path(ep(9)).name)

    def test_shuffle_off_puts_new_episode_in_its_place(self):
        w = self.win
        w.set_queue([{"path": ep(i)} for i in (1, 2, 4, 5)], 0)
        w.set_queue_mode("shuffle", announce=False)
        w.enqueue([ep(3)])
        w.set_queue_mode("next", announce=False)
        self.assertEqual(self.queue(), names(ep(i) for i in (1, 2, 3, 4, 5)))

    def test_sort_queue_by_name(self):
        w = self.win
        w.set_queue([{"path": ep(i)} for i in (1, 5, 6, 7, 2, 3)], 3)
        w.sort_queue_by_name()
        self.assertEqual(self.queue(), names(ep(i) for i in (1, 2, 3, 5, 6, 7)))
        self.assertEqual(w.queue[w.qindex]["path"], ep(7))

    def test_sorting_a_shuffled_queue_leaves_shuffle(self):
        w = self.win
        w.set_queue([{"path": ep(i)} for i in range(1, 7)], 0)
        w.set_queue_mode("shuffle", announce=False)
        w.sort_queue_by_name()
        self.assertEqual(w.queue_mode, "next")
        self.assertEqual(self.queue(), names(ep(i) for i in range(1, 7)))

    def test_add_to_playlist_slots_episodes_in(self):
        lib = self.win.library
        self.store.data["playlists"]["Show"] = [ep(i) for i in (1, 5, 6, 7)]
        lib.add_to_playlist("Show", [ep(2), ep(3), ep(1)])     # ep 1 is already there
        self.assertEqual(self.store.data["playlists"]["Show"], [ep(i) for i in (1, 2, 3, 5, 6, 7)])

    def test_sort_playlist_by_name(self):
        lib = self.win.library
        self.store.data["playlists"]["Show"] = [ep(i) for i in (1, 5, 6, 7, 2, 3)]
        lib._pl_sort("Show")
        self.assertEqual(self.store.data["playlists"]["Show"], [ep(i) for i in (1, 2, 3, 5, 6, 7)])


if __name__ == "__main__":
    unittest.main()
