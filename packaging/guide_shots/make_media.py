"""Makes the made-up shows, film and music the user guide's screenshots show (Linux, needs ffmpeg and Pillow).

    python3 packaging/guide_shots/make_media.py [ROOT]      # default ROOT: /  (makes /Shows, /Movies, /Music)

Everything is drawn here, so the pictures carry no one else's work. Re-running skips files that exist.
"""
import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "/")
W, H = 1920, 1080

SHOWS = {
    "Lighthouse Keepers": ("Lighthouse.Keepers.S01E0{n}.1080p.mkv", 6, 3182, "lighthouse"),
    "Night Market": ("Night.Market.S02E0{n}.mkv", 4, 2400, "market"),
}
FILM = ("Movies/Paper Planets (2024)/Paper.Planets.2024.mkv", 5820, "planets")
ALBUMS = [  # artist, album, year, colours (top, bottom, sun)
    ("Ada Rowe", "Field Notes", 2020, ((90, 70, 30), (236, 190, 70), (246, 205, 90))),
    ("Kites & Wires", "Low Orbit", 2021, ((20, 40, 90), (60, 140, 230), (110, 180, 255))),
    ("The Lanterns", "Paper Moons", 2022, ((20, 60, 60), (90, 190, 160), (190, 240, 210))),
    ("Mira Vale", "Night Bus", 2023, ((60, 20, 70), (230, 70, 140), (255, 120, 190))),
    ("Hollow Coast", "Tidewater", 2024, ((40, 50, 60), (220, 120, 50), (235, 120, 50))),
]
SONGS = {
    "Field Notes": ["Morning Field", "Paper Boats", "Copper Sky", "Long Way Round", "Small Hours", "Harvest Moon Road"],
    "Low Orbit": ["Lift Off", "Satellite Hum", "Static Bloom", "Weightless", "Re-entry", "Ground Control Lullaby"],
    "Paper Moons": ["Lantern Street", "Origami", "Folded Light", "Ink and Rain", "Night Garden", "Paper Moon"],
    "Night Bus": ["Last Stop", "Neon Window", "Back Seat", "City Lights", "Sleepwalk", "First Train Home"],
    "Tidewater": ["Low Tide", "Salt", "Driftwood", "Harbour Bells", "Undertow", "High Water"],
}
LYRICS = """[ti:Morning Field]
[ar:Ada Rowe]
[00:04.00]Morning comes in over the field
[00:09.50]Light on the fences, the gate still sealed
[00:15.00]I walk the long way, nowhere to be
[00:20.50]Counting the swallows, they're counting me
[00:26.00]Oh, slow down, slow down
[00:31.00]The day isn't going anywhere
[00:36.50]Oh, slow down, slow down
[00:41.50]I'll meet you there
[00:47.00]Dew on the laces, mud on my knees
[00:52.50]Writing the weather in notes to the trees
"""
LINES = ["We should be back before dark.", "Look, the lamp's already lit.", "The tide comes in at six.",
         "Then we'd better hurry."]


def subtitles(seconds: int) -> str:
    """A line every six seconds, on for five: the guide's playing moment, 12:40, shows the tide line."""
    def t(s):
        return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d},000"
    return "".join(f"{i + 1}\n{t(i * 6)} --> {t(i * 6 + 5)}\n{LINES[i % 4]}\n\n" for i in range(seconds // 6))



def lerp(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def gradient(w, h, top, bottom, right=None):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            c = lerp(top, bottom, y / (h - 1))
            if right:
                c = lerp(c, right, max(0.0, (x / w - 0.45) / 0.55) ** 1.6 * (0.35 + 0.65 * y / h))
            px[x, y] = c
    return img


def glow(img, cx, cy, r, colour, strength=1.0):
    layer = Image.new("RGB", img.size, (0, 0, 0))
    ImageDraw.Draw(layer).ellipse((cx - r, cy - r, cx + r, cy + r), fill=colour)
    layer = layer.filter(ImageFilter.GaussianBlur(r * 0.55))
    return Image.blend(img, Image.composite(layer, img, layer.convert("L")), strength)


def lighthouse():
    w, h = W // 4, H // 4                       # draw small, then scale: the gradient is slow in pure Python
    img = gradient(w, h, (24, 44, 64), (22, 58, 84), right=(214, 110, 44)).resize((W, H), Image.BICUBIC)
    img = glow(img, 1060, 340, 230, (236, 214, 178))
    d = ImageDraw.Draw(img)
    d.polygon([(0, 690), (420, 620), (840, 650), (1350, 620), (W, 600), (W, H), (0, H)], fill=(14, 22, 34))
    d.polygon([(410, 470), (452, 470), (462, 640), (398, 640)], fill=(236, 234, 228))
    d.polygon([(405, 548), (457, 548), (459, 572), (403, 572)], fill=(200, 50, 46))
    return img


def market():
    w, h = W // 4, H // 4
    img = gradient(w, h, (30, 16, 48), (70, 30, 80), right=(240, 120, 60)).resize((W, H), Image.BICUBIC)
    d = ImageDraw.Draw(img)
    for i in range(14):
        x = 120 + i * 130
        img = glow(img, x, 420 + int(40 * math.sin(i)), 34, (255, 200 - i * 6, 120), 0.9)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 700, W, H), fill=(20, 12, 28))
    for i in range(7):
        d.rectangle((90 + i * 260, 560, 250 + i * 260, 700), fill=(40 + i * 8, 24, 52))
    return img


def planets():
    w, h = W // 4, H // 4
    img = gradient(w, h, (8, 12, 30), (30, 40, 90)).resize((W, H), Image.BICUBIC)
    img = glow(img, 640, 520, 260, (120, 170, 255), 0.9)
    img = glow(img, 1380, 300, 120, (255, 190, 120), 0.9)
    d = ImageDraw.Draw(img)
    for i in range(80):
        x, y = (i * 2654435761) % W, (i * 40503) % H
        d.ellipse((x, y, x + 3, y + 3), fill=(220, 225, 255))
    return img


def cover(top, bottom, sun):
    img = gradient(120, 120, top, bottom).resize((600, 600), Image.BICUBIC)
    ImageDraw.Draw(img).ellipse((200, 170, 400, 370), fill=sun)
    return img


def run(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


def video(path: Path, picture, seconds: int):
    """A still picture as a 25 fps H.264 file this long, with quiet sound and an English subtitle. (VLC shows
    nothing for a 1 fps file, so ten seconds are encoded once and repeated without re-encoding.)"""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    png, seg, srt = path.with_suffix(".png"), path.with_suffix(".seg.mkv"), path.with_suffix(".srt")
    picture.save(png)
    srt.write_text(subtitles(seconds), encoding="utf-8")
    run("-loop", "1", "-framerate", "25", "-i", png, "-t", 10, "-c:v", "libx264", "-preset", "veryfast",
        "-tune", "stillimage", "-crf", "28", "-pix_fmt", "yuv420p", "-g", 250, seg)
    run("-stream_loop", -1, "-i", seg, "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=22050", "-i", srt,
        "-map", "0:v", "-map", "1:a", "-map", "2:s", "-t", seconds, "-c:v", "copy", "-c:a", "aac", "-b:a", "16k",
        "-af", "volume=0.02", "-c:s", "srt", "-metadata:s:a:0", "language=eng", "-metadata:s:s:0", "language=eng",
        path)
    for f in (png, seg, srt):
        f.unlink()


def song(path: Path, artist, album, year, title, track, seconds):
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    f = 196 + track * 22
    run("-f", "lavfi", "-i", f"sine=frequency={f}:sample_rate=22050", "-t", seconds, "-af", "volume=0.05",
        "-ac", "1", "-b:a", "32k", "-metadata", f"title={title}", "-metadata", f"artist={artist}",
        "-metadata", f"album={album}", "-metadata", f"date={year}", "-metadata", f"track={track}", path)


def main():
    pics = {"lighthouse": lighthouse, "market": market, "planets": planets}
    made = {}
    for show, (pattern, count, secs, pic) in SHOWS.items():
        made.setdefault(pic, pics[pic]())
        for n in range(1, count + 1):
            video(ROOT / "Shows" / show / pattern.format(n=n), made[pic], secs)
    subs = ROOT / "Shows" / "Lighthouse Keepers" / "Subs"
    subs.mkdir(exist_ok=True)
    for n in range(1, 7):
        p = subs / f"Lighthouse.Keepers.S01E0{n}.1080p.en.srt"
        if not p.exists():
            p.write_text(subtitles(3182), encoding="utf-8")
    path, secs, pic = FILM
    video(ROOT / path, pics[pic](), secs)
    for artist, album, year, cols in ALBUMS:
        folder = ROOT / "Music" / artist / album
        folder.mkdir(parents=True, exist_ok=True)
        if not (folder / "cover.jpg").exists():
            cover(*cols).save(folder / "cover.jpg", quality=90)
        for i, title in enumerate(SONGS[album], 1):
            song(folder / f"{i:02d} {title}.mp3", artist, album, year, title, i, 150 + (i * 37) % 120)
    (ROOT / "Music/Ada Rowe/Field Notes/01 Morning Field.lrc").write_text(LYRICS, encoding="utf-8")
    print("Media ready under", ROOT)


if __name__ == "__main__":
    main()
