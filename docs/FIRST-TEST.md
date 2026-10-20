<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# First test on a PS5 (firmware 13.60), beside your installed Orbit

Nothing in this fork has run on a console yet. This is the safest way to find out whether it does, and it is meant
to be done **one test at a time**: do a test, look at the result, tell me what happened, then go on.

It uses only the **sandbox build**, `orbit_store_sandbox.elf`. Never the regular fork ELF and never the fork's FFPKG.

Placeholders: `PS5` is the console's address. `TOOLS` is the folder holding the build (`dist-fork/1.3.5-custom.2/`).
`FTP_PORT` is your FTP payload's port (2121 in the first hardware test; it differs between payloads).

> This guide was corrected after the first hardware test (see `FIRST-TEST-REPORT.md` if you kept it). The tests that failed or were
> inconclusive are in [HARDWARE-RETEST.md](HARDWARE-RETEST.md); the rest below is unchanged in substance.

## What the sandbox is

| | Installed Orbit | Sandbox build |
|---|---|---|
| Queue, tokens, TorBox key, saved links | `/data/orbit-store/` | **`/data/orbit-store-fork-test/`** (nothing is shared or copied) |
| Web interface and API | port 34177 | **port 34178** |
| Home-screen icon (`ORBT00001`), payload-manager and autoload copies, TV-app installer | written at start | **never written** (the code is not even linked in: no `sceAppInstUtil*` imports) |
| Updater and TV-app installer | on | **off** |
| Native TV app | talks to port 34177 | untouched; it never sees the sandbox |
| Identification | none | toast says **TEST BUILD**; the page shows a notice with a **Stop test build** button; `/api/v1/system` reports `"sandbox": true` |

It writes to exactly two places: its own state folder, and `<drive>/homebrew/` of the drive you pick for a download.
The read-through behind that claim is in [SANDBOX-AUDIT.md](SANDBOX-AUDIT.md).

**Which drive.** The **Save to** list in Add a download link starts on your saved default drive; with none saved it picks an
external drive if one is mounted, otherwise internal storage. So **with a USB drive attached, files go to `/mnt/usb0/homebrew/`,
not `/data/homebrew/`**, unless you choose otherwise. The panel shows the full destination ("Saves to /mnt/usb0/homebrew/…") and the
Downloads list shows "Saving to …" for every active job; read it before you press the button. Every `homebrew` folder named in
this guide means the one on the drive you chose.

**Shared on purpose or by nature:** the console and its network, the PS5 browser (opened only when you press a
browser-assisted button), your TorBox account, and the download folder `<drive>/homebrew/`. Orbit never overwrites an
existing file there ("Destination file already exists"), but give every test file a **unique name** (`orbit-fork-test-…`)
and never use `PPSA99177.ffpkg` or anything already in that folder.

**Do not touch in the sandbox:** the **Library** page (its actions talk to ShadowMount, which the installed Orbit also
uses), **Payload managers** and **Start automatically** (they refuse to run here, by design), and archives (`.zip`,
`.7z`, `.rar` are extracted into `homebrew/` and, by default, deleted afterwards).

**What it cannot prove:** that the ELF loads on 13.60 with your loader. That is what the test is for.

> **Do not** install the fork's FFPKG, do not load the regular `orbit_store.elf` (it writes itself over
> `/data/orbit-store/orbit_store.elf` and refreshes your payload-manager copies), and do not use Orbit Zero's
> "start Orbit" (it sends the official ELF). See [ORBIT-ZERO.md](ORBIT-ZERO.md).

## Before you start

**1. Check the file** (on the Linux desktop; this changes nothing on the console):

```sh
cd TOOLS
sha256sum -c SHA256SUMS --ignore-missing        # orbit_store_sandbox.elf: OK
sha256sum orbit_store_sandbox.elf
# expected: 9ce87a6d72e466394296a6cdb0d2602669fdd794566cca25378a7e676165981c  (also in FORK.md on the dev branch)
```

To go further than trusting the file, rebuild the pushed commit from scratch and compare:
`tools/fork/verify-build.sh dist-fork/1.3.5-custom.2/SHA256SUMS --rebuild` (needs Podman or Docker and network).

**2. Make sure your usual Orbit is running and healthy**, so the "still independent" check in test 2 means something:
open `http://PS5:34177/` and look. Change nothing. Note how you start it (icon, autoload, payload manager).

**3. Back up (recommended).** The sandbox does not write to these, so this is insurance, and it lets test 8 prove nothing
changed. Use your usual file access (an FTP payload, a file manager, or a USB copy); the FTP port depends on the payload
you run, so `FTP_PORT` is yours to fill in. Pause any active download in the installed Orbit first.

First find where things are: the installed Orbit's state, the payload manager's folder, and its TV-app package, which sits in the
`homebrew` folder of whichever drive it was installed to (on the first test console it was on USB, not `/data`).

```sh
lftp -p FTP_PORT PS5 -e "cls -l /data/orbit-store /data/pldmgr /data/homebrew /mnt/usb0/homebrew /mnt/usb1/homebrew; bye"
# Paths that do not exist on your console print "550 No such file". That is harmless: just skip them below.
mkdir -p ~/ps5-backup/before && cd ~/ps5-backup/before
lftp -p FTP_PORT PS5 -e "mirror /data/orbit-store orbit-store; mirror /data/pldmgr pldmgr; bye"
# The TV-app package (and the Homebrew Launcher entry, if you have one) on the drive where they exist, e.g. USB:
lftp -p FTP_PORT PS5 -e "get /mnt/usb0/homebrew/PPSA99177.ffpkg -o PPSA99177.ffpkg; mirror /mnt/usb0/homebrew/OrbitStore homebrew-OrbitStore; bye"
# Auto-start lists: /data/pldmgr/autoload.txt is covered above; also check /data/ps5_autoloader* and /mnt/usb*/ps5_autoloader*
# (none existed on the first test console).
cd ~/ps5-backup && (cd before && find . -type f -exec sha256sum {} +) > before.sha256 && wc -l before.sha256
mkdir -p official && gh release download v1.3.5 -R saawant12/orbit-store-ps5 -D official -p orbit_store.elf -p PPSA99177.ffpkg -p SHA256SUMS
```

## The tests

After each: note **pass / fail / odd**, the exact text of any message, and whether the console stayed stable. Stop at the
first thing that looks wrong. Stopping the sandbox is always safe: **Stop test build** on its page, or restart the console.

### Test 1: start the sandbox and open its page

1. Send `TOOLS/orbit_store_sandbox.elf` once, the way you send any ELF (port 9021 is the usual ELF-loader port):
   `nc -w 5 PS5 9021 < TOOLS/orbit_store_sandbox.elf`, or, without `nc`,
   `socat -t 5 -u FILE:TOOLS/orbit_store_sandbox.elf TCP:PS5:9021` (this worked on the first test console).
   Payload Manager: upload and **run once**, never "autoload".
2. You may see a toast within a few seconds: `Orbit Store TEST BUILD :34178 | Pair: 123456 | Server ready`. **It was not seen on the
   first test**, although the service was up and answering about eight seconds after the ELF was sent, so do not wait for it.
   Wait for step 3's `curl` to answer instead. If you need the code and saw no toast: press **Show code on PS5** on the page's
   pairing dialog (a second toast; please report whether that one appears), or open `http://127.0.0.1:34178/` in the PS5's own
   browser, which pairs by itself and shows the code under Settings → Pair devices.
3. On the desktop: `curl -s http://PS5:34178/api/v1/system | python3 -m json.tool` and look for `"name": "Orbit Store"`,
   `"version": "1.3.5"`, `"forkTag": "custom.2"`, `"sandbox": true`, `"httpPort": 34178`, `"platform": "ps5"`.
4. Open `http://PS5:34178/` in a desktop browser and enter the pairing code (missed the toast? press **Show code on PS5**).
5. Expect the **Test build** notice at the top, and **no new icon** in the Media tab.

Report: the toast text, the JSON lines above, and what the page looked like.

### Test 2: the installed Orbit still works on its own

1. `curl -s http://PS5:34177/api/v1/system | python3 -m json.tool`: it must answer, with **no** `forkTag` and no `sandbox`.
2. Open `http://PS5:34177/` and the Media-tab icon / native app as you normally do.
3. If your usual Orbit was running before test 1 and is not now, tell me: it means your ELF loader stopped it when
   the sandbox was sent. That is the loader's doing, not the sandbox's; start it again and carry on.

### Test 3: a small public file over HTTPS

In the sandbox page: **Download sources** → turn on **Direct links** and accept the notice. Open **Add a download link**
(link icon in the Store header, or Settings → Add a download link). Paste

`https://proof.ovh.net/files/10Mb.dat` (10 MiB; OVH publishes it for speed tests, with `Accept-Ranges`, `ETag`, `Last-Modified`)

Expect the file name, the size and "can resume". Set **Save as** to `orbit-fork-test-10mb.bin` (a name left at its default, such as
`10Mb.dat`, is easy to forget at cleanup time). Under **Save to** choose the drive you want and read the "Saves to …" line below it
(it is the USB drive if one is mounted and you changed nothing), then press **Add to Downloads**.

Check on the desktop: `curl -sL https://proof.ovh.net/files/10Mb.dat | sha256sum`, and the same for the copy from the console
(`<drive>/homebrew/orbit-fork-test-10mb.bin`, via your FTP). Pass: the job shows Complete and the hashes match.

### Test 4: pause, resume and cancel

Use the 116 MB file, which comes from GitHub's CDN and does not throttle (OVH's server stopped answering during my own
rehearsal after a few downloads). On a fast LAN it finishes in about six seconds (about 19 MB/s on the first test console), so a
click on Pause or Cancel can easily come too late. For a result that is the same every time, use `tools/fork/hardware-check.py`
(see [HARDWARE-RETEST.md](HARDWARE-RETEST.md)); the clicks below are the manual version, and work best with a bigger file.
`https://github.com/saawant12/orbit-store-ps5/releases/download/v1.3.5/Orbit-Zero-1.3.5-linux-arm64.deb`
(a public release asset, used only as test data; do not install it).

1. Add it as `orbit-fork-test-large.bin`. While it runs, press **Pause**. Pass: progress stops, and
   `orbit-fork-test-large.bin.part` stays in `<drive>/homebrew/`. Press **Resume**. Pass: it continues from where it stopped
   and finishes. Hash: upstream's `SHA256SUMS` lists `Orbit-Zero-1.3.5-linux-arm64.deb`.
   (Desktop rehearsal of exactly this: paused at 20.7 MB, resumed from 21.6 MB, hash matched. On the first hardware test the pause and
   resume passed and the hash matched.) The `.part` file's size is **not** the progress: it can be well ahead of the counter. See
   [PROGRESS.md](PROGRESS.md).
2. Add it again as `orbit-fork-test-cancel.bin`, let it start, press **Cancel**, then **Delete partial file** in the dialog
   (**Keep partial file** would leave the `.part` behind). Pass: the job moves to Cancelled and its `.part` file is gone; nothing
   else in `<drive>/homebrew/` changes. Then press **Delete download** on the cancelled entry to clear it.
3. Optional, restart recovery: add it as `orbit-fork-test-restart.bin`, press **Stop test build** mid-download, send the ELF
   again (test 1) and open the page. Pass: the job is listed as paused and resumes to a matching hash.
4. Optional, drive choice: with a USB drive in, repeat test 3 choosing it under **Save to**. Pass: the file is in
   `/mnt/usb0/homebrew/`.

### Test 5: a real Rootz download

Upload a random 1 KB file of your own on rootz.so in a desktop browser (`head -c 1024 /dev/urandom > orbit-fork-probe.bin`),
and copy the share link (`https://rootz.so/d/…`). Paste it into **Add a download link**. Expect **Open Rootz on PS5**, with the
name and size still to be read. Press it; on the PS5 browser complete whatever the page asks, then press the page's own
Download button. Expect Orbit to capture the link, queue the file, and the browser to return to `http://127.0.0.1:34178/`.
Pass: the file completes and its hash equals your original.

Fail modes: nothing captured (the browser-memory scan did not see a link: safe, and exactly what needs a console to learn);
"Captured link does not match the file the provider named. Nothing was queued." (Orbit refused a link that did not fit; safe).
Tell me what the Rootz page showed.

**What happened the first time:** every press of Rootz's Download button opens an advertising tab (`link-file-….website`), and the
PS5 browser kept bouncing between ad pages without reaching a usable link. I reproduced the ad tab on a desktop browser; it is how
Rootz's free download is built, not something Orbit can influence. Use the computer route in
[HARDWARE-RETEST.md](HARDWARE-RETEST.md) instead, and expect Rootz to be a poor fit for a console.

### Test 6: Vikingfile, browser-assisted

Same as test 5 with a file you upload to vikingfile.com (`https://vikingfile.com/f/…`). The panel shows the name and size
read from Vikingfile's public listing, then **Open Vikingfile on PS5**.

**Do not press the page's own Download button.** Vikingfile shows a Cloudflare check; once you pass it, Orbit finds the generated
link by itself ("Complete verification if shown, then wait"). A link that was already used by the browser's own download can no
longer be validated, which is what the banner "Waiting for a fresh download link from the provider…" means: Orbit had found a link and
refused it. The first version of this guide told you to press Download here; that was wrong. See [HARDWARE-RETEST.md](HARDWARE-RETEST.md).

### Test 7: TorBox with your account

The sandbox has its own, empty settings, so it does not know your key. In the sandbox page: **TorBox** → **Connect TorBox** and
paste the key. It is stored only in `/data/orbit-store-fork-test/` and goes away in test 8.

1. Pass: **TorBox connected**.
2. Paste a Vikingfile link of your own. The panel should offer a **TorBox** choice next to **PS5 browser**. Select it, press
   **Download via TorBox**. Expect it in your TorBox dashboard, then the file in `<drive>/homebrew/` with the right hash.
   Orbit waits about 61 seconds between submissions to TorBox; that pause is intended.
3. Paste a plain `https` file link (a host TorBox does not list). Pass: no TorBox choice.
4. Paste a dead link on a listed host. Pass: a plain message such as "TorBox says this link is offline or has been removed".

### Test 8: shut down and prove nothing changed

1. Press **Stop test build** → **Pause downloads and stop**. The page says "Test build stopped" and the port stops answering.
2. Delete `/data/orbit-store-fork-test/` (this removes the TorBox key you typed) and everything you downloaded, **on every drive you
   used**: `/data/homebrew/` and `/mnt/usb0/homebrew/` (and `usb1` if you used it). List them first, then delete only these:
   `lftp -p FTP_PORT PS5 -e "cls -l /data/homebrew /mnt/usb0/homebrew; bye"`. Your files are the `orbit-fork-test-*` names, anything
   you left at a default name (`10Mb.dat`, `10MB.dat`, `Orbit-Zero-1.3.5-linux-arm64.deb`), and their `.part` files. Leave everything
   else, including any `*.exfat.part` that was there before the test.
3. Compare with the backup:

```sh
mkdir -p ~/ps5-backup/after && cd ~/ps5-backup/after
lftp -p FTP_PORT PS5 -e "mirror /data/orbit-store orbit-store; mirror /data/pldmgr pldmgr; bye"
lftp -p FTP_PORT PS5 -e "get /mnt/usb0/homebrew/PPSA99177.ffpkg -o PPSA99177.ffpkg; mirror /mnt/usb0/homebrew/OrbitStore homebrew-OrbitStore; bye"
cd ~/ps5-backup && (cd after && find . -type f -exec sha256sum {} +) > after.sha256 && diff before.sha256 after.sha256 && echo UNCHANGED
```

Expected: `UNCHANGED`. The installed Orbit's own `state.json` may differ if it was busy; anything else differing is a failure of
the sandbox, so stop and tell me. Also check `http://PS5:34177/` and the icon once more.

## If something goes wrong with the installed Orbit anyway

1. Restart the console and re-run your jailbreak.
2. Copy `~/ps5-backup/before/orbit-store` back to `/data/orbit-store`, `pldmgr` to `/data/pldmgr`, and `PPSA99177.ffpkg` to the
   `homebrew` folder of the drive it came from.
3. Load the official `orbit_store.elf` from `~/ps5-backup/official/` (check it against upstream's `SHA256SUMS`).

## Limits of this procedure

- Every test above is **unverified on hardware**. The service, the page and the capture rules were exercised on a Linux desktop
  against local mock servers and a few real public hosts.
- The FTP commands assume a standard FTP payload; ports and root paths differ between payloads.
- Browser capture (tests 5 and 6) reads memory of the PS5 browser. That depends on firmware and browser version and is the part
  most likely to need adjustment.
