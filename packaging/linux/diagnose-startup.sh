#!/bin/bash
# Run from a terminal: bash diagnose-startup.sh /path/to/Pylon.AppImage
# Extract into a fresh temporary directory to test startup without FUSE.
set -u
if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
  echo "Usage: bash diagnose-startup.sh /path/to/Pylon.AppImage" >&2
  exit 2
fi
IMAGE="$(readlink -f "$1")"
WORK="$(mktemp -d -t pylon-startup-XXXXXX)" || exit 1
{
  echo "Pylon Linux startup diagnostics"
  date -u
  uname -sm
  getconf GNU_LIBC_VERSION
  echo "Session: ${XDG_SESSION_TYPE:-unknown}; Qt platform: ${QT_QPA_PLATFORM:-xcb}"
  sha256sum "$IMAGE"
} > "$WORK/system.txt" 2>&1
echo "Extracting into $WORK (the original package is unchanged; Pylon uses its normal settings)."
if ! (cd "$WORK" && "$IMAGE" --appimage-extract > extraction.txt 2>&1); then
  echo "Extraction failed. Please share system.txt and extraction.txt from $WORK."
  exit 1
fi
echo "Starting the extracted application. Close Pylon normally if it opens."
(
  cd "$WORK" || exit 1
  PYTHONFAULTHANDLER=1 PYTHONUNBUFFERED=1 QT_DEBUG_PLUGINS=1 \
    ./squashfs-root/AppRun 2>&1 | tee startup-console.txt
  exit "${PIPESTATUS[0]}"
)
RESULT=$?
echo "Exit status: $RESULT" | tee "$WORK/exit-status.txt"
echo "Reports are in $WORK. Review them for personal paths before sharing."
echo "Newer Pylon builds also write startup.log in the Pylon data folder's logs directory."
exit "$RESULT"
