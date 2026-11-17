"""Search and download subtitles from OpenSubtitles.com inside Pylon.

Like other players, Pylon has its own OpenSubtitles.com API key (PYLON_KEY), so searching and downloading
works with no setup. Download limits belong to each user, not to the key: without an account OpenSubtitles
allows a few downloads a day, and signing in with your own free OpenSubtitles.com account (Preferences >
Subtitles) gives you your account's limit. Someone who wants to can use their own API key instead, in the same
place or in PYLON_OPENSUBTITLES_KEY.

Results that were made for this exact file (the file's OpenSubtitles hash matches) are marked and listed
first, so you can pick the one that fits without trying them.
"""
import json
import os
import re
import struct
import threading
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import QObject, Signal

from . import APP_VERSION
from .util import episode_key, subtitle_query

API = "https://api.opensubtitles.com/api/v1"
TIMEOUT = 20
ENV_KEY = "PYLON_OPENSUBTITLES_KEY"
KEY_PAGE = "https://www.opensubtitles.com/en/consumers"
SIGN_UP_PAGE = "https://www.opensubtitles.com"
# Pylon's own API key (the "Pylon" consumer on OpenSubtitles.com). Visible to anyone reading the source, as in
# every open-source player; if it is ever misused, delete it on KEY_PAGE and put a new one here.
PYLON_KEY = ""

# Pylon's language setting can be a two- or three-letter code or a name; OpenSubtitles wants two letters
_LANGS = {
    "eng": "en", "english": "en", "jpn": "ja", "japanese": "ja", "hin": "hi", "hindi": "hi", "mal": "ml",
    "malayalam": "ml", "tam": "ta", "tamil": "ta", "spa": "es", "spanish": "es", "fre": "fr", "fra": "fr",
    "french": "fr", "ger": "de", "deu": "de", "german": "de", "ita": "it", "italian": "it", "por": "pt-pt",
    "portuguese": "pt-pt", "pob": "pt-br", "rus": "ru", "russian": "ru", "ara": "ar", "arabic": "ar",
    "chi": "zh-cn", "zho": "zh-cn", "chinese": "zh-cn", "kor": "ko", "korean": "ko", "dut": "nl", "nld": "nl",
    "dutch": "nl", "pol": "pl", "polish": "pl", "tur": "tr", "turkish": "tr", "swe": "sv", "swedish": "sv",
    "tel": "te", "telugu": "te", "kan": "kn", "kannada": "kn", "ben": "bn", "bengali": "bn",
}


class OpenSubtitlesError(Exception):
    """Something the user should read: no key, a wrong key, no downloads left, no connection."""


def api_language(setting: str) -> str:
    """OpenSubtitles' language code for Pylon's subtitle language setting (English when it's empty)."""
    s = (setting or "").strip().lower()
    if not s:
        return "en"
    s = s.split(",")[0].strip()
    if s in _LANGS:
        return _LANGS[s]
    return s if re.fullmatch(r"[a-z]{2}(-[a-z]{2})?", s) else "en"


def movie_hash(path: str) -> str:
    """OpenSubtitles' hash of a video file: its size plus the 64-bit sums of its first and last 64 KB.
    Empty for a file under 128 KB or one that can't be read."""
    try:
        size = os.path.getsize(path)
        if size < 131072:
            return ""
        h = size
        with open(path, "rb") as f:
            for offset in (0, size - 65536):
                f.seek(offset)
                for (v,) in struct.iter_unpack("<Q", f.read(65536)):
                    h = (h + v) & 0xFFFFFFFFFFFFFFFF
        return f"{h:016x}"
    except OSError:
        return ""


def api_key(store) -> str:
    """Your own key if you set one, else Pylon's."""
    return (store.setting("opensubtitles_key") or os.environ.get(ENV_KEY) or PYLON_KEY or "").strip()


class Client:
    """OpenSubtitles.com's REST API (v1). Every call blocks: run it on a background thread."""

    def __init__(self, key: str, username: str = "", password: str = "", opener=None):
        if not key:
            raise OpenSubtitlesError("This copy of Pylon has no OpenSubtitles.com API key. "
                                     "You can add your own in Preferences > Subtitles.")
        self.key = key
        self.username, self.password = username, password
        self.base = API
        self.token = ""
        self._open = opener or urllib.request.urlopen

    def _request(self, method, path, params=None, body=None, auth=False):
        url = self.base + path
        if params:
            # the API redirects requests whose parameters aren't sorted and lower case
            url += "?" + urllib.parse.urlencode(sorted((k, str(v).lower()) for k, v in params.items() if v not in
                                                       (None, "")))
        headers = {"Api-Key": self.key, "User-Agent": f"Pylon v{APP_VERSION}", "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._open(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as err:
            detail = ""
            try:
                detail = json.loads(err.read().decode("utf-8")).get("message", "")
            except Exception:
                pass
            if err.code in (401, 403):
                raise OpenSubtitlesError("OpenSubtitles.com didn't accept the API key or the account. "
                                         "Check them in Preferences > Subtitles.") from None
            if err.code == 406 or "download" in detail.lower() and "limit" in detail.lower():
                raise OpenSubtitlesError(f"No downloads left for today. {detail}".strip()) from None
            if err.code == 429:
                raise OpenSubtitlesError("OpenSubtitles.com asked Pylon to slow down. Try again in a moment.") from None
            raise OpenSubtitlesError(f"OpenSubtitles.com answered {err.code}. {detail}".strip()) from None
        except (urllib.error.URLError, OSError, ValueError) as err:
            raise OpenSubtitlesError(f"Couldn't reach OpenSubtitles.com ({err}).") from None

    def login(self):
        if self.token or not (self.username and self.password):
            return
        r = self._request("POST", "/login", body={"username": self.username, "password": self.password})
        self.token = r.get("token") or ""
        if r.get("base_url"):
            self.base = f"https://{r['base_url']}/api/v1"

    def search(self, path: str = "", query: str = "", language: str = "en") -> list[dict]:
        """Subtitles for a video file (by its hash, and its title and episode) or for typed words.
        Each result: {file_id, name, language, release, downloads, match (made for this exact file),
        episode ((season, episode) or None)}. Exact matches first, then the most downloaded."""
        params = {"languages": language}
        fhash = movie_hash(path) if path else ""
        if fhash:
            params["moviehash"] = fhash
        if not query and path:
            query = subtitle_query(path)
        if query:
            params["query"] = query
        ep = episode_key(os.path.basename(path)) if path else None
        if ep:
            if ep[0]:
                params["season_number"] = ep[0]
            params["episode_number"] = ep[1]
        r = self._request("GET", "/subtitles", params=params)
        out = []
        for item in r.get("data") or []:
            a = item.get("attributes") or {}
            files = a.get("files") or []
            if not files:
                continue
            fd = a.get("feature_details") or {}
            season, episode = fd.get("season_number"), fd.get("episode_number")
            out.append({
                "file_id": files[0].get("file_id"),
                "name": files[0].get("file_name") or a.get("release") or "subtitle",
                "language": a.get("language") or language,
                "release": a.get("release") or fd.get("movie_name") or fd.get("title") or "",
                "downloads": int(a.get("download_count") or 0),
                "match": bool(a.get("moviehash_match")),
                "episode": (int(season or 0), int(episode)) if episode else None,
            })
        if ep:          # an episode: drop other episodes the title search brought in
            same = [x for x in out if x["match"] or x["episode"] is None or x["episode"][1] == ep[1]]
            out = same or out
        out.sort(key=lambda x: (not x["match"], -x["downloads"]))
        return out

    def download(self, file_id) -> tuple[bytes, str]:
        """The subtitle file's contents and its name on OpenSubtitles."""
        self.login()
        r = self._request("POST", "/download", body={"file_id": int(file_id)}, auth=True)
        link = r.get("link")
        if not link:
            raise OpenSubtitlesError(r.get("message") or "OpenSubtitles.com didn't give a download link.")
        try:
            req = urllib.request.Request(link, headers={"User-Agent": f"Pylon v{APP_VERSION}"})
            with self._open(req, timeout=TIMEOUT) as f:
                data = f.read()
        except (urllib.error.URLError, OSError) as err:
            raise OpenSubtitlesError(f"Couldn't download the subtitle ({err}).") from None
        return data, r.get("file_name") or "subtitle.srt"


def save_next_to(video: str, data: bytes, language: str, fallback_dir: str) -> str:
    """Write a downloaded subtitle as <video name>.<language>.srt next to the video, so it's found again later
    (or in fallback_dir when the video's folder can't be written). Returns the path."""
    base = os.path.splitext(os.path.basename(video))[0]
    name = f"{base}.{language}.srt"
    for folder in (os.path.dirname(video), fallback_dir):
        if not folder:
            continue
        target = os.path.join(folder, name)
        try:
            os.makedirs(folder, exist_ok=True)
            with open(target, "wb") as f:
                f.write(data)
            return target
        except (OSError, ValueError):
            continue
    raise OpenSubtitlesError("Couldn't save the subtitle next to the video or in Pylon's folder.")


class Job(QObject):
    """Runs one function on a background thread and hands its result (or its OpenSubtitlesError) back to the
    window's thread."""
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self.cancelled = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            result = self._fn(self)
        except OpenSubtitlesError as err:
            if not self.cancelled.is_set():
                self.failed.emit(str(err))
            return
        except Exception as err:
            if not self.cancelled.is_set():
                self.failed.emit(f"Something went wrong: {err}")
            return
        if not self.cancelled.is_set():
            self.done.emit(result)
