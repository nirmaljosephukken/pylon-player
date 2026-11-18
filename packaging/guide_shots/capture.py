"""Takes the user guide's screenshots (docs/guide/*.webp) from a real Pylon on Linux. The whole routine:

    sudo apt install vlc-plugin-base vlc-plugin-video-output ffmpeg xvfb openbox    # VLC needs its video outputs
    python3 packaging/guide_shots/make_media.py          # once: the made-up shows, film and music under /
    Xvfb :98 -screen 0 2600x2600x24 &  DISPLAY=:98 openbox &
    DISPLAY=:98 python3 packaging/guide_shots/capture.py [shot names...]   # all of them when none are named
    python3 packaging/guide_shots/update_guide.py        # picture sizes and numbered markers in docs/guide.html
    node packaging/build_guide_pdf.js                    # the PDF

Pylon runs at 150% (QT_SCALE_FACTOR=1.5, as on a 150% Windows laptop) in the dark theme with a fresh data folder
seeded below. Marker boxes for the numbered figures go to docs/guide/markers.json.
"""
import json
import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
os.environ["QT_SCALE_FACTOR"] = "1.5"
HOME = tempfile.mkdtemp(prefix="pylon-guide-")
DATA = "/home/you/.local/share"            # shown in Preferences > Privacy, so a plain-looking place
shutil.rmtree(os.path.join(DATA, "pylon"), ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ["XDG_DATA_HOME"] = DATA
os.environ["XDG_CONFIG_HOME"] = os.path.join(HOME, "config")
os.environ["XDG_CACHE_HOME"] = os.path.join(HOME, "cache")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "docs", "guide")

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, QEventLoop  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
app = QApplication(sys.argv[:1])
app.setStyle("Fusion")

from PIL import Image  # noqa: E402
from app import theme  # noqa: E402
from app.store import Store  # noqa: E402

LK = "/Shows/Lighthouse Keepers/Lighthouse.Keepers.S01E0{}.1080p.mkv"
NM = "/Shows/Night Market/Night.Market.S02E0{}.mkv"
PP = "/Movies/Paper Planets (2024)/Paper.Planets.2024.mkv"


def seed(store: Store):
    now = time.time()
    s = store.data["settings"]
    s.update(onboarded=True, check_updates=False, hw_decoding=False, theme="dark", resume="ask",
             remember_history=True, volume=80)
    store.data["library_folders"] = ["/Shows/Lighthouse Keepers", "/Music", "/Shows"]
    pos = {LK.format(1): (3182000, 3182000, True, 30), LK.format(2): (3182000, 3182000, True, 20),
           LK.format(3): (760000, 3182000, False, 1), NM.format(2): (1900000, 2400000, False, 3),
           PP: (5820000, 5820000, True, 2)}
    store.data["positions"] = {k: {"pos": a, "len": b, "watched": w, "t": now - h * 3600}
                               for k, (a, b, w, h) in pos.items()}
    store.data["recent"] = [{"path": p, "t": now - h * 3600}
                            for p, h in ((LK.format(3), 1), (PP, 2), (NM.format(2), 3),
                                         ("http://radio.example/city.m3u8", 5))]
    store.data["playlists"] = {"Lighthouse S1": [LK.format(n) for n in range(1, 7)],
                               "Night Market S2": [NM.format(n) for n in range(1, 5)],
                               "Weekend films": [PP]}
    store.data["streams"] = [{"name": "News 24", "url": "https://tv.example/news/live.m3u8"},
                             {"name": "Free TV", "url": "https://tv.example/free.m3u", "count": 240},
                             {"name": "City radio", "url": "https://radio.example/city.m3u8"}]
    store.save_now()


def settle(ms=400):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents(QEventLoop.AllEvents, 50)
        time.sleep(0.01)


def save(img: Image.Image, name: str):
    img.save(os.path.join(OUT, name + ".webp"), quality=88, method=6)
    print("saved", name, img.size, flush=True)


def qimage_to_pil(qimg):
    qimg = qimg.convertToFormat(qimg.Format.Format_RGBA8888)
    return Image.frombuffer("RGBA", (qimg.width(), qimg.height()), bytes(qimg.constBits()), "raw", "RGBA",
                            qimg.bytesPerLine(), 1).convert("RGB")


def screen_grab(w: QWidget, rect: QRect | None = None) -> Image.Image:
    """What's on screen over w (VLC's video included), at device pixels."""
    rect = rect or w.rect()
    g = QRect(w.mapToGlobal(rect.topLeft()), rect.size())
    pm = QGuiApplication.primaryScreen().grabWindow(0, g.x(), g.y(), g.width(), g.height())
    return qimage_to_pil(pm.toImage())


def widget_grab(w: QWidget) -> Image.Image:
    return qimage_to_pil(w.grab().toImage())


def popup(trigger, name, prep=None, delay=600, crop=None):
    """Open a menu or dialog with trigger(), grab it once it shows (after prep(widget)), and close it."""
    def grab():
        w = QApplication.activePopupWidget() or QApplication.activeModalWidget()
        if w is None:
            print("nothing opened for", name, flush=True)
            return
        if prep:
            prep(w)
            settle(500)
        img = widget_grab(w) if crop is None else crop(w)
        save(img, name)
        w.close()
    QTimer.singleShot(delay, grab)
    trigger()
    settle(300)


def wait_for(cond, secs=20):
    end = time.time() + secs
    while time.time() < end and not cond():
        settle(200)
    return cond()


def gpos(w: QWidget) -> QPoint:
    return w.mapToGlobal(QPoint(0, 0))


def union(ws, origin: QWidget, size) -> list:
    """The box around several widgets, in percent of size, like mark()."""
    ws = [w for w in ws if w is not None and w.isVisible()]
    xs, ys, xe, ye = [], [], [], []
    for w in ws:
        p = gpos(w) - gpos(origin)
        xs.append(p.x()); ys.append(p.y()); xe.append(p.x() + w.width()); ye.append(p.y() + w.height())
    W, H = size
    x, y = min(xs), min(ys)
    return [round(100 * x / W, 2), round(100 * y / H, 2), round(100 * (max(xe) - x) / W, 2),
            round(100 * (max(ye) - y) / H, 2)]


def find(root: QWidget, cls, test):
    return next((w for w in root.findChildren(cls) if w.isVisible() and test(w)), None)


def mark(w: QWidget, origin: QWidget, size) -> list:
    """w's box inside origin (in any window), in percent of size (logical px)."""
    p = gpos(w) - gpos(origin)
    W, H = size
    return [round(100 * p.x() / W, 2), round(100 * p.y() / H, 2), round(100 * w.width() / W, 2),
            round(100 * w.height() / H, 2)]


def main():
    from app.window import MainWindow
    store = Store()
    seed(store)
    theme.set_theme(store.setting("theme"), store.setting("theme_tint"))
    theme.set_accent(store.setting("accent"))
    app.setStyleSheet(theme.stylesheet())
    MainWindow.can_integrate_desktop = lambda self: False      # the menus as on Windows and macOS
    from app.engine import Engine
    Engine.audio_devices = lambda self: [("", "Default"), ("speakers", "Speakers (High Definition Audio)"),
                                         ("headphones", "Headphones (USB Audio)")]   # not the cloud's null device
    win = MainWindow(store)
    win._vlc_missing = lambda: None
    win.resize(1067, 633)
    win.move(40, 40)
    win.show()
    settle(1500)
    wait_for(lambda: len(win.library.music.albums()) >= 5, 30)
    want = set(sys.argv[1:])
    markers = {}
    shots = globals()["SHOTS"]
    for name, fn in shots:
        if want and name not in want:
            continue
        fn(win, markers)
    path = os.path.join(OUT, "markers.json")
    old = json.load(open(path)) if os.path.exists(path) else {}
    old.update(markers)
    with open(path, "w") as f:
        json.dump(old, f, indent=1)
    win.close()
    if not os.environ.get("KEEP_HOME"): shutil.rmtree(HOME, ignore_errors=True)
    else: print("home", HOME)


# ---------------------------------------------------------------- the shots
W0, H0 = 1067, 633           # the window, in logical px (1600 x 950 in the pictures)


def size_win(win, w=W0, h=H0):
    win.resize(w, h)
    settle(700)


def panels_closed(win):
    win.toggle_library(False)
    win.toggle_sidebar(False)
    settle(500)


def playing(win, path=None, at_ms=None, paused=False):
    """The episode the guide plays, stopped on its picture with the subtitle showing."""
    path = path or LK.format(3)
    if win.engine.current != path:
        items = [{"path": LK.format(n)} for n in range(1, 7)] + [{"path": NM.format(n)} for n in range(1, 5)]
        idx = next((i for i, it in enumerate(items) if it["path"] == path), None)
        if idx is None:
            win.play_path(path)
        else:
            win.set_queue(items, idx)
        wait_for(lambda: win.engine.is_playing() and win.engine.length() > 0, 20)
        settle(1500)
    if at_ms is not None:
        win.engine.seek(at_ms)
        settle(800)
    if paused and win.engine.is_playing():
        win.do("play_pause", key=False)
    settle(800)


def show_bars(win):
    for name in ("_poke", "poke"):
        f = getattr(win, name, None)
        if f:
            f(600)
            break
    settle(600)


def shot_home(win, markers):
    win.show_home()
    size_win(win, W0, 1395)
    page = win.centralWidget()
    save(screen_grab(page), "home")
    from PySide6.QtWidgets import QPushButton, QToolButton
    from app.widgets import Card
    size = (page.width(), page.height())
    h = win.home
    m = {"1": find(h, QToolButton, lambda b: b.toolTip().startswith("Library")),
         "7": find(h, QToolButton, lambda b: b.toolTip() == "Menu"),
         "6": find(h, Card, lambda c: True)}
    for key, text in (("2", "Open file"), ("3", "Open folder"), ("4", "Network stream"), ("5", "Add folder to library")):
        m[key] = find(h, QPushButton, lambda b, t=text: b.text() == t)
    markers["home"] = {k: mark(w, page, size) for k, w in m.items() if w is not None}


def shot_player(win, markers):
    win.show_player() if hasattr(win, "show_player") else None
    panels_closed(win)
    size_win(win, W0, 700)
    playing(win)
    resume = win.bottom.resume.isVisible()
    playing(win, at_ms=758000)
    if resume:
        win.bottom.resume.show()          # the guide shows the button as it is when a file opens
    win.set_rate(1.25, osd=False)
    show_bars(win)
    stage = win.centralWidget()
    save(screen_grab(stage), "player")
    t, b = win.top, win.bottom
    size = (stage.width(), stage.height())
    m = {}
    for key, w in (("1", t.btn_library), ("2", t.folder_chip), ("3", t.title), ("4", t.btn_pip), ("5", t.btn_full),
                   ("6", t.btn_menu), ("7", b.btn_prev), ("8", b.btn_play), ("9", b.btn_next), ("10", b.time),
                   ("11", b.resume), ("12", b.speed), ("13", b.btn_subs), ("14", b.btn_audio), ("15", b.btn_queue),
                   ("16", b.btn_mute), ("17", b.cone), ("18", b.btn_tune), ("19", b.seek), ("20", t.btn_close)):
        if w.isVisible():
            m[key] = mark(w, stage, size)
    markers["player"] = m


def shot_panels(win, markers):
    size_win(win, W0, 683)
    playing(win)
    win.library.show_section("library")
    win.library.open_folder("/Shows/Lighthouse Keepers")
    win.toggle_library(True)
    win.open_sidebar_tab("subtitles")
    show_bars(win)
    settle(1200)
    page = win.centralWidget()
    save(screen_grab(page), "panels")
    from PySide6.QtWidgets import QComboBox, QToolButton
    lib, sb = win.library, win.sidebar
    size = (page.width(), page.height())
    qbtns = [b for b in lib.findChildren(QToolButton) if b.isVisible() and b.toolTip() in (
        "Add files to the queue", "Clear queue") or b is getattr(lib, "mode_btn", None)
        or b.toolTip().startswith("Save the queue")]
    sort = find(lib, QComboBox, lambda c: c.currentText() == "Name")
    sort_dir = [b for b in lib.findChildren(QToolButton) if b.isVisible() and sort is not None
                and abs(gpos(b).y() - gpos(sort).y()) < 12]
    pre = [b for b in sb.findChildren(QToolButton) if b.isVisible() and (
        b.toolTip().startswith("Save current settings") or b.toolTip() == "Delete this preset")]
    markers["panels"] = {
        "1": union(list(lib.nav_buttons.values()), page, size),
        "2": union([lib.btn_back, lib.btn_fwd, lib.btn_up, lib.address], page, size),
        "3": union([lib.search, lib.btn_add, sort] + sort_dir, page, size),
        "4": union(qbtns, page, size),
        "5": mark(lib.queue_search, page, size),
        "6": mark(lib.queue, page, size),
        "7": union([sb.preset_combo] + pre, page, size),
        "8": mark(sb.tabs.tabBar(), page, size)}


def lib_shot(win, key, name, height, prep=None):
    size_win(win, W0, 900)
    win.toggle_library(True)
    win.library.show_section(key)
    if prep:
        prep()
    settle(900)
    lib = win.library
    save(screen_grab(lib, QRect(0, 0, lib.width(), height)), name)


def item_menu(lst, row, handler, name):
    it = lst.item(row)
    pos = lst.visualItemRect(it).center()
    lst.setCurrentRow(row)
    popup(lambda: handler(pos), name)


def shot_library(win, markers):
    lib = win.library
    lib_shot(win, "library", "lib_library", 411, lambda: lib.open_folder("/Shows/Lighthouse Keepers"))
    lst = lib.lib_list
    rows = [lst.item(i).text() for i in range(lst.count())]
    folder = next((i for i, t in enumerate(rows) if t.startswith("Subs")), 0)
    item_menu(lst, folder, lib._lib_menu, "menu_library_folder")
    item_menu(lst, min(folder + 3, lst.count() - 1), lib._lib_menu, "menu_library_file")


def shot_music(win, markers):
    lib = win.library
    from PySide6.QtWidgets import QPushButton

    def albums():
        b = next(b for b in lib.findChildren(QPushButton) if b.text() == "Albums" and b.isVisible())
        b.click()
    lib_shot(win, "music", "lib_music", 493, albums)


def shot_recent(win, markers):
    lib = win.library
    lib_shot(win, "recent", "lib_recent", 388)
    item_menu(lib.recent_list, 0, lib._recent_menu, "menu_recent")


def shot_playlists(win, markers):
    lib_shot(win, "playlists", "lib_playlists", 445)


def shot_streams(win, markers):
    lib = win.library
    lib_shot(win, "streams", "lib_streams", 445)
    lst = lib.st_list
    row = next((i for i in range(lst.count()) if "Free TV" in lst.item(i).text()), 0)
    item_menu(lst, row, lib._st_menu, "menu_streams_list")


def shot_queue(win, markers):
    lib = win.library
    size_win(win, W0, 900)
    playing(win)
    win.toggle_library(True)
    settle(900)
    q = lib.queue
    from PySide6.QtWidgets import QLabel
    head = next(w for w in lib.findChildren(QLabel) if w.text().startswith("Queue") and w.isVisible())
    top = head.mapTo(lib, QPoint(0, 0)).y() - 10
    save(screen_grab(lib, QRect(0, top, lib.width(), lib.height() - top)), "lib_queue")
    item_menu(q, 3, lib._queue_menu, "menu_queue")


def side_shot(win, tab, name):
    size_win(win, W0, 1650)
    playing(win)
    win.open_sidebar_tab(tab)
    settle(1200)
    sb = win.sidebar
    page = sb.tabs.currentWidget()
    from PySide6.QtWidgets import QScrollArea
    sc = page if isinstance(page, QScrollArea) else page.findChild(QScrollArea)
    if sc is not None and sc.widget() is not None:
        inner = sc.widget()
        bottom = sc.mapTo(sb, QPoint(0, 0)).y() + inner.sizeHint().height() + 8
    else:
        bottom = sb.height()
    save(screen_grab(sb, QRect(0, 0, sb.width(), min(bottom, sb.height()))), name)


def shot_settings(win, markers):
    for tab in ("subtitles", "audio", "video", "playback", "bookmarks"):
        side_shot(win, tab, "set_" + tab)
    size_win(win)
    win.open_sidebar_tab("subtitles")
    settle(600)
    from PySide6.QtWidgets import QPushButton
    online = next(b for b in win.sidebar.findChildren(QPushButton) if b.text() == "Find online")
    popup(online.showMenu, "menu_findonline")


def shot_menus(win, markers):
    win.toggle_library(False)
    win.toggle_sidebar(False)
    size_win(win)
    playing(win)
    show_bars(win)
    popup(lambda: win.show_main_menu(win.top.btn_menu), "menu_main")
    popup(lambda: win.show_context_menu(win.mapToGlobal(QPoint(300, 200))), "menu_context")
    popup(win.show_subs_menu, "menu_subs")
    popup(win.show_audio_menu, "menu_audio")


def shot_dialogs(win, markers):
    size_win(win)
    playing(win)
    popup(lambda: win.open_subtitle_dialog(), "dlg_subtitles")
    popup(win.open_stream_dialog, "dlg_stream")
    popup(win.show_shortcuts, "dlg_shortcuts", prep=lambda d: d.resize(853, 1200))


PREF_PAGES = ("general", "interface", "playback", "subtitles", "controls", "privacy", "performance")


def shot_prefs(win, markers):
    from PySide6.QtWidgets import QListWidget, QScrollArea
    for i, page in enumerate(PREF_PAGES):
        def prep(d, i=i):
            d.resize(1067, 677)
            d.findChild(QListWidget).setCurrentRow(i)
            settle(300)
            sc = d.pages.currentWidget()
            sc = sc if isinstance(sc, QScrollArea) else sc.findChild(QScrollArea)
            if sc is not None and sc.widget() is not None:
                extra = sc.widget().sizeHint().height() - sc.viewport().height()
                if extra > 0:
                    d.resize(1067, min(677 + extra + 4, 1150))
        popup(win.show_preferences, "prefs_" + page, prep=prep)


def shot_pip(win, markers):
    size_win(win)
    playing(win)
    win.toggle_pip()
    settle(1500)
    save(screen_grab(win), "pip")
    win.toggle_pip()
    settle(1000)


def shot_lyrics(win, markers):
    size_win(win)
    win.toggle_library(False)
    win.toggle_sidebar(False)
    win.set_rate(1.0, osd=False)
    song = "/Music/Ada Rowe/Field Notes/01 Morning Field.mp3"
    win.play_path(song)
    wait_for(lambda: win.engine.is_playing(), 15)
    settle(1500)
    win.engine.seek(27000)
    settle(2500)
    show_bars(win)
    save(screen_grab(win.centralWidget()), "music_lyrics")


SHOTS = [("home", shot_home), ("player", shot_player), ("menus", shot_menus), ("pip", shot_pip),
         ("panels", shot_panels), ("library", shot_library), ("music", shot_music), ("recent", shot_recent),
         ("playlists", shot_playlists), ("streams", shot_streams), ("queue", shot_queue),
         ("settings", shot_settings), ("dialogs", shot_dialogs), ("prefs", shot_prefs), ("lyrics", shot_lyrics)]

if __name__ == "__main__":
    main()
