"""Pylon diagnostics: plays the last opened file straight through libVLC
and records what happens. Output goes to logs\\diag.txt (via diag.bat)."""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
print("Python", sys.version)
print("exe", sys.executable)

# 1. find the file to test
target = sys.argv[1] if len(sys.argv) > 1 else None
if not target:
    try:
        from app.store import data_dir
        with open(os.path.join(data_dir(), "data.json"), encoding="utf-8") as f:
            rec = json.load(f).get("recent", [])
        target = rec[0]["path"] if rec else None
    except Exception as e:
        print("could not read history:", e)
if target and "://" not in target:
    target = os.path.normpath(target)
print("target", repr(target), "exists:", bool(target) and os.path.exists(target))

# 2. load the engine module exactly as the app does
try:
    import app.engine as eng
    print("VLC_ERROR", eng.VLC_ERROR)
    vlc = eng.vlc
    print("PYTHON_VLC_LIB_PATH", os.environ.get("PYTHON_VLC_LIB_PATH"))
    print("PYTHON_VLC_MODULE_PATH", os.environ.get("PYTHON_VLC_MODULE_PATH"))
    print("VLC_PLUGIN_PATH", os.environ.get("VLC_PLUGIN_PATH"))
    print("libvlc version", vlc.libvlc_get_version())
    print("python-vlc", getattr(vlc, "__version__", "?"))
except Exception:
    import traceback
    traceback.print_exc()
    sys.exit(1)


def trial(label, args, use_path=True):
    print(f"\n---- {label}: args={args}")
    sys.stdout.flush()
    inst = vlc.Instance(args)
    print("instance", inst)
    if inst is None:
        print("!! libvlc refused these options")
        return
    p = inst.media_player_new()
    m = inst.media_new_path(target) if use_path else inst.media_new(target)
    p.set_media(m)
    print("play() ->", p.play())
    for i in range(16):
        time.sleep(0.5)
        print(f"  t+{(i + 1) / 2:.1f}s state={p.get_state()} time={p.get_time()} len={p.get_length()} vout={p.has_vout()}")
        sys.stdout.flush()
    p.stop()
    p.release()
    inst.release()


if target:
    trial("plain VLC (its own window)", ["-vv"])
    st = eng.Engine.__dict__["_args"]

    class FakeStore:
        def setting(self, k):
            return {"hw_decoding": True}.get(k)
    dummy = type("D", (), {})()
    dummy.store = FakeStore()
    dummy.sub_style = dict(eng.DEFAULT_SUB_STYLE)
    dummy.transform = ""
    args = [a for a in st(dummy) if not a.startswith(("--file-logging", "--logfile", "--log-verbose"))]
    trial("Pylon options", args + ["-vv"])
print("\nDONE")
