#!/bin/bash
# Pylon for macOS: picks the Python that matches this Mac (and the installed VLC), then starts Pylon.
CONTENTS="$(cd "$(dirname "$0")/.." && pwd)"
R="$CONTENTS/Resources"
export PYTHONPATH="$R/site-packages"
unset PYTHONHOME
ARCH="$(uname -m)"
VLC_LIB=""
for d in "$PYLON_VLC_DIR" "/Applications/VLC.app" "$HOME/Applications/VLC.app"; do
  if [ -n "$d" ] && [ -f "$d/Contents/MacOS/lib/libvlc.dylib" ]; then VLC_LIB="$d/Contents/MacOS/lib/libvlc.dylib"; break; fi
done
# An Intel-only VLC on an Apple Silicon Mac: run Pylon's Intel Python under Rosetta so they match
if [ "$ARCH" = "arm64" ] && [ -n "$VLC_LIB" ] && ! /usr/bin/file "$VLC_LIB" | grep -q "arm64"; then
  exec /usr/bin/arch -x86_64 "$R/python-x86_64/bin/python3" -s "$R/pylon/main.py" "$@"
fi
PY="$R/python-$ARCH/bin/python3"
[ -x "$PY" ] || PY="$R/python-x86_64/bin/python3"
exec "$PY" -s "$R/pylon/main.py" "$@"
