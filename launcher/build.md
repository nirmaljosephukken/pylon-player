# Building Pylon.exe

`Pylon.exe` is a ~90 KB launcher. It finds Python and runs `main.py`, so Windows
can show Pylon by name and icon in "Open with" and Default apps.

Cross-compile from any OS with [Zig](https://ziglang.org) (`pip install ziglang`):

```
python -m ziglang cc -target x86_64-windows-gnu -O2 -municode -Wl,--subsystem,windows -s -o ../Pylon.exe pylon.c pylon.rc
```

Or with MSVC on Windows: `rc pylon.rc` then `cl /O2 pylon.c pylon.res user32.lib /link /SUBSYSTEM:WINDOWS /OUT:..\Pylon.exe`.
