<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# What the progress counter means, and why the `.part` file can be bigger

The first hardware test saw a paused job at "89.4 MB of 116.4 MB (76.8%)" while its `.part` file was 114,662,816 bytes
(98%). Nothing is wrong: they are different measurements. This page records what each one is, with the evidence.

## The counter is durable progress

`received` (the number in the Downloads list and in `/api/v1/downloads`) is the number of bytes Orbit has **written, flushed
with `fsync` and saved in its queue file**. It is deliberately conservative: it never counts a byte that is not on disk at the
right place. Resuming, restarting and crash recovery all start from it, never from the size of the file.

## The `.part` file is the furthest byte written

Which one you see depends on where the download is going:

| Destination | Layout | Counter | `.part` length |
|---|---|---|---|
| Internal storage (`/data`) and any other non-USB drive | 8 equal ranges downloaded in parallel, each with its own saved cursor | the **sum** of the 8 cursors | the end of the **furthest** range written. The last range begins at 7/8 of the file, so the file is soon much longer than the counter and has unwritten gaps in the middle |
| USB (`/mnt/usbN`) | one cursor, with a window of at most 8 MiB fetched ahead and committed whole | that cursor | at most a little ahead of it |

The report's numbers fit the first row. With 8 ranges of 14,553,380 bytes, the last starts at 101,873,660; a file of
114,662,816 bytes means that range had written 12.8 MB of its 14.6 MB while the other seven, on average, had written
10.9 MB, so the sum was 89.4 MB. In the USB layout the counter and the file match at a pause (checked on the desktop with the USB code path; I have not seen
the counter for the hardware's USB job). I could not confirm which drive that particular job was on, so this is "consistent
with", not proof.

## Resuming

A resume continues each range from its own saved cursor. Bytes that are already in the file beyond a cursor are fetched again
and overwritten: after a crash nothing can vouch for them. The tests assert this: after a pause, the bytes fetched on resume
equal the bytes missing (within a few MiB), the final file is byte-identical, and every byte counted at the pause is present in
the file at the right offset with the right content.

## Stopping, crashing, cancelling

- **Pause** and a **clean stop** flush what the writer holds and save the cursors. In the USB layout a window that was still
  arriving is not counted (it is committed whole), so up to one window of progress is fetched again.
- **Progress is saved about every two seconds** while downloading. If the service is killed or the console loses power, the
  download resumes from the last save: at most about two seconds plus the unfinished window are lost. A restarted service lists
  the download as paused with its saved progress.
- **Cancel, then Delete partial file** removes the `.part` file, leaves nothing else in the folder, and the name can be used
  again. **Keep partial file** leaves the `.part` file and the entry (history cannot drop an entry that still owns a partial
  file); the download can be resumed, or the entry deleted later, which removes the partial file too.
- A partial file that no longer matches the saved cursors (for example shortened by hand) is refused with "Partial file size is
  invalid. Delete the partial file before retrying." instead of being trusted.

Covered by `tests/custom_integration.py` classes `Recovery` (range layout) and `RecoveryUsbWindows` (USB layout), against a 48 MiB
file that the test server holds at an exact byte count, so "part-way through" is the same on every run.
