"""Small helpers: time formatting, natural sorting, episode detection,
subtitle discovery and subtitle file parsing."""
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg",
              ".ts", ".m2ts", ".mts", ".3gp", ".ogv", ".vob", ".divx", ".rmvb", ".asf", ".f4v", ".iso"}
AUDIO_EXTS = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff",
              ".ape", ".mka", ".dts", ".ac3"}     # ALAC lives in .m4a
SUB_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx", ".smi", ".txt"}   # files you can load as subtitles
# Files picked up next to a video automatically: not .txt (too many notes and readmes) or .idx (needs its .sub)
SUB_SIDECAR_EXTS = SUB_EXTS - {".txt", ".idx"}
PLAYLIST_EXTS = {".m3u", ".m3u8", ".pls", ".xspf"}
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS

# The file types Pylon lists itself for under "Open with" on every OS. This is the one list:
# packaging/sync_metadata.py writes it into the Windows installer, register_pylon.bat, the macOS
# Info.plist and the Linux desktop file. .iso is left out on purpose: it is a disc image first.
ASSOCIATED_EXTS = tuple(sorted((MEDIA_EXTS | PLAYLIST_EXTS) - {".iso"}))
# Linux MIME type for each of them (several extensions can share one)
MIME_TYPES = {
    ".3gp": "video/3gpp", ".asf": "video/x-ms-asf", ".avi": "video/x-msvideo", ".divx": "video/x-msvideo",
    ".f4v": "video/mp4", ".flv": "video/x-flv", ".m2ts": "video/mp2t", ".m4v": "video/x-m4v",
    ".mkv": "video/x-matroska", ".mov": "video/quicktime", ".mp4": "video/mp4", ".mpeg": "video/mpeg",
    ".mpg": "video/mpeg", ".mts": "video/mp2t", ".ogv": "video/ogg", ".rmvb": "application/vnd.rn-realmedia",
    ".ts": "video/mp2t", ".vob": "video/mpeg", ".webm": "video/webm", ".wmv": "video/x-ms-wmv",
    ".aac": "audio/aac", ".ac3": "audio/ac3", ".aiff": "audio/x-aiff", ".ape": "audio/x-ape",
    ".dts": "audio/vnd.dts", ".flac": "audio/flac", ".m4a": "audio/mp4", ".mka": "audio/x-matroska",
    ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".opus": "audio/opus", ".wav": "audio/x-wav",
    ".wma": "audio/x-ms-wma",
    ".m3u": "audio/x-mpegurl", ".m3u8": "application/vnd.apple.mpegurl", ".pls": "audio/x-scpls",
    ".xspf": "application/xspf+xml",
}


def desktop_mime_types() -> list[str]:
    """The MimeType= list of Pylon's Linux desktop entry."""
    return sorted({MIME_TYPES[e] for e in ASSOCIATED_EXTS})


# Playback speeds: the steps the Faster/Slower keys move through, and the presets in the menu and
# the Playback tab's chips.
SPEED_STEPS = (0.25, 0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0)
SPEED_PRESETS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)

def fmt_time(ms: int | float | None, force_hours: bool = False) -> str:
    if ms is None or ms < 0:
        ms = 0
    s = int(ms // 1000)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h or force_hours:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def fmt_delay(ms: int) -> str:
    sign = "+" if ms > 0 else ("" if ms == 0 else "-")
    return f"{sign}{abs(ms) / 1000:.2f}s"


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def merge_in_name_order(existing: list, new: list, path_of=lambda x: x) -> list:
    """Add items to a list, putting each file next to the files from its own folder in name order (#57).

    Episode 2 added to a list holding episodes 1, 5 and 6 of the same show lands between 1 and 5.
    A file whose folder isn't in the list yet, or whose folder's files are in an order the user chose
    themselves (not name order), goes at the end like before. Streams and songs always go at the end:
    a mix is in the order you add songs, and an album's order is its track numbers, not file names."""
    out = list(existing)

    def folder(x):
        p = path_of(x)
        return None if is_url(p) or is_audio(p) else os.path.normcase(os.path.dirname(os.path.abspath(p)))

    def key(x):
        return natural_key(os.path.basename(path_of(x)))

    for item in new:
        f = folder(item)
        same = [i for i, x in enumerate(out) if f is not None and folder(x) == f]
        keys = [key(out[i]) for i in same]
        if not same or keys != sorted(keys):
            out.append(item)
            continue
        k = key(item)
        after = [i for i in same if key(out[i]) <= k]
        out.insert(after[-1] + 1 if after else same[0], item)
    return out


def sort_key_by_name(path: str, title: str = ""):
    """Name order for a whole queue or playlist: by title for channels, else by file name.

    A file sorts by its file name even when the queue shows another title for it. Entries from an
    .m3u carry the title another player wrote from the file's tags, and sorting by that put a
    folder in tag order (#58)."""
    return natural_key(title if is_url(path) and title else display_name(path))


def is_url(s: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", s or "")) and not s.lower().startswith("file://")


def to_path(s: str) -> str:
    """Convert a file:// URI into a filesystem path; leave others alone."""
    if s and s.lower().startswith("file://"):
        p = urlparse(s)
        path = unquote(p.path)
        if os.name == "nt" and re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        elif p.netloc and p.netloc.lower() != "localhost":
            path = "//" + p.netloc + path          # file://server/share/x is a network share
        return os.path.normpath(path)
    return s


def norm(p: str) -> str:
    """Windows-style absolute path for local files (VLC on Windows rejects
    D:/forward/slashes); URLs pass through untouched."""
    if not p:
        return p
    p = to_path(p)
    if is_url(p):
        return p
    return os.path.normpath(os.path.abspath(p))


def short_path(path: str) -> str:
    """A folder as people say it: relative to the home folder when it's inside it (Pictures/Pylon)."""
    home = os.path.expanduser("~")
    try:
        rel = os.path.relpath(path, home)
    except ValueError:                   # another drive on Windows
        return path
    return path if rel.startswith("..") or os.path.isabs(rel) else rel


def display_name(path: str) -> str:
    if is_url(path):
        tail = urlparse(path).path.rstrip("/").split("/")[-1]
        return unquote(tail) or path
    return Path(path).stem


# Episode markers, shared by titles, subtitle matching and subtitle searches: S01E02, 1x02 and E02/EP02.
_SXE = r"[Ss](\d{1,2})[ ._-]*[Ee](\d{1,3})"
_NXN = r"(\d{1,2})[xX](\d{1,3})"
_EPN = r"[Ee][Pp]?[ ._-]?(\d{1,3})"
# For matching subtitle files to videos (loose: any of the three, anywhere in the name)
_EP_PATTERNS = [re.compile(_SXE), re.compile(_NXN), re.compile(_EPN)]
# For titles: S01E02 or 1x02 (two or three digits, so "4x4" stays part of a name), as a whole word
_TITLE_EP = re.compile(rf"\b(?:{_SXE}|(\d{{1,2}})[xX](\d{{2,3}}))\b")
# For subtitle searches: the marker and everything after it
_EP_TAIL = re.compile(rf"\s*\b(?:{_SXE}|{_NXN}|{_EPN})\b.*$")

_JUNK = re.compile(r"\b(2160p|1080p|720p|480p|4k|uhd|hdr10?\+?|dv|web-?dl|webrip|web|bluray|blu-ray|brrip|bdrip|"
                   r"dvdrip|hdtv|x26[45]|h\.?26[45]|hevc|avc|aac\d?(\.\d)?|ddp?\d?(\.\d)?|atmos|10bit|8bit|"
                   r"proper|repack|extended|remastered|multi|dual|subs?|esub)\b.*$", re.I)


def pretty_title(path: str) -> str:
    """A readable name for cards: "Shameless.US.S02E01.1080p.WEB" -> "Shameless US · S02E01",
    "Movie.Name.2019.1080p.BluRay" -> "Movie Name (2019)". Falls back to the plain file name."""
    name = display_name(path)
    if is_url(path):
        return name
    text = re.sub(r"[._]+", " ", name).strip()
    m = _TITLE_EP.search(text)
    if m:
        show = text[:m.start()].strip(" -[(")
        season, episode = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        code = f"S{int(season):02d}E{int(episode):02d}"
        return f"{show}  ·  {code}" if show else code
    years = [y for y in re.finditer(r"[\[(]?\b(19[3-9]\d|20[0-4]\d)\b[\])]?", text) if y.start() > 0]
    m = years[-1] if years else None
    if m:
        return f"{text[:m.start()].strip(' -[(')} ({m.group(1)})"
    cleaned = _JUNK.sub("", text).strip(" -[(")
    return cleaned or name


def is_media(path: str) -> bool:
    return Path(path).suffix.lower() in MEDIA_EXTS


def is_audio(path: str) -> bool:
    return Path(path).suffix.lower() in AUDIO_EXTS


def is_dvd_folder(path: str) -> bool:
    """A copied DVD: a VIDEO_TS folder, or a folder that holds one."""
    if not path or is_url(path) or not os.path.isdir(path):
        return False
    if os.path.basename(os.path.normpath(path)).upper() == "VIDEO_TS":
        folder = path
    else:
        folder = next((os.path.join(path, f) for f in _listdir(path) if f.upper() == "VIDEO_TS"), "")
    return bool(folder) and any(f.upper() == "VIDEO_TS.IFO" for f in _listdir(folder))


def is_disc(path: str) -> bool:
    """A DVD image (.iso), a DVD folder or a dvd:// link: played with its menus and titles."""
    if not path:
        return False
    if path.lower().startswith("dvd://"):
        return True
    return Path(path).suffix.lower() == ".iso" or is_dvd_folder(path)


def disc_mrl(path: str) -> str:
    """How VLC is asked to open a disc. An .iso opens as a file; a folder needs dvd://."""
    if is_dvd_folder(path):
        return "dvd:///" + path.replace("\\", "/").lstrip("/")
    return path


def _listdir(folder):
    try:
        return os.listdir(folder)
    except OSError:
        return []


def list_media(folder: str) -> list[str]:
    try:
        items = [os.path.join(folder, f) for f in os.listdir(folder)]
    except OSError:
        return []
    files = [f for f in items if os.path.isfile(f) and is_media(f)]
    return sorted(files, key=lambda p: natural_key(os.path.basename(p)))


# ---------- episode / subtitle matching ----------

def episode_key(name: str):
    """Return (season, episode) if the name looks like an episode, else None."""
    for i, pat in enumerate(_EP_PATTERNS):
        m = pat.search(name)
        if m:
            if i < 2:
                return int(m.group(1)), int(m.group(2))
            return 0, int(m.group(1))
    return None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


MATCH_LEVELS = [
    ("off", "Don't look for subtitle files"),
    ("exact", "Only files with exactly the same name"),
    ("starts", "Files that start with the video name (e.g. Movie.en.srt)"),
    ("episode", "Same name, or the same episode number (S01E02, 1x02)"),
    ("any", "Any subtitle file in the folder"),
]


def find_subtitle_candidates(video: str) -> list[str]:
    folder = os.path.dirname(video)
    cands = []
    search_dirs = [folder]
    for sub in ("Subs", "subs", "Subtitles", "subtitles", "Sub", "sub"):
        d = os.path.join(folder, sub)
        if os.path.isdir(d):
            search_dirs.append(d)
            # Subs/<episode name>/*.srt layout
            stem_dir = os.path.join(d, Path(video).stem)
            if os.path.isdir(stem_dir):
                search_dirs.append(stem_dir)
    for d in search_dirs:
        try:
            for f in os.listdir(d):
                p = os.path.join(d, f)
                if os.path.isfile(p) and Path(f).suffix.lower() in SUB_SIDECAR_EXTS:
                    cands.append(p)
        except OSError:
            pass
    return cands


def match_subtitle(video: str, candidates: list[str], level: str = "episode") -> str | None:
    if level == "off" or not candidates:
        return None
    stem = _norm(Path(video).stem)
    ep = episode_key(Path(video).stem)
    best, best_score = None, 0
    for c in candidates:
        cstem = _norm(Path(c).stem)
        # files inside Subs/<video stem>/ count as exact
        parent = _norm(Path(c).parent.name)
        score = 0
        if cstem == stem or parent == stem:
            score = 100
        elif level in ("starts", "episode", "any") and cstem.startswith(stem):
            score = 80
        elif level in ("episode", "any") and ep and episode_key(Path(c).stem) == ep:
            score = 60
        elif level == "any":
            score = 10
        if level == "exact" and score < 100:
            score = 0
        # prefer English / non-forced
        low = c.lower()
        if score and ("eng" in low or ".en." in low):
            score += 3
        if score and "forced" in low:
            score -= 5
        if score > best_score:
            best, best_score = c, score
    return best


def auto_match_folder(videos: list[str], subs: list[str]) -> dict[str, str | None]:
    """Pair each video with its best subtitle from a pool of subtitle files."""
    out = {}
    for v in videos:
        out[v] = match_subtitle(v, subs, "episode")
    # if nothing matched and counts are equal, pair in natural order
    if subs and not any(out.values()) and len(videos) == len(subs):
        s_sorted = sorted(subs, key=lambda p: natural_key(os.path.basename(p)))
        out = dict(zip(videos, s_sorted))
    return out


# ---------- subtitle parsing for the timeline ----------

def _ts_to_ms(ts: str) -> int:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
        elif len(parts) == 2:
            h, (m, s) = 0, parts
        else:
            return 0
        return int((int(h) * 3600 + int(m) * 60 + float(s)) * 1000)
    except ValueError:
        return 0


def _read_text(path: str) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except (UnicodeError, UnicodeDecodeError):
            continue
        except OSError:
            return ""
    return ""


def parse_subtitles(path: str) -> list[tuple[int, int, str]]:
    """Return a list of (start_ms, end_ms, text) cues. Supports SRT, VTT, ASS/SSA."""
    ext = Path(path).suffix.lower()
    text = _read_text(path)
    cues = []
    if ext in (".srt", ".vtt"):
        arrow = re.compile(r"([\d:.,]+)\s*-->\s*([\d:.,]+)")
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            m = arrow.search(lines[i])
            if m:
                start, end = _ts_to_ms(m.group(1)), _ts_to_ms(m.group(2))
                i += 1
                body = []
                while i < len(lines) and lines[i].strip():
                    body.append(re.sub(r"<[^>]+>", "", lines[i]).strip())
                    i += 1
                cues.append((start, end, " ".join(body)))
            i += 1
    elif ext in (".ass", ".ssa"):
        for line in text.splitlines():
            if line.startswith("Dialogue:"):
                parts = line.split(",", 9)
                if len(parts) >= 10:
                    txt = re.sub(r"\{[^}]*\}", "", parts[9]).replace("\\N", " ").strip()
                    cues.append((_ts_to_ms(parts[1]), _ts_to_ms(parts[2]), txt))
    cues.sort()
    return cues


_LRC_TIME = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_LRC_WORD_TIME = re.compile(r"<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>")
_LRC_OFFSET = re.compile(r"^\s*\[offset:\s*([+-]?\d+)\s*\]", re.I | re.M)
_LRC_TAG = re.compile(r"^\s*\[[a-z#]+:.*\]\s*$", re.I)


def parse_lrc(text: str) -> list[tuple[int | None, str]]:
    """Lines of a .lrc lyrics file as (ms, text), in time order. A line with several time tags is repeated at
    each; [offset:+500] shows every line 500 ms earlier; word timings (<00:12.30>) are dropped. A file with no
    time tags gives its lines with None for the time (shown without following the song)."""
    m = _LRC_OFFSET.search(text)
    offset = int(m.group(1)) if m else 0
    timed, plain = [], []
    for raw in text.splitlines():
        stamps = []
        rest = raw.strip()
        while True:
            t = _LRC_TIME.match(rest)
            if not t:
                break
            frac = t.group(3) or "0"
            ms = int(frac.ljust(3, "0")[:3]) if len(frac) != 2 else int(frac) * 10
            stamps.append((int(t.group(1)) * 60 + int(t.group(2))) * 1000 + ms)
            rest = rest[t.end():].lstrip()
        words = _LRC_WORD_TIME.sub("", rest).strip()
        if stamps:
            timed.extend((max(0, st - offset), words) for st in stamps)
        elif rest and not _LRC_TAG.match(rest):
            plain.append((None, words))
    if timed:
        timed.sort(key=lambda x: x[0])
        return timed
    return plain


def find_lyrics(song: str) -> str:
    """The .lrc file next to a song with the same name (any letter case), or ""."""
    if not song or is_url(song):
        return ""
    folder, name = os.path.split(song)
    want = os.path.splitext(name)[0].lower() + ".lrc"
    for entry in _listdir(folder or "."):
        if entry.lower() == want:
            return os.path.join(folder, entry)
    return ""


def read_lyrics(song: str) -> list[tuple[int | None, str]]:
    path = find_lyrics(song)
    return parse_lrc(_read_text(path)) if path else []


def lyric_index(lines, ms: int) -> int:
    """Index of the line sung at ms (-1 before the first, or when the lyrics have no times)."""
    lo, hi, found = 0, len(lines) - 1, -1
    while lo <= hi:
        mid = (lo + hi) // 2
        t = lines[mid][0]
        if t is None:
            return -1
        if t <= ms:
            found, lo = mid, mid + 1
        else:
            hi = mid - 1
    return found


# VLC options a browser extension such as "Open in VLC" passes with a link (#91). Their values reach VLC as
# options of that link, so a site that needs its page as the referrer, or a browser's user agent, plays.
PASSED_OPTIONS = ("http-referrer", "http-user-agent")


def parse_command_line(argv) -> tuple[list[str], dict[str, list[str]], dict[str, str]]:
    """What to open from VLC-style command-line arguments: (targets, {target: [":option=value", ...]},
    {target: title}). "--http-referrer X" or "--http-referrer=X" before the links applies to every link;
    ":http-referrer=X" after a link applies to that link; --meta-title / :meta-title name it. Other options
    are ignored, and their values aren't taken for files."""
    targets, opts, titles = [], {}, {}
    common, common_title = [], ""
    args = [a for a in argv if a]
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--") or (a.startswith(":") and not targets):
            name, eq, value = a.lstrip("-:").partition("=")
            name = name.lower()
            if name in PASSED_OPTIONS + ("meta-title",) and not eq and i + 1 < len(args):
                i += 1
                value = args[i]
            if name in PASSED_OPTIONS:
                common.append(f":{name}={value}")
            elif name == "meta-title":
                common_title = value
        elif a.startswith(":"):                    # :option[=value] belongs to the link before it
            name, _, value = a[1:].partition("=")
            name = name.lower()
            if name in PASSED_OPTIONS:
                opts.setdefault(targets[-1], []).append(f":{name}={value}")
            elif name == "meta-title":
                titles[targets[-1]] = value
        elif not a.startswith("-"):
            targets.append(a)
        i += 1
    for t in targets:
        if is_url(t) and common:
            opts[t] = common + [o for o in opts.get(t, []) if o not in common]
        if common_title and len(targets) == 1:
            titles.setdefault(t, common_title)
    return targets, opts, titles


def parse_m3u(text: str) -> list[tuple[str, str]] | None:
    """If text is a channel-list M3U (not an HLS stream), return [(name, url)]."""
    if "#EXT-X-TARGETDURATION" in text or "#EXT-X-STREAM-INF" in text or "#EXT-X-MEDIA-SEQUENCE" in text:
        return None
    out, name = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            name = line.split(",", 1)[1].strip() if "," in line else None
        elif not line.startswith("#"):
            out.append((name or display_name(line), line))
            name = None
    return out or None



def parse_jump(text: str, now_ms: int, length_ms: int) -> int | None:
    """Where a typed time points, in ms, or None if it can't be read.
    1:02:10, 62:10 and 2:10 are clock times; digits alone are read like a clock from the right, so 130 is
    1:30 and 10230 is 1:02:30; +30 and -10 jump from where you are (seconds, or a clock time); 50% is half
    way. The result stays within the file."""
    s = (text or "").strip().replace(" ", "").replace(",", ".")
    if not s:
        return None
    rel = s[0] if s[0] in "+-" else ""
    body = s[1:] if rel else s
    try:
        if body.endswith("%") and not rel:
            if not length_ms:
                return None
            ms = int(float(body[:-1]) / 100 * length_ms)
        elif ":" in body:
            parts = body.split(":")
            if len(parts) > 3 or any(not p for p in parts[1:]):
                return None
            secs = 0.0
            for p in parts:
                secs = secs * 60 + float(p or 0)
            ms = int(secs * 1000)
        elif rel:
            ms = int(float(body) * 1000)          # +30: seconds
        elif body.isdigit():
            digits = body[-6:].rjust(6, "0")       # hhmmss, like a microwave
            h, m, sec = int(digits[:2]), int(digits[2:4]), int(digits[4:])
            ms = ((h * 60 + m) * 60 + sec) * 1000
        else:
            return None
    except ValueError:
        return None
    if rel == "+":
        ms = now_ms + ms
    elif rel == "-":
        ms = now_ms - ms
    ms = max(0, ms)
    return min(ms, length_ms - 500) if length_ms > 500 else ms


def parse_pls(text: str) -> list[tuple[str, str]]:
    """[(name, entry)] from a .pls playlist (FileN= and TitleN= keys, in N order)."""
    files, titles = {}, {}
    for raw in text.splitlines():
        m = re.match(r"\s*(File|Title)(\d+)\s*=(.*)$", raw, re.I)
        if m:
            (files if m.group(1).lower() == "file" else titles)[int(m.group(2))] = m.group(3).strip()
    return [(titles.get(n) or display_name(files[n]), files[n]) for n in sorted(files) if files[n]]


def parse_xspf(text: str) -> list[tuple[str, str]]:
    """[(name, entry)] from an .xspf playlist: each track's <location> and <title>."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError:
        return []
    out = []
    for track in root.iter():
        if track.tag.rsplit("}", 1)[-1] != "track":
            continue
        loc = title = ""
        for child in track:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "location" and not loc:
                loc = (child.text or "").strip()
            elif tag == "title":
                title = (child.text or "").strip()
        if loc:
            out.append((title, loc))
    return out


def _playlist_entry(entry: str, base: str) -> str:
    """A playlist entry as Pylon plays it: links stay links, file: URIs become paths, and relative
    paths (or relative URIs, as .xspf has them) are made absolute against the playlist's folder."""
    if entry.lower().startswith("file:"):
        if not entry.lower().startswith("file://"):        # file:relative/name.mp3
            entry = unquote(entry[5:])
        else:
            return to_path(entry)
    if is_url(entry):
        return entry
    if os.path.isabs(entry) or re.match(r"^[A-Za-z]:[\\/]", entry) or entry.startswith(("\\\\", "//")):
        return os.path.normpath(entry)
    return os.path.normpath(os.path.join(base, entry))


def _playlist_text(path: str) -> str:
    """A playlist's text: UTF-8 (with or without a BOM), else the system's own encoding, which older
    players use for .m3u and .pls."""
    with open(path, "rb") as f:
        data = f.read(8_000_000)
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        import locale
        return data.decode(locale.getpreferredencoding(False) or "latin-1", errors="replace")


def read_playlist(path: str) -> list[tuple[str, str]]:
    """[(name, path or link)] from an .m3u, .m3u8, .pls or .xspf file, with file: URIs and relative
    paths turned into absolute paths. Empty if the file can't be read or isn't a list (an HLS stream)."""
    try:
        text = _playlist_text(path)
    except OSError:
        return []
    head = text.lstrip()[:2000].lower()
    ext = os.path.splitext(path)[1].lower()
    if head.startswith("[playlist]") or (ext == ".pls" and not head.startswith("#")):
        found = parse_pls(text)
    elif head.startswith("<?xml") or head.startswith("<playlist") or ext == ".xspf":
        found = parse_xspf(text)
    else:
        found = parse_m3u(text) or []
    base = os.path.dirname(os.path.abspath(path))
    out = []
    for name, entry in found:
        target = _playlist_entry(entry, base)
        if not name or name == display_name(entry):         # no title of its own: name it from the file
            name = display_name(target)
        out.append((name, target))
    return out


def expand_playlists(paths) -> list[tuple[str, str]]:
    """[(name, path or link)] for files picked or dropped together: each playlist among them is replaced,
    in place, by its entries, and every other path is kept as it is (with an empty name)."""
    out = []
    for p in paths:
        if not is_url(p) and os.path.splitext(p)[1].lower() in PLAYLIST_EXTS and os.path.isfile(p):
            out += read_playlist(p)
        else:
            out.append(("", p))
    return out


def write_m3u(path: str, entries) -> None:
    """Write [(name, path or link)] as an extended M3U playlist. Raises OSError if it can't be written."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for name, url in entries:
            f.write(f"#EXTINF:-1,{name}\n{url}\n")

# Subtitle sites "Find online" can open (#46). Each search address was checked in
# October 2026. Subscene shut down in 2024; the YIFY subtitle sites are unofficial copies.
SUBTITLE_SITES = [
    ("opensubtitles.com", "OpenSubtitles.com",
     "https://www.opensubtitles.com/en/search-all/q-{q}/hearing_impaired-include/machine_translated-/trusted_sources-"),
    ("opensubtitles.org", "OpenSubtitles.org", "https://www.opensubtitles.org/en/search2/moviename-{q}/sublanguageid-all"),
    ("subdl", "SubDL", "https://subdl.com/search/{q}"),
    ("subsource", "SubSource", "https://subsource.net/search?q={q}"),
    ("addic7ed", "Addic7ed (TV shows)", "https://www.addic7ed.com/search.php?search={q}&Submit=Search"),
]


def subtitle_query(path: str) -> str:
    """What to search subtitle sites for: the show for an episode, the title for a film."""
    if not path:
        return ""
    title = pretty_title(path).split("  ·  ")[0]
    # keep the show name only: drop an episode marker (S01E02, 1x02, E01) and what follows
    title = _EP_TAIL.sub("", title)
    title = re.sub(r"\s*\((19|20)\d\d\)$", "", title).strip()
    return title or display_name(path)


def subtitle_search_url(site: str, query: str) -> str:
    from urllib.parse import quote
    pattern = next((u for k, _n, u in SUBTITLE_SITES if k == site), SUBTITLE_SITES[0][2])
    return pattern.replace("{q}", quote(query.strip(), safe=""))


_USER32 = None


def _user32():
    """user32 with the prototypes Pylon calls declared once (Windows only, imported lazily)."""
    global _USER32
    if _USER32 is None:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wintypes.UINT]
        u.SetWindowPos.restype = wintypes.BOOL
        u.GetSystemMenu.argtypes = [wintypes.HWND, wintypes.BOOL]
        u.GetSystemMenu.restype = wintypes.HMENU
        u.EnableMenuItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
        u.EnableMenuItem.restype = wintypes.BOOL
        u.DrawMenuBar.argtypes = [wintypes.HWND]
        u.DrawMenuBar.restype = wintypes.BOOL
        _USER32 = u
    return _USER32


def win_set_topmost(hwnd: int, on: bool) -> bool:
    """Put a window above (or back among) other apps' windows on Windows. Returns whether it worked.
    The argument types matter on 64-bit Windows: without them ctypes passes HWND_TOPMOST (-1) as a
    32-bit int, which isn't the handle Windows expects (#66)."""
    if sys.platform != "win32":
        return False
    try:
        from ctypes import wintypes
        f = _user32().SetWindowPos
        swp = 0x0001 | 0x0002 | 0x0010            # NOSIZE | NOMOVE | NOACTIVATE
        return bool(f(wintypes.HWND(hwnd), wintypes.HWND(-1 if on else -2), 0, 0, 0, 0, swp))
    except Exception:
        return False


def win_enable_close(hwnd: int) -> bool:
    """Turn the title bar's close button (X) back on for a window on Windows. Leaving borderless
    picture in picture could leave it greyed out (#71): the button follows the Close item of the
    window's system menu, which Windows keeps across frame changes. Returns whether it worked."""
    if sys.platform != "win32":
        return False
    try:
        from ctypes import wintypes
        u = _user32()
        menu = u.GetSystemMenu(wintypes.HWND(hwnd), False)
        if not menu:
            return False
        sc_close, mf_bycommand, mf_enabled = 0xF060, 0x0000, 0x0000
        u.EnableMenuItem(menu, sc_close, mf_bycommand | mf_enabled)
        u.DrawMenuBar(wintypes.HWND(hwnd))
        # NOSIZE | NOMOVE | NOZORDER | NOACTIVATE | FRAMECHANGED: redraw the title bar
        u.SetWindowPos(wintypes.HWND(hwnd), None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
        return True
    except Exception:
        return False
