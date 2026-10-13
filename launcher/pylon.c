/* Pylon.exe: a tiny launcher so Windows can treat Pylon as a normal app.
   Runs  <python>\pythonw.exe "<this folder>\main.py" <same arguments>
   where <python> is the first that exists of:
     <this folder>\.venv\Scripts   (made by setup.bat)
     <this folder>\Python           (a portable Python inside the Pylon folder)
     <this folder>\..\Python       (a portable Python next to it)            */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wchar.h>

static const wchar_t *skip_argv0(const wchar_t *cmd) {
    if (*cmd == L'"') { cmd++; while (*cmd && *cmd != L'"') cmd++; if (*cmd) cmd++; }
    else { while (*cmd && *cmd != L' ' && *cmd != L'\t') cmd++; }
    while (*cmd == L' ' || *cmd == L'\t') cmd++;
    return cmd;
}

int WINAPI wWinMain(HINSTANCE h, HINSTANCE p, PWSTR c, int n) {
    (void)h; (void)p; (void)c; (void)n;
    wchar_t self[MAX_PATH * 2], dir[MAX_PATH * 2], py[MAX_PATH * 2], mainpy[MAX_PATH * 2];
    DWORD len = GetModuleFileNameW(NULL, self, MAX_PATH * 2);
    if (!len || len >= MAX_PATH * 2) return 1;
    wcscpy(dir, self);
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (!slash) return 1;
    *slash = 0;                                   /* dir = folder of Pylon.exe */

    swprintf(mainpy, MAX_PATH * 2, L"%ls\\main.py", dir);
    static const wchar_t *cands[] = { L"%ls\\.venv\\Scripts\\pythonw.exe",
                                      L"%ls\\Python\\pythonw.exe",
                                      L"%ls\\..\\Python\\pythonw.exe" };
    int found = 0;
    for (int i = 0; i < 3 && !found; i++) {
        swprintf(py, MAX_PATH * 2, cands[i], dir);
        found = GetFileAttributesW(py) != INVALID_FILE_ATTRIBUTES;
    }
    if (!found) {
        MessageBoxW(NULL, L"Pylon isn't set up yet.\n\nDouble-click setup.bat in the Pylon folder first. "
                          L"It installs what Pylon needs (takes about a minute).", L"Pylon", MB_ICONINFORMATION);
        return 1;
    }

    const wchar_t *args = skip_argv0(GetCommandLineW());
    size_t total = wcslen(py) + wcslen(mainpy) + wcslen(args) + 16;
    wchar_t *cmd = (wchar_t *)HeapAlloc(GetProcessHeap(), 0, total * sizeof(wchar_t));
    if (!cmd) return 1;
    swprintf(cmd, total, L"\"%ls\" \"%ls\" %ls", py, mainpy, args);

    STARTUPINFOW si; PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof si); si.cb = sizeof si;
    ZeroMemory(&pi, sizeof pi);
    if (!CreateProcessW(py, cmd, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi)) {
        MessageBoxW(NULL, L"Pylon couldn't start Python.", L"Pylon", MB_ICONERROR);
        return 1;
    }
    AllowSetForegroundWindow(pi.dwProcessId);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
