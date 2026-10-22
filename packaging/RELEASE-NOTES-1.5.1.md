## Pylon 1.5.1

### Fixed
- **New episodes go in order.** Adding episodes to a playlist or the queue used to put them at the end, so episodes 2 and 3 could end up after 7. Now a video added next to others from the same folder slots in among them in name order. Files from a folder that isn't in the list yet still go at the end. So do songs and streams, and a list you've put in your own order isn't touched. The queue and playlists also have **Sort by name** in their right-click menus, to tidy up a list that's already out of order. Sorting a shuffled queue switches it back to In order (#57).
- **Songs are no longer in Continue watching.** Continue watching on the home screen is for videos now (#55).
- **Super Resolution in full screen, another try (Windows).** On some PCs the picture still went black in full screen while a panel was open with RTX Video Super Resolution on. With Super Resolution on, Pylon now keeps the picture one pixel short of the bottom of the screen in full screen. That pixel is in the black bar, so you can't see it, but it means Windows shows full screen the same way as a window, where panels already work. This couldn't be tested on an RTX card, so please say in #42 whether it helps (#42).

### New
- **Continue listening.** The Music section on the home screen starts with what you were listening to. For a song from an album, the card is the album, with a progress bar showing how far through it you are. Clicking it plays the album from the song you were on, at the point you stopped. If you finished a song, it starts the next one. A song that isn't part of an album gets its own card. Hover a card and click × to remove it until you play it again (#55).
- **Move a shortcut that's already taken.** In the keyboard shortcuts window, pressing a key that another action already uses now says which one, with **Use it here** (the other action is left without a key) and **Undo**. If two actions still share a key when you click Save, Pylon offers to keep it for the one you changed last (#56).
- **Aspect ratio and crop keys.** **A** steps through the aspect ratios and **C** through the crops in the settings panel, like in VLC. An on-screen message shows which one is on. If you already gave A or C to something else, your choice is kept and the new action starts without a key (#56).

Thanks to @UserSpringRoll for the three reports, and to @boxdr21-netizen for testing Super Resolution again.

### Downloads
| | Download |
|---|---|
| Windows 10/11 (64-bit) | `Pylon-Setup-1.5.1.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.5.1-x86_64.AppImage` |
| macOS 14+ (experimental) | `Pylon-1.5.1-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
Automated checks cover new episodes slotting into the queue and playlists in name order (including episode 10 after 9, a list in your own order, other folders, songs, streams, the playing item keeping its place, Play next, and turning Shuffle off afterwards), Sort by name for the queue and playlists, the shortcut clash bar (Use it here, Undo, fixing it by hand), the Save prompt (keeping the key for the one you changed, or going back), the A and C keys stepping and wrapping through every aspect ratio and crop, a key you already chose winning over a new default, songs leaving Continue watching, and Continue listening (album progress, moving on after a finished song, only the newest song per album, finished albums, songs not on an album, resuming at the right song and time, and removing a card until it's played again), and the one-pixel full-screen margin with Super Resolution (only on Windows, only with Super Resolution on, and gone again after leaving full screen). All 27 test files pass. The home screen with Continue listening and the shortcut clash bar were also checked on screen. The Linux AppImage was started on Fedora 44 with PipeWire. The Windows installer and macOS package were checked for contents and version, but neither has been run on its own system.
