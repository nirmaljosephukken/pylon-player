"""Small helpers: time formatting, natural sorting, episode detection,
subtitle discovery and subtitle file parsing."""
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg",
              ".ts", ".m2ts", ".mts", ".3gp", ".ogv", ".vob", ".divx", ".rmvb", ".asf", ".f4v"}
AUDIO_EXTS = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".alac", ".aiff",
              ".ape", ".mka", ".dts", ".ac3"}
SUB_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx", ".smi", ".txt"}
PLAYLIST_EXTS = {".m3u", ".m3u8", ".pls", ".xspf"}
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS


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


def is_url(s: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", s or "")) and not s.lower().startswith("file://")


def to_path(s: str) -> str:
    """Convert a file:// URI into a filesystem path; leave others alone."""
    if s and s.lower().startswith("file://"):
        p = urlparse(s)
        path = unquote(p.path)
        if os.name == "nt" and re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
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


def display_name(path: str) -> str:
    if is_url(path):
        tail = urlparse(path).path.rstrip("/").split("/")[-1]
        return unquote(tail) or path
    return Path(path).stem


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
    m = re.search(r"\b[Ss](\d{1,2})[ ._-]?[Ee](\d{1,3})\b", text) or re.search(r"\b(\d{1,2})x(\d{2,3})\b", text)
    if m:
        show = text[:m.start()].strip(" -[(")
        code = f"S{int(m.group(1)):02d}E{int(m.group(2)):02d}"
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


def list_media(folder: str) -> list[str]:
    try:
        items = [os.path.join(folder, f) for f in os.listdir(folder)]
    except OSError:
        return []
    files = [f for f in items if os.path.isfile(f) and is_media(f)]
    return sorted(files, key=lambda p: natural_key(os.path.basename(p)))


# ---------- episode / subtitle matching ----------

_EP_PATTERNS = [
    re.compile(r"[Ss](\d{1,2})[ ._-]*[Ee](\d{1,3})"),
    re.compile(r"(\d{1,2})[xX](\d{1,3})"),
    re.compile(r"[Ee][Pp]?[ ._-]?(\d{1,3})"),
]


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
                if os.path.isfile(p) and Path(f).suffix.lower() in SUB_EXTS - {".txt", ".idx"}:
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
