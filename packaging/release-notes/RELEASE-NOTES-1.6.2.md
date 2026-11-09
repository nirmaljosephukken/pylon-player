## Pylon 1.6.2

### New
- **Close the video (#61).** A **✕** next to the menu in the top bar, **Ctrl+W**, or **Close the video** in the menu and the right-click menu stops what's playing, unloads it and goes back to the home page, without closing Pylon. Where you stopped is remembered and the queue is kept, so it shows up in Continue watching and Space plays it again. The key can be changed in the shortcuts window (F1).
- **More aspect ratios and crops (#62).** The crop row now has **2.21:1** (the anamorphic crop from VLC) and **16:10**, and the aspect ratio row has 16:10 too. 21:9 and 2.39:1 were too close to each other, so 21:9 is no longer in the crop row by default. **Preferences > Playback > Aspect ratios and crops to offer** lists VLC's classic shapes (16:9, 16:10, 4:3, 5:4, 5:3, 1.85:1, 2.21:1, 21:9, 2.35:1, 2.39:1 and 1:1). Click the eye next to one to show or hide it in the aspect ratio row, the crop row, or both. The right-click menu and the **A** and **C** keys follow the same choice. On-screen messages show the ratio as 2.21:1 instead of VLC's 221:100.
- **Sorting Playlists and Streams (#63).** Both tabs can be sorted by **Recently played**, like Music. Each sort is now one entry (Date added, Name, Recently played, Items, Watched), with an arrow next to it that turns the order round (A to Z or Z to A, newest or oldest first, and so on), so the list is shorter. Music works the same way. A playlist counts as played when anything in it was played, and a channel list when any of its channels was. Your sort from 1.6.1 is kept, and the home page's Playlists row still follows the Playlists tab.
- **Previous (#64).** Once a file has played for more than 3 seconds, Previous first goes back to its start, like most players. The message now says to press again for the previous item. If you'd rather go straight to the previous item, turn off **Previous goes back to the start of the file first** in Preferences > Playback. With nothing before it, Previous starts the file again instead of doing nothing.

### Fixed
- **Text on a light accent colour (#63).** With a light accent such as yellow, the highlighted entry in drop-down lists and selected text in text boxes were white on the accent colour and hard to read. That text is now dark on light accent colours and white on dark ones, the same as the play button.

### Downloads
| | Download |
|---|---|
| Windows 10/11 (64-bit) | `Pylon-Setup-1.6.2.exe` (installs over earlier versions, settings kept) |
| Linux x86-64 | `Pylon-1.6.2-x86_64.AppImage` |
| macOS 14+ (experimental) | `Pylon-1.6.2-macOS.zip` |

Install VLC separately. Checksums are in `SHA256SUMS.txt`. Not affiliated with VideoLAN.

### Testing
New automated checks (`tests/check_close_prev_ratios_sort.py`) cover the following:
- **Previous:** a first press past 3 seconds restarts the file with the hint, a press near the start goes back, the preference turned off always goes back, there's a fallback when nothing comes before, and the Preferences switch works.
- **Close the video:** the button sits right of the menu, Ctrl+W doesn't clash with another key, and closing unloads the file, saves the position, keeps the queue and shows the home page, from the button and from the key.
- **Ratios:** the new crops are in the rows, the Preferences eyes change the rows in their usual order, and a rebuilt row keeps the chosen crop while C steps on with readable names.
- **Sorting:** there's one entry per sort, the arrow turns the order round and saves it, a new sort starts in its usual direction, Recently played works for playlists, streams and the home page, sorts saved by 1.6.1 still load, and dark or white text is picked for light and dark accents.

The check for **A** stepping through aspect ratios now expects 16:10 after 16:9. All 35 test files pass on Linux (X11). The new layout of the Video tab, the Preferences page and the sort drop-down with a yellow accent was checked in screenshots. Windows hasn't been tried by hand yet.
