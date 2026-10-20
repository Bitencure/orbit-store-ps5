<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Hardware retest: only what failed or was inconclusive the first time

The first hardware test passed these and they are **not** repeated: starting the sandbox, the installed Orbit staying
independent, a 10 MiB HTTPS download (internal and USB, hashes matched), pause and resume of the 116 MB file (hash matched),
and the final backup comparison (`UNCHANGED`). The report is in `~/ps5-backup/FIRST-TEST-REPORT.md`.

This build is **custom.2**. Nothing below has been verified on a console; each step says what would count as a pass. **Do not treat
browser capture or real TorBox downloads as working until you have seen them work here.** Do one test, send the result, then the next.

Placeholders as in [FIRST-TEST.md](FIRST-TEST.md): `PS5`, `FTP_PORT` (2121 last time), `TOOLS` = `dist-fork/1.3.5-custom.2/`.

## R0. Start the new build (2 minutes)

```sh
cd TOOLS && sha256sum -c SHA256SUMS --ignore-missing       # orbit_store_sandbox.elf: OK  (hash is in FORK.md and in my message)
socat -t 5 -u FILE:orbit_store_sandbox.elf TCP:PS5:9021     # or nc -w 5 PS5 9021 < orbit_store_sandbox.elf
curl -s http://PS5:34178/api/v1/system | python3 -m json.tool | grep -E 'forkTag|sandbox|httpPort'
```

Pass: `"forkTag": "custom.2"`, `"sandbox": true`, `"httpPort": 34178`. Pair as before. Send me: whether a toast appeared this time, and the
console's real firmware, which the page does not show (its "targetFirmware" is upstream's label, not yours):

```sh
export TOKEN=$(curl -s -X POST http://PS5:34178/api/v1/pair -d '{"code":"CODE"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -H "Authorization: Bearer $TOKEN" http://PS5:34178/api/v1/diagnostics | python3 -m json.tool | grep -E '"firmware"|loader'
```

(Keep `$TOKEN` to yourself: it is a pairing token. The sandbox's state folder, and with it every token, is deleted at the end.)

## R1. TorBox: the host check (was the main bug)

Cause found: the first build kept only the first 256 of TorBox's 378 listed domains, and Vikingfile is number 339 to 341.

1. On the sandbox page: **TorBox** → **Connect TorBox**, paste your key. (The sandbox has its own empty settings, so this is a new
   connection; the key goes away with the state folder in R6.)
2. `curl -s -H "Authorization: Bearer $TOKEN" http://PS5:34178/api/v1/debrid | python3 -m json.tool | grep -E 'connected|listedDomains|error'`
   Pass: `"connected": true` and `listedDomains` around 378 (anything above 256).
3. Upload your own 1 KB file to vikingfile.com and paste its link into **Add a download link**. Pass: Orbit shows the name and size and
   **both** "PS5 browser" and "TorBox" as choices (it said "TorBox does not list this host" before). Try the `vik1ngfile.site` form of the link too.
4. Choose **TorBox**, pick the drive (read the "Saves to" line), press **Download via TorBox**. Pass: it appears in your TorBox dashboard
   and the file lands in `<drive>/homebrew/` with the right hash. Orbit waits about 61 seconds between submissions; that is intended.
   **This is the first real TorBox download of this fork, so tell me exactly what the panel and the Downloads list say at each stage.**
5. Paste a link TorBox does not host (your Rootz link): Pass: no TorBox choice. Paste a deleted Vikingfile link:
   Pass: a plain message from Orbit (the file no longer exists) or from TorBox ("…offline or has been removed"), and nothing queued.

Do not paste your TorBox key anywhere except the sandbox page. `/api/v1/debrid` never contains it, and nothing here asks for it.

## R2. Progress, cancel and recovery, repeatably

A click cannot cancel a 6-second download reliably. This tool acts at exact byte counts and checks the files over FTP:

```sh
python3 tools/fork/hardware-check.py --ps5 PS5 --code CODE --ftp-port FTP_PORT --drive usb0     progress cancel-delete cancel-keep
python3 tools/fork/hardware-check.py --ps5 PS5 --code CODE --ftp-port FTP_PORT --drive internal progress cancel-delete cancel-keep
python3 tools/fork/hardware-check.py --ps5 PS5 --code CODE --ftp-port FTP_PORT --drive usb0     restart     # asks you to send the ELF again
```

(Direct links must be on in the sandbox page. `CODE` is the sandbox's pairing code; use "Show code on PS5" for a fresh one. It
prints no token, and deletes only the `orbit-fork-hw-*` files it made.)

What the checks mean (details in [PROGRESS.md](PROGRESS.md)):
- **progress** prints the counter next to the `.part` file's size every 0.4 s. The `.part` file is allowed to be **bigger** than the counter,
  by a lot on internal storage (8 parallel ranges) and by very little on USB. Pass: the file is never *shorter* than the counter, nothing moves
  while paused, resume finishes, the `.part` file is gone at the end, and the hash matches. Send me the table for both drives.
- **cancel-delete** pass: cancelled, `.part` removed, no finished file. **cancel-keep** pass: `.part` kept and not growing, history refuses to drop
  the entry, **Delete download** removes the partial.
- **restart** pass: the job is still listed after the restart with progress above zero, resumes, hash matches. Expect to lose about two
  seconds of progress on a hard stop (and up to one 8 MiB window on USB).

## R3. Browser-assisted downloads

The service now tells you what the browser scan did. While Orbit is waiting, in a second terminal:

```sh
curl -s -H "Authorization: Bearer $TOKEN" http://PS5:34178/api/v1/browser | python3 -m json.tool
```

It holds only counts and one sentence, never a link: `timing.browserProcesses` (0 means no browser network process was found),
`scannedBytes` and `readableBytes` (how much memory was read; a big gap means reads failed), `readFailures`, `passes` (complete
sweeps), `candidates` (links found), `rejected` and `lastRejection` (links found but refused, and why).

**R3a. Vikingfile on the PS5 browser.** Paste your Vikingfile link, press **Open Vikingfile on PS5**, pass Cloudflare's check, then
**do not press Download** and **wait up to two minutes**. Pass: the banner says "Added to Downloads". If it does not, send me the JSON above
taken at about 30, 60 and 100 seconds, and the banner text (it now says "Orbit found a link but could not use it: …" when that is the case).
- `candidates` 0 and `passes` 0 or 1: the scan is too slow or reads nothing: a memory-scan problem.
- `candidates` ≥ 1 and `lastRejection` set: the link was found and the file server refused or did not match it: a validation problem, and the
  sentence says which.

**R3b. Vikingfile through your computer (the new fallback).** On the page's card open "Can't finish it on the PS5? Use your computer
instead". On your computer open the same Vikingfile page, pass the check, and **right-click the Download button → Copy link address** (do not
click it). Paste it into the box and press **Check and add this link**. Pass: Orbit checks it and adds the file; the hash matches. If it fails,
the banner says why. The link is single-use or short-lived on some hosts, so paste it promptly.

**R3c. Rootz (optional, expect a poor result).** Rootz opens an advertising tab on every Download click. Only try the computer route: finish it in
a desktop browser (it may need you to wait on, and close, the ad tab), copy the final `cdn-files.alcyone.so` link from your browser's download
list, and paste it as in R3b. Tell me if it works at all.

## R4. Destination and defaults

During R1 to R3 note, and tell me if any is wrong: the **Save to** default (a mounted USB drive wins unless you set a default in
Settings → Storage and downloads), the "Saves to …" line under it, and the "Saving to …" line on every active job in Downloads.

## R5. Toast (low priority)

Press **Show code on PS5** on the pairing dialog once. Did a toast appear? (The same call sends the start-up toast, which was not seen.)

## R6. Clean up and compare

As in [FIRST-TEST.md](FIRST-TEST.md) test 8 with its corrected paths: **Stop test build**, delete `/data/orbit-store-fork-test/` (this removes the
TorBox key and every token), delete your test files and `.part` files on **every drive you used** (list first, delete only your own names), then
mirror the same paths as before and `diff` against `before.sha256`. Pass: `UNCHANGED`.
