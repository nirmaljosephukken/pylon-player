"""Puts the pictures capture.py took into docs/guide.html: each picture's width and height, and the numbered
markers of the home screen, player and panels figures (from docs/guide/markers.json). A marker's number keeps
its side of the box (below, above, right or left) and its gap from it, so a moved button keeps a tidy label.

    python3 packaging/guide_shots/update_guide.py
"""
import json
import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
HTML = ROOT / "docs" / "guide.html"
MARKERS = ROOT / "docs" / "guide" / "markers.json"
FIGS = {"home": "fig-home", "player": "fig-player", "panels": "fig-panels"}
BOX = re.compile(r'<span class="box" data-i="(\d+)" style="left:([\d.]+)%;top:([\d.]+)%;width:([\d.]+)%;height:([\d.]+)%"></span>')
SPOT = re.compile(r'<button class="spot" type="button" data-i="(\d+)" style="left:([\d.]+)%;top:([\d.]+)%" aria-label="([^"]*)">\d+</button>')


SCALE = 1.5          # the pictures are taken at 150%; width and height give Pylon's own size
MM_PER_PX = 0.147    # a menu's printed width in the PDF...
MAX_MENU_MM = 55     # ...but no taller than this, so a long menu shares its page with the text around it


def sizes(html: str) -> str:
    def fix(m):
        img = Image.open(ROOT / "docs" / m.group(2))
        w, h = round(img.width / SCALE), round(img.height / SCALE)
        mw = f' style="--mw:{min(w * MM_PER_PX, MAX_MENU_MM * w / h):.1f}mm"' if m.group(1) else ""
        return f'{m.group(1) or ""}{mw}><img src="{m.group(2)}" width="{w}" height="{h}"'
    return re.sub(r'(<figure class="plain menu")?(?: style="--mw:[\d.]+mm")?>?<img src="(guide/[\w-]+\.webp)" '
                  r'width="\d+" height="\d+"', fix, html)


def placement(box, spot, w, h):
    """Which side of its box a number sits on, and how far (px), from the guide as it was."""
    l, t, bw, bh = (v / 100 * d for v, d in zip(box, (w, h, w, h)))
    x, y = spot[0] / 100 * w, spot[1] / 100 * h
    if y > t + bh:
        return "below", y - (t + bh)
    if y < t:
        return "above", t - y
    if x > l + bw:
        return "right", x - (l + bw)
    return "left", l - x


def place(box, side, gap, w, h):
    l, t, bw, bh = (v / 100 * d for v, d in zip(box, (w, h, w, h)))
    x, y = {"below": (l + bw / 2, t + bh + gap), "above": (l + bw / 2, t - gap),
            "right": (l + bw + gap, t + bh / 2), "left": (l - gap, t + bh / 2)}[side]
    return round(100 * x / w, 2), round(100 * y / h, 2)


def figure(html: str, fid: str, marks: dict, extra: dict) -> str:
    m = re.search(r'<figure class="shot[^"]*" id="%s">.*?</figure>' % fid, html, re.S)
    fig = m.group(0)
    w, h = (int(v) for v in re.search(r'width="(\d+)" height="(\d+)"', fig).groups())
    old_boxes = {i: [float(v) for v in vals] for i, *vals in BOX.findall(fig)}
    old_spots = {i: ([float(l), float(t)], label) for i, l, t, label in SPOT.findall(fig)}
    for i, (label, legend, like) in extra.items():       # a new item: a marker placed like an old one
        if i not in old_boxes and i in marks:
            old_boxes[i], old_spots[i] = old_boxes[like], (old_spots[like][0], label)
            fig = fig.replace("</ol></figure>", f'<li data-i="{i}"><button type="button"><span class="n">{i}</span>'
                                                f'<span><b>{label}</b> {legend}</span></button></li></ol></figure>')
    boxes, spots = [], []
    for i in sorted(old_boxes, key=int):
        new = marks.get(i)
        if new is None:
            raise SystemExit(f"{fid}: no marker for {i}")
        side, gap = placement(old_boxes[i], old_spots[i][0], w, h)
        x, y = place(new, side, gap, w, h)
        boxes.append(f'<span class="box" data-i="{i}" style="left:{new[0]}%;top:{new[1]}%;width:{new[2]}%;'
                     f'height:{new[3]}%"></span>')
        spots.append(f'<button class="spot" type="button" data-i="{i}" style="left:{x:.2f}%;top:{y:.2f}%" '
                     f'aria-label="{i}: {old_spots[i][1].split(": ", 1)[-1]}">{i}</button>')
    start = fig.index('<span class="box"')
    end = fig.index('<div class="pop"')
    fig = fig[:start] + "".join(boxes) + "".join(spots) + fig[end:]
    return html[:m.start()] + fig + html[m.end():]


def main():
    html = sizes(HTML.read_text(encoding="utf-8"))
    marks = json.loads(MARKERS.read_text(encoding="utf-8"))
    extra = {"player": {"20": ("Close the video", "Stops playing and goes back to the home screen. Shortcut: Ctrl+W.",
                               "6"),
                        "21": ("Quality", "The picture's quality, worked out from its size: 480p, 720p, 1080p or 4K. "
                                          "It follows a stream that changes quality. Hover it for the exact size. "
                                          "Preferences &gt; Playback can cap the quality of streams.", "10")}}
    for key, fid in FIGS.items():
        html = figure(html, fid, marks[key], extra.get(key, {}))
    HTML.write_text(html, encoding="utf-8")
    print("Updated", HTML.relative_to(ROOT))


if __name__ == "__main__":
    main()
