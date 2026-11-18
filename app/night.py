"""Night mode: loud scenes turned down and quiet talk brought up, so a film can play quietly at night.

VLC has a compressor, but libVLC 3 doesn't let an app switch on audio filters other than its equalizer (a
media player resets "audio-filter" when it is made and whenever the equalizer is set), so Pylon levels the
sound itself. The waveform reader already turns each file's sound into a small mono WAV; from it comes the
file's loudness every STEP_MS. While night mode is on, Pylon looks a little ahead in that loudness and
moves VLC's volume against it: down quickly before a loud part arrives, back up slowly afterwards. The
volume you set stays the volume shown; night mode only scales what VLC plays.
"""
import math
from operator import mul

STEP_MS = 250            # one loudness value for every quarter of a second
FLOOR_DB = -60           # quieter than this counts as silence (it isn't brought up)
THRESHOLD_DB = -26       # louder than this is turned down...
RATIO = 4.0              # ...so 4 dB louder above it plays only 1 dB louder
MAX_CUT_DB = 18
QUIET_DB = -44           # talk between this and the threshold is brought up...
MAX_LIFT_DB = 8          # ...by up to this much
AHEAD_MS = 1500          # start turning down this long before a loud part (the output lags a little)
BEHIND_MS = 500
RELEASE_DB = 1.0         # come back up by at most this much each step, so it doesn't pump


def envelope(samples, rate: int) -> bytes:
    """Loudness (RMS, dB below full scale, plus 100, 0..100) of each STEP_MS of 16-bit mono samples."""
    win = max(1, rate * STEP_MS // 1000)
    out = bytearray()
    for i in range(0, len(samples), win):
        part = samples[i:i + win]
        if not part:
            break
        rms = math.sqrt(sum(map(mul, part, part)) / len(part))
        db = 20 * math.log10(rms / 32768) if rms > 0 else -100
        out.append(int(max(0, min(100, round(db + 100)))))
    return bytes(out)


def level_at(env: bytes, ms: int) -> float | None:
    """The loudest moment just around ms (looking further ahead than behind), in dB; None outside the file."""
    if not env:
        return None
    i = int(ms // STEP_MS)
    if i < 0 or i >= len(env):
        return None
    lo, hi = max(0, i - BEHIND_MS // STEP_MS), min(len(env), i + AHEAD_MS // STEP_MS + 1)
    return max(env[lo:hi]) - 100.0


def target_gain(level_db: float | None) -> float:
    """How many dB to change the volume by for sound this loud."""
    if level_db is None or level_db <= FLOOR_DB:
        return 0.0
    if level_db > THRESHOLD_DB:
        return -min(MAX_CUT_DB, (level_db - THRESHOLD_DB) * (1 - 1 / RATIO))
    if level_db < THRESHOLD_DB:
        lift = (THRESHOLD_DB - level_db) * 0.5
        if level_db < QUIET_DB:            # fade the lift out towards silence, so hiss isn't brought up
            lift *= max(0.0, (level_db - FLOOR_DB) / (QUIET_DB - FLOOR_DB))
        return min(MAX_LIFT_DB, lift)
    return 0.0


class Leveller:
    """Follows one file's loudness and gives the gain to play it at now."""

    def __init__(self):
        self.env = b""
        self.path = None
        self.gain_db = 0.0

    def load(self, path, env: bytes):
        self.path, self.env = path, env or b""
        self.gain_db = 0.0

    def clear(self):
        self.load(None, b"")

    def step(self, ms: int) -> float:
        """The gain (dB) for this moment: down at once, up by RELEASE_DB a step at most."""
        want = target_gain(level_at(self.env, ms))
        if want < self.gain_db:
            self.gain_db = want
        else:
            self.gain_db = min(want, self.gain_db + RELEASE_DB)
        return self.gain_db


def scaled_volume(volume: int, gain_db: float, cubic: bool) -> int:
    """VLC's volume for the user's volume with gain_db applied. On Windows VLC's volume is cubic
    (percentage = loudness ** 1/3), elsewhere it scales the sound directly."""
    factor = 10 ** (gain_db / 20)
    if cubic:
        factor = factor ** (1 / 3)
    return max(0, int(round(volume * factor)))
