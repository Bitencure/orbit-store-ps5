<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# First test on a PS5 (firmware 13.60) without touching your installed Orbit

Nothing in this fork has run on a console yet. This is the safest way to find out whether it does. It uses a separate
**sandbox build**, `orbit_store_sandbox.elf`, and never the regular fork ELF or the fork's FFPKG.

Placeholders: `PS5` is the console's address, `TOOLS` is the folder holding the build (`dist-fork/1.3.5-custom.1/`).

## What the sandbox changes, and what it shares

| | Installed Orbit | Sandbox build |
|---|---|---|
| Queue, tokens, TorBox key, saved links | `/data/orbit-store/` | **`/data/orbit-store-fork-test/`** (nothing is shared or copied) |
| Web interface and API | port 34177 | **port 34178** |
| Home-screen icon (`ORBT00001`), payload-manager and autoload copies, `/data/homebrew` installer | written at start | **never written** |
| Updater and TV-app installer | on | **off** (`orbit.autoboot` is false, so they refuse to run) |
| Native TV app | talks to port 34177 | untouched; it never sees the sandbox |
| Identification | none | toast says **TEST BUILD**; the page shows a notice with a **Stop test build** button; `/api/v1/system` reports `"sandbox": true` |

**What it still shares with your normal setup:** the console itself, its disk and network, the PS5 browser, and the
download folder `<drive>/homebrew/` (every pasted-link file lands there). Orbit never overwrites an existing file
("Destination file already exists"), but give test files a **unique name** and never use `PPSA99177.ffpkg`.

**What this cannot prove:** that the ELF loads on 13.60 with your loader. That is what the test is for. The sandbox is
built from the same source, SDK (v0.43) and libraries as upstream's ELF; the only difference is the flag.

> **Do not** install the fork's FFPKG (same title ID as the official app, it replaces it), do not load the regular
> `orbit_store.elf` (at start it writes itself over `/data/orbit-store/orbit_store.elf` and refreshes the payload-manager and
> autoload copies you already have), and do not use
> Orbit Zero's "start Orbit" (it sends the official ELF). See [ORBIT-ZERO.md](ORBIT-ZERO.md).

## 0. Check the files (Linux desktop)

```sh
cd TOOLS && sha256sum -c SHA256SUMS            # orbit_store_sandbox.elf must say OK
ls -l orbit_store_sandbox.elf
```

## 1. Back up the current installation

The sandbox does not write to any of these, so this is insurance, and it gives you a way to prove nothing changed.
Use whichever file access you already have (an FTP payload, a file manager, or a USB copy); the FTP port depends on
the payload you run, so `FTP_PORT` below is yours to fill in. Stop any download in the installed Orbit first (so
`state.json` is not mid-write).

```sh
mkdir -p ~/ps5-backup/before && cd ~/ps5-backup/before
lftp -p FTP_PORT PS5 -e "mirror /data/orbit-store orbit-store; \
  mirror /data/pldmgr pldmgr; \
  mirror /data/homebrew/OrbitStore homebrew-OrbitStore; \
  get /data/homebrew/PPSA99177.ffpkg -o PPSA99177.ffpkg; bye"
# Auto-start lists written by Orbit's "Start automatically": any autoload.txt under /data/ps5_autoloader* and /mnt/usb*/ps5_autoloader*
cd ~/ps5-backup && (cd before && find . -type f -exec sha256sum {} +) > before.sha256 && wc -l before.sha256
# The official files, to go back to (nothing from this fork):
mkdir -p official && gh release download v1.3.5 -R saawant12/orbit-store-ps5 -D official -p orbit_store.elf -p PPSA99177.ffpkg -p SHA256SUMS
(cd official && sha256sum -c SHA256SUMS --ignore-missing)
```

Write down: which loader you use for ELFs, whether the installed Orbit is running, and its pairing state.

## 2. Launch the sandbox ELF manually

Send it once, the way you send any ELF (port 9021 is the usual ELF-loader port; use your loader's own address if it
differs). Do not add it to any autoload list.

```sh
nc -w 5 PS5 9021 < TOOLS/orbit_store_sandbox.elf
```

If you use Payload Manager, upload and **run once**; do not choose "autoload".

Expect, within a few seconds, a console toast like `Orbit Store TEST BUILD :34178 | Pair: 123456 | Server ready`.

```sh
curl -s http://PS5:34178/api/v1/system | python3 -m json.tool | grep -E '"(name|version|forkTag|sandbox|httpPort|platform)"'
#  name "Orbit Store", version "1.3.5", forkTag "custom.1", sandbox true, httpPort 34178, platform "ps5"
curl -s http://PS5:34177/api/v1/system | grep -o '"forkTag"' || echo "installed Orbit still answers on 34177 without a fork tag"
```

Open `http://PS5:34178/` on the desktop, enter the pairing code from the toast, and confirm the **Test build** notice at
the top. There must be **no new icon** in the Media tab.

**Stop here and tell me if:** nothing answers on 34178, the toast never appears, the console freezes, or
`/api/v1/system` on 34177 changed. To stop the sandbox at any time: press **Stop test build** on its page.

## 3. A small, legitimate direct URL

In the sandbox page: **Download sources** → turn on **Direct links** and accept the notice. Then open **Add a download
link** (link icon in the Store header, or Settings → Add a download link). Use a file the host publishes for testing:

- small: `https://proof.ovh.net/files/10Mb.dat` (10 MiB; OVH publishes it for speed tests, with `Accept-Ranges`, `ETag`
  and `Last-Modified`)
- larger, for step 4: `https://github.com/saawant12/orbit-store-ps5/releases/download/v1.3.5/Orbit-Zero-1.3.5-linux-arm64.deb`
  (116 MB, a public release asset that redirects to GitHub's CDN; upstream's `SHA256SUMS` lists its hash). It is only a
  test file; do not install it. OVH's server stopped answering during my own desktop rehearsal when I asked it for
  several downloads in a few minutes, so for the repeated pause and resume tests use the GitHub file.

Paste it, expect the file name, the size and "can resume". Set **Save as** to something unique (for example
`orbit-fork-test-10mb.bin`), pick the internal drive under **Save to**, and press **Add to Downloads**.

Check the result on the desktop:

```sh
curl -sL https://proof.ovh.net/files/10Mb.dat | sha256sum           # reference (for the large file, upstream's SHA256SUMS)
lftp -p FTP_PORT PS5 -e "get /data/homebrew/orbit-fork-test-10mb.bin -o /tmp/got.bin; bye" && sha256sum /tmp/got.bin
```

Pass: the two hashes match and the job shows Complete.

## 4. Pause, resume and storage selection

Rehearsed on the Linux desktop with the same service code and the real GitHub file: paused at 20.7 MB, resumed from
the saved 21.6 MB (not from zero), finished, and the SHA-256 matched upstream's published value. The same steps have not
been run on a console.

1. Add the 116 MB file as `orbit-fork-test-large.bin`. While it is running, **Pause** it. The progress must stop, and a
   `.part` file must stay in `/data/homebrew/`. **Resume** it. Pass: it finishes and the hash matches the reference.
2. Delete that file, add it again as `orbit-fork-test-large2.bin` and, while it runs, press **Stop test build**. Run the ELF again (step 2) and open
   the page. Pass: the job is listed as paused, resumes, and finishes with a matching hash. (This is the restart
   recovery path.)
3. Plug in a USB drive (`/mnt/usb0`) and repeat step 3 choosing it in **Save to**. Pass: the file is in
   `/mnt/usb0/homebrew/`. The sandbox's own **Storage and downloads** page holds a separate default drive; the installed
   Orbit's setting must be unchanged.
4. Remove the drive while a download is queued to it. Expected (this is upstream's behaviour, not tested here): Orbit reports the drive is missing and keeps the partial file; it
   does not write to another drive.

## 5. Browser-assisted downloads

Upload your own 1 KB random file through the normal website of one of the hosts (so the link is yours):

```sh
head -c 1024 /dev/urandom > orbit-fork-probe.bin     # then upload it at vikingfile.com, or rootz.so, in a desktop browser
```

Paste the link into **Add a download link**. Expected for Vikingfile and Rootz: the panel shows the name and size (Vikingfile
reads them from its public listing; Rootz learns them when the link appears) and an **Open Vikingfile on PS5** button
(Rootz: **Open Rootz on PS5**). Press it, finish any verification and press the host's own Download button in the PS5 browser. Pass: Orbit captures the link,
checks it against the host's rules, queues the file, and the browser returns to `http://127.0.0.1:34178/`.

What each result means:

- **Captured and complete, hash matches your original file:** the browser step works on 13.60.
- **"Captured link does not match the file the provider named. Nothing was queued.":** Orbit refused something that
  did not match. Safe; tell me what the page showed.
- **Nothing captured:** the PS5 browser memory scan did not see a link. Safe; this is the part that most needs a console.

1Fichier, DataNodes and AkiraBox use the same flow but have only been tested against mocks. Try them only with a file
you are allowed to download.

## 6. TorBox with your existing account

The sandbox has its own, empty settings, so it does not know your key. Enter it on the sandbox page: **TorBox** →
**Connect TorBox**. The key is stored in `/data/orbit-store-fork-test/` and goes away with step 8.

1. Pass: it shows **TorBox connected**.
2. Paste a Vikingfile or 1Fichier link of your own (a host on TorBox's list). Pass: the panel offers a **TorBox** choice;
   select it and press **Download via TorBox**; the item appears in your TorBox dashboard, and the file arrives in `/data/homebrew/` with the right hash.
3. Paste a link from a host TorBox does not list (for example a plain `https` file). Pass: no TorBox option is offered.
4. Paste a dead link on a listed host. Pass: a plain message such as "TorBox says this link is offline or has been
   removed", and nothing is left half-queued.

Orbit waits about 61 seconds between link submissions to TorBox; that pause is intended. Gofile and FuckingFast links work
only through TorBox.

## 7. Prove the installed Orbit was not touched

```sh
mkdir -p ~/ps5-backup/after && cd ~/ps5-backup/after
lftp -p FTP_PORT PS5 -e "mirror /data/orbit-store orbit-store; mirror /data/pldmgr pldmgr; mirror /data/homebrew/OrbitStore homebrew-OrbitStore; get /data/homebrew/PPSA99177.ffpkg -o PPSA99177.ffpkg; bye"
cd ~/ps5-backup && (cd after && find . -type f -exec sha256sum {} +) > after.sha256 && diff before.sha256 after.sha256 && echo UNCHANGED
```

Expected: `UNCHANGED`. If the installed Orbit was running and busy, its own `state.json` may differ; anything else
differing is a failure of the sandbox, so stop and tell me.

## 8. Go back to the official build

Nothing was replaced, so going back is just cleaning up:

1. Press **Stop test build** (or restart the console, which ends every payload).
2. Delete the sandbox's folder and your test files: `/data/orbit-store-fork-test/`, `/data/homebrew/orbit-fork-test-*`,
   and anything you saved to a USB `homebrew` folder. This also removes the TorBox key you typed. In TorBox's own
   dashboard, remove the test items if you want.
3. Start the installed Orbit the way you always do. Check `http://PS5:34177/` and the Media tab icon.

**If something went wrong with the installed Orbit anyway:**

1. Stop everything (restart the console and re-run your jailbreak).
2. Copy `~/ps5-backup/before/orbit-store` back to `/data/orbit-store` (this restores the queue, settings and saved payload copy),
   `pldmgr` to `/data/pldmgr`, and `PPSA99177.ffpkg` to `/data/homebrew/`.
3. Load the official `orbit_store.elf` from `~/ps5-backup/official/` (checked against upstream's `SHA256SUMS`).
4. If the queue file was written by the fork with a pasted link in it, the official build may refuse it. Move
   `state.json` aside to start with an empty queue; downloaded files are not affected.

## What to send back

For each step: pass or fail, the toast text, the `/api/v1/system` output, any message the page showed, the PS5 firmware
and loader, and whether the console stayed stable. Do not paste your TorBox key or pairing tokens.

## Limits of this procedure

- Every step above is **unverified on hardware**. The service, the page and the capture rules were exercised on a Linux desktop
  against local mock servers and a few real public hosts.
- The FTP commands assume a standard FTP payload. Different payloads use different ports and sometimes different root paths.
- Browser capture (step 5) reads memory of the PS5 browser. That depends on firmware and browser version and is the part most
  likely to need adjustment.
