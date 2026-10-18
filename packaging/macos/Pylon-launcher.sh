#!/bin/bash
# Pylon for macOS: picks the Python that matches this Mac (and the installed VLC), then starts Pylon.
CONTENTS="$(cd "$(dirname "$0")/.." && pwd)"
R="$CONTENTS/Resources"
export PYTHONPATH="$R/site-packages"
unset PYTHONHOME
ARCH="$(uname -m)"
# uname follows the current process architecture under Rosetta. Detect the
# hardware, then force the matching interpreter slice instead of inheriting it.
if [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ]; then
  ARCH="arm64"
fi
VLC_LIB=""
for d in "$PYLON_VLC_DIR" "/Applications/VLC.app" "$HOME/Applications/VLC.app"; do
  if [ -n "$d" ] && [ -f "$d/Contents/MacOS/lib/libvlc.dylib" ]; then VLC_LIB="$d/Contents/MacOS/lib/libvlc.dylib"; break; fi
done
# An Intel-only VLC on an Apple Silicon Mac: run Pylon's Intel Python under Rosetta so they match
if [ "$ARCH" = "arm64" ] && [ -n "$VLC_LIB" ] && ! /usr/bin/file "$VLC_LIB" | grep -q "arm64"; then
  ARCH="x86_64"
fi
PY="$R/python-$ARCH/bin/python3"
if [ ! -x "$PY" ]; then
  echo "Pylon: the bundled $ARCH Python is missing or not executable: $PY" >&2
  exit 1
fi
exec /usr/bin/arch "-$ARCH" "$PY" -s "$R/pylon/main.py" "$@"
