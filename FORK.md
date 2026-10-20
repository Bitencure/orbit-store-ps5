# Orbit Store, unofficial fork

An **unofficial, community fork** of [Orbit Store](https://github.com/saawant12/orbit-store-ps5) by saawant12. It is not
affiliated with or endorsed by the upstream project. Upstream copyright and attribution are kept and the code remains
**GPL-3.0-or-later** (see `LICENSE`, `THIRD-PARTY-NOTICES.md`).

**Licence and attribution.** Upstream's `LICENSE`, `THIRD-PARTY-NOTICES.md`, `licenses/` and every upstream file header are
unchanged on `source` and `dev` (verified byte-identical to the release bundle). New files carry
`SPDX-License-Identifier: GPL-3.0-or-later`. [`docs/upstream-bundle/`](docs/upstream-bundle/README.md) keeps upstream's list of
the third-party source archives; a binary release of this fork must offer that corresponding source too.

Branches: `main` mirrors upstream's docs and catalogue feeds · `source` holds unmodified upstream source bundles
(`src-v1.3.5` = release v1.3.5, bundle sha256 `c0fe51d94b199daa77b620b5d596afc13b77902076db313891885d0e54339858`)
· `dev` is that source plus this fork's changes (this branch).

## What it adds

- **Add a download link.** Paste a URL; Orbit checks it, shows the file name, size and delivery choices, and queues it
  to a drive you pick, through the normal queue (pause, resume, retry, cancel, partial recovery, archive extraction).
- **More hosts**, matched by their real domain (see the matrix). Each is marked verified, partly verified,
  unverified or not supported, with the evidence.
- **Name and size learned from the provider.** For browser-assisted hosts Orbit no longer asks you to type them: it
  reads them from the file the provider itself serves, and refuses the link if they do not fit the host's rules.
- **Resume that is checked, not assumed.** A partial file continues only if the host proves it is the same file.
- **New link for an expired download.** Paste a fresh address; Orbit resumes only if size and validators match.
- **Saved links.** A local, importable JSON list of your own links ([format](docs/custom-catalogue.md)). Upstream's
  encrypted catalogue is never modified, so upstream catalogue updates keep working.
- **TorBox for pasted links**, only when your account is connected and TorBox's own live host list names the host,
  with plain messages for links TorBox rejects.
- **A computer fallback for browser-assisted downloads.** If the PS5 browser cannot finish a provider's steps, finish them in your
  computer's browser, copy the Download button's link, and paste it into the panel. It is held to the same checks as a link read
  from the PS5 browser (route shape, host allowlist, address guard, the file's own name, size and validators).
- **The destination is always visible**: the panel shows the full path before you add a file ("Saves to /mnt/usb0/homebrew/…"), and
  Downloads shows "Saving to …" for active jobs. A mounted USB drive is the default unless you set another.
- **Plain explanations of progress.** The counter is durable progress; the `.part` file can be longer ([docs/PROGRESS.md](docs/PROGRESS.md)).
- **A hardware check tool** (`tools/fork/hardware-check.py`) that cancels, pauses and restarts at exact byte counts and checks the files
  over FTP, because a click cannot cancel a six-second download.
- **A sandbox build for the first run** (`orbit_store_sandbox.elf`): its own state folder and port, no icon,
  updater, installer or autostart writes. See [docs/FIRST-TEST.md](docs/FIRST-TEST.md).
- The in-app updaters read **this fork's** feeds, so an official build is never offered over it.

Everything else (appearance, favourites, Archive.org sign-in, AkiraBox/Vikingfile catalogue downloads, TorBox, the queue
format for people who never paste a link) is upstream's code, unchanged.

## Support matrix (pasted links)

"Verified" means what I could observe on **2026-10-20**: on a Linux desktop against mocks and live hosts, and, where a row says
so, on the first hardware test of the sandbox build (a PS5, report kept outside the repository). Browser capture and real TorBox
downloads have **not** been seen to work on a console.

| Host | Route for a pasted link | TorBox | Status |
|---|---|---|---|
| Any public `https://` file | Direct, after a one-request check. Resumes only if the host honours byte ranges and sends an ETag or Last-Modified | Only if TorBox lists the domain | **Verified, including on hardware.** Integration tests against mocks; real files on the desktop (GitHub's release CDN, a 10 MiB OVH file). On the PS5 (first hardware test): a 10 MiB file to internal storage and to USB, and a 116 MB file paused and resumed on USB, all with matching SHA-256 |
| Rootz | PS5 browser step (name and size read from the provider's file link), or the computer route | Not offered (not on TorBox's list) | **PS5 browser: failed on hardware.** Every press of Rootz's Download opens an advertising tab and the PS5 browser never reached a usable link (I reproduced the ad tab on a desktop browser; it is how Rootz's free download works). **Pasting a real CDN link:** verified live on the desktop (resolved, validated, name and size learned, byte-identical). The computer route has not been tried on a console |
| Vikingfile | PS5 browser step (name and size from its public file listing), or the computer route | Yes, when connected. The first hardware test found the link dialog refusing it although settings listed it: fixed (see below), **not yet seen working on a console** | Listing **verified live**. The page shows a Cloudflare Turnstile check, so a person must pass it. **PS5 capture: failed on hardware**: Orbit had found a link and refused it (the banner said it was waiting for a fresh one), and the reason was not recorded; this build reports it. The computer route is **unverified** on hardware |
| 1Fichier | PS5 browser step, name and size learned at capture; or TorBox | Yes, when connected | **Unverified** against the real site (mocks only) |
| DataNodes | Same as 1Fichier | Yes, when connected | **Unverified** |
| AkiraBox | Same as 1Fichier | Not on TorBox's list | **Unverified** |
| FileDitch | **Partly:** confirms the file exists through its documented, open status endpoint, then refuses the download with the reason | Not on TorBox's list | **Partly verified (live).** Its file links answer plain HTTP with a Cloudflare human-verification challenge (`cf-mitigated: challenge`); Orbit does not try to answer it |
| Gofile | **TorBox only** | Yes, when connected | Direct is **not possible**: the guest API answered `error-notPremium` (live) and the link is bound to a session cookie. TorBox path mock-tested only |
| FuckingFast | **TorBox only** | Yes, when connected | Its page sits behind a Cloudflare challenge (live). TorBox path mock-tested only |
| Archive.org | Catalogue entries unchanged. A pasted `archive.org/download/…` link is an ordinary direct link | Only if listed | Public files only; a login-only file gets the host's "needs a login" message |

**Can a person clear the challenge and Orbit use the result?** Rootz, Vikingfile, 1Fichier, DataNodes and AkiraBox: yes,
that is the existing browser-assisted flow, which the fork now offers for pasted links. For FileDitch, Gofile and
FuckingFast the file link is bound to cookies the browser holds (Cloudflare's `cf_clearance`, Gofile's `accountToken`),
tied to that browser's fingerprint. Orbit could in principle read them from the PS5 browser's memory the way it reads
links, but I did not build that: it cannot be checked without a console, and it would reuse a clearance rather than
a plain link. They are left as above.

**TorBox audit.** Orbit uses TorBox's web-download calls (create, list, request download link) and its live hoster
list. It offers TorBox for a pasted link only when that list names the link's domain (or a subdomain of it) and the
file fits the host's size limit. Rejections are mapped to plain messages (link offline or removed, host switched off,
too many active downloads, monthly limit, rate limit, TorBox busy), each tested against a mock. Creation is spaced
about 61 seconds apart. This audit found and fixed one bug of mine (a use after free on the failure path). It was
**not** run against a real TorBox account.

**About the names you listed.** Akia, Viki and Data are consistent with AkiraBox, Vikingfile and DataNodes, and Dith with
FileDitch, but nothing in upstream's source or in the hosts' own sites confirms those short names. Names ending in `1`
were not found anywhere. They are treated only as search aliases, never as a way to classify a link.

A provider is offered only for what its real flow returned. If a host later removes its challenge or adds a public API,
re-run `tools/fork/host-build.sh build/orbit-live && python3 tests/live_hosts.py --yes` before changing its entry in
`backend/hosts.c`.

## Since the first hardware test (build custom.2)

The first test of the sandbox build on a PS5 left Orbit's installed copy untouched (backup comparison `UNCHANGED`), and direct downloads,
USB and internal storage, and pause/resume worked. Changes made from what it found:

- **TorBox host detection (fixed, found by reading TorBox's real answer).** The fork kept only the first 256 of TorBox's 378 listed
  domains, and Vikingfile is number 339 to 341, so pasted Vikingfile links were refused while the settings page (which maps every domain)
  showed it available. The table now grows to fit; host matching is unchanged (the link's host must equal a listed domain or be a
  subdomain of it). `/api/v1/debrid` reports `listedDomains`. The key is never logged or returned.
- **Browser-assisted downloads.** The banner "Waiting for a fresh download link…" appears only after Orbit *found* a link and refused it, so the
  first Vikingfile attempt was a rejected link, not a missed one; the likely reason is that the first guide told you to press the page's own
  Download button, which uses up a single-use link. The session now reports the reason (a sentence, never an address) and counts
  (processes, bytes read, read failures, passes, links found and refused). The computer route is the fallback. The Vikingfile page is behind a Cloudflare
  Turnstile and Rootz's is ad-gated, so a person is needed either way; nothing automates or bypasses either.
- **Progress counter vs `.part` file.** Not a bug: the counter is durable progress, the file is the furthest byte written ([docs/PROGRESS.md](docs/PROGRESS.md)).
- **Cancel and recovery.** New deterministic tests (a 48 MiB file held at an exact byte count) for progress, cancel with and without deleting
  the partial, resume after cancel, restart after a clean stop and after a kill, and a tampered partial, in both the range and USB layouts.
  They also found that a test restart dropped the layout setting (a test fix), and that saved links loaded after the web server started
  (moved before it).
- **Documentation and interface.** USB-default storage, the `socat` alternative to `nc`, backup and cleanup paths (the installed TV-app
  package was on USB), unique file names, the missing toast, and the visible destination.

## Which parts must match

| You want | PS5 service (`orbit_store.elf`) | Native app (`PPSA99177.ffpkg`) | Orbit Zero |
|---|---|---|---|
| Pasted links, new hosts, saved links, TorBox for links (in the browser version) | **fork** | any | not supported |
| Native **More settings → Add a download link** button | **fork** | **fork** | not supported |
| Only existing features | either | either | upstream's |

The fork service keeps upstream's version number (`1.3.5`) because upstream's apps compare it; the fork's own tag
(`custom.2`) is reported as `forkTag` by `/api/v1/system`. The official native app 1.7.0 should keep working against
the fork service (the API only gained fields) but this was **not tried on a console**.

**Orbit Zero** (the desktop app) cannot use pasted links: it talks to the console only about catalogue releases and
its own transfers. The browser interface is the practical alternative. Details: [docs/ORBIT-ZERO.md](docs/ORBIT-ZERO.md).

## Install on a jailbroken PS5 (firmware 13.60)

This fork does not change anything about your jailbreak, ELF loader, kstuff or ShadowMountPlus. Whether those work on
13.60 is up to your setup. Follow upstream's [getting-started guide](https://github.com/saawant12/orbit-store-ps5/blob/main/guides/getting-started.md);
only the files differ.

**First time: use the sandbox build and follow [docs/FIRST-TEST.md](docs/FIRST-TEST.md).** It runs beside your installed
Orbit without touching its queue, settings, icon, payload-manager copies or update feed.

The regular fork ELF is different. Like the official one, at start it writes itself to `/data/orbit-store/orbit_store.elf`
and refreshes the payload-manager and autoload copies you already have, and it uses the same state folder as the
installed Orbit, so it **replaces** your installed Orbit.
Only use it once the sandbox test has gone well and you have the backup from the first-test guide.

1. Build the files ([below](#build-it-yourself)) or take a fork release if one is published. Check them against
   `SHA256SUMS`: `sha256sum -c SHA256SUMS`.
2. **Browser version:** load `orbit_store.elf` with your payload manager or ELF loader, exactly as for the official one.
   Open Orbit Store from the Media tab, then **App settings → Download sources** and turn on **Direct links** (and any
   other host you want). You must have accepted the download notice there; pasting a link never bypasses it.
3. **Native app (optional):** the fork's `PPSA99177.ffpkg` uses the **same title ID as the official app**, so it
   replaces it. Keep a copy of the official FFPKG so you can go back. Copy the fork's file to `/data/homebrew/` and let
   ShadowMountPlus register it. If an older Orbit service is running, stop it first (App settings → Updates → Stop Orbit).
4. Use it: in the browser version press the link icon in the top bar (Store look) or **Settings → Add a download link**
   (other looks), or from the native app **More settings → Add a download link**.

To go back to the official build, load the official `orbit_store.elf` and copy the official FFPKG back; the queue
file stays readable unless it holds a pasted link (see Limits).

## Build it yourself

Linux without containers (host service and tests only):

```sh
python3 -m venv .venv && .venv/bin/python tools/bootstrap.py && npm ci && npm run build
tools/fork/host-build.sh               # build/orbit-host, build/orbit-test, build/orbit-hosts-test
tools/fork/host-build.sh build/orbit-sandbox-test   # the sandbox flags on the host, for the Sandbox tests
./build/orbit-hosts-test               # 131 unit checks
python3 tests/custom_integration.py    # 92 integration tests (local mock servers only)
npm test                               # web unit tests (drive choice)
tools/fork/host-build.sh build/orbit-live && python3 tests/live_hosts.py --yes   # opt-in; contacts real hosts
```

PS5 ELF and TV app (Podman or Docker; needs network the first time):

```sh
ORBIT_SOURCE_BUNDLE=~/Downloads/orbit-store-1.3.5-source-bundle.zip tools/fork/build-ps5.sh
python3 tools/fork/make-feeds.py       # regenerate fork-payloads.json / fork-tv-app.json
```

The script follows `BUILDING.md` exactly and writes `dist-fork/<version>-<tag>/` with `SHA256SUMS`. Notes from the
build I ran:

- Podman needs an unqualified-registry setting for upstream's short image names; the script header shows a
  per-shell override that touches no system file.
- The TV app's OpenGL SDK download address (`blackbearreloaded/ps5-opengl`) returned 404 on 2026-10-20. The source bundle
  contains the same archive; `ORBIT_SOURCE_BUNDLE` unpacks it and upstream's script still verifies its checksum.
- Native unit tests build with the host compiler: `app/tools/build-tests.sh` (needs `ninja` and `libwebp`; set
  `USE_CCACHE=0` without ccache). 180 tests pass (176 upstream's, 4 new).

**Artifacts from my build** (source tree of commit `e5c5891`, build `custom.2`, Podman 6.1.4, 2026-10-20; nothing was installed or uploaded):

| File | Size | SHA-256 |
|---|---|---|
| `orbit_store.elf` | 42,593,728 | `f71c1b8d46021db924bf2d79665c7289ffb5e7593c747149f8996dffe99fb88b` |
| `orbit_store_sandbox.elf` | 22,069,120 | `ca78f16e64cd50776c1b1dc9ad0393bcc7d5002d041ec578c1a937d8e98fdb0c` |
| `PPSA99177.ffpkg` | 114,294,784 | `9f6071e369dac962299f3d351dd1ea39e7a05ff70965dbc2e72f32f99f9ef975` |

**Check them yourself.** `tools/fork/verify-build.sh dist-fork/1.3.5-custom.2/SHA256SUMS` checks the hashes; add `--rebuild` to
export the committed tree with `git archive`, rebuild both ELFs from scratch in a temporary folder and compare. A later commit
only changed docs, tests or `tools/fork/` scripts if `git diff --stat e5c5891..HEAD -- backend src app Makefile Dockerfile tools/build-deps.sh i18n catalog package.json package-lock.json`
is empty, which is why those hashes still describe the tip. One input is not pinned by this repo: `tools/bootstrap.py` downloads
curl.se's *current* CA bundle (SHA-256 `a41b5d356aea97a529fe27e0f7316d2f9d946d75927476cf9cf1b90637d00505` in my build), which the ELF embeds.
If curl.se publishes a newer one, a rebuild differs by that alone.

What the sandbox can write, and the evidence: [docs/SANDBOX-AUDIT.md](docs/SANDBOX-AUDIT.md) (`tools/fork/audit-writes.sh` repeats the
enforcement run).

`app/tools/verify-package.sh` passed: the FFPKG carries exactly this ELF, its version marker, metadata, executable and
translations match the build. The sandbox ELF is the service only (no embedded runtime, no icon code), and the data
section of each file carries its own default port: 34177 in `orbit_store.elf`, 34178 in the sandbox.

**Reproducibility.** The first rebuild of the *unmodified* upstream 1.3.5 source was deterministic but not
byte-identical to the published ELF (mine `8a954347…`, official `561a8e80…`). Cause found: OpenSSL embeds its build
date, and pinning it (`SOURCE_DATE_EPOCH`, now set in this repo's `Dockerfile`) gives a rebuild that matches the official
file to the byte. It is neither a security nor a compatibility concern. Evidence and the way to repeat it:
[docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md). The fork's own ELF is not byte-identical to upstream's, of course;
it differs by the fork's changes.

## What was and was not tested

| Layer | Result |
|---|---|
| Host filter, URL and filename rules, socket guard (production rules) | 131 checks pass |
| Pasted-link service against mock origins (redirects, HTML and error pages, filenames, Range and range-less hosts, interruption and resume, missing validators, expired link refresh, size change after check, late off-site redirect, saved links, restart, tampered queue, TorBox and Vikingfile mocks, learned names and sizes, hostile names, FileDitch status, the sandbox flags and its stop button) | 92 tests pass, also under AddressSanitizer and UBSan with no report, and inside a read-only jail (`tools/fork/audit-writes.sh`: 7,614 filesystem writes logged, none outside the state and storage folders); the key safety rules were mutation-checked. Includes TorBox answers shaped like the real one (378 domains), pasted links, and progress, cancel and recovery against a 48 MiB file held at an exact byte count |
| Web UI | Type-checks and builds; driven in headless Chromium through add, rename, errors, TorBox-only, the browser step, new-link prompt and all four looks; the sandbox notice and its two-step Stop button were driven against the host sandbox build, and the service exited cleanly |
| Native app | 180 unit tests pass, including the new hand-off. Web unit tests: 5 pass |
| Real hosts | `tests/live_hosts.py`: 8 checks pass (generic CDN file, Vikingfile listing, FileDitch status and challenge, Rootz end to end, Gofile refusal) |
| Desktop rehearsal of the first-test steps | Direct URL, pause, resume and checksum against a real public file, using the production host rules and the real transfer code |
| **PS5 hardware** | First test of the sandbox build (custom.1): start, isolation from the installed Orbit, direct downloads (internal and USB), pause and resume **passed**; Rootz and Vikingfile browser capture **failed**; TorBox connected but the link dialog refused Vikingfile (fixed in custom.2, **not retested**); cancel and restart recovery were **inconclusive**. No FFPKG install, no controller navigation of the new screens. custom.2 has **not been run on a console** |
| Real TorBox account | Connection tested once on hardware. **No real TorBox download has been seen to work** (mock API only) |
| Orbit Zero | Not changed. Its console calls were read from the distributed app; it was not run ([docs/ORBIT-ZERO.md](docs/ORBIT-ZERO.md)) |
| Languages | New strings are in `i18n/en.json` only; the other ten show English |

**Next hardware test:** [docs/HARDWARE-RETEST.md](docs/HARDWARE-RETEST.md), the sandbox build only. The fork is not ready to
replace the installed Orbit, and no browser-assisted host or TorBox download may be called working until it has been seen on a console.

## Keeping the fork current

```sh
git remote -v                          # origin = your fork, upstream = saawant12/orbit-store-ps5

# 1. Docs, guides and catalogue feeds
git checkout main && git fetch upstream && git merge --ff-only upstream/main && git push origin main

# 2. A new upstream release: import its source bundle as one commit on `source`
gh release download vX.Y.Z -R saawant12/orbit-store-ps5 -p 'orbit-store-*-source-bundle.zip' -p SHA256SUMS
sha256sum -c SHA256SUMS --ignore-missing
#   unzip the bundle, check its SOURCE-SHA256SUMS, extract orbit-store-X.Y.Z-source.tar.gz over a clean `source` checkout
git checkout source && git rm -rq . && tar -xzf orbit-store-X.Y.Z-source.tar.gz --strip-components=1
git add -A && git commit -m "Import Orbit Store X.Y.Z source bundle" && git tag src-vX.Y.Z

# 3. Bring it into the fork
git checkout dev && git merge source
```

Files this fork changed in upstream's tree, which are the only places a merge can conflict:
`backend/{api,browser,catalog,debrid,diagnostics,main,orbit,providers,queue,sources,state,transfer,tvapp,updates}.c|h`,
`Makefile`, `Dockerfile`, `i18n/en.json`, `src/{App,Downloads,TvApp,components,types}.tsx|ts`, `src/interfaces/SettingsPage.tsx`,
`src/styles.css`, and in the native app `main.cpp`, `orbit/{browser_handoff,screens}.hpp`, `orbit/settings*.cpp`,
`preview_main.cpp`, `image_app_test.cpp`. Everything else is new (`backend/{hosts,resolve,custom}.c`, `src/{AddLink,SandboxNotice}.tsx`,
`tests/`, `tools/fork/`, `docs/`, this file).

After a merge: rebuild, run `./build/orbit-hosts-test`, `python3 tests/custom_integration.py`, the native tests, rebuild the PS5 files, then
`python3 tools/fork/make-feeds.py`. If upstream bumps `ORBIT_VERSION`, keep `ORBIT_FORK_TAG` and bump only its suffix.
Do not commit anything under `build/`, `dist-fork/` or `.deps/`.

## Limits

- No PS5 hardware verification. Treat browser-assisted hosts as unverified until you try them on the console.
- A pasted link needs a known size: a host that sends no `Content-Length` (and no byte range) is refused. Plain
  text, JSON, XML and HTML responses are refused on purpose, so a genuine `.txt` file cannot be downloaded.
- A queue that holds a pasted link is saved as schema 7. Official builds reject it and refuse to start rather than
  misread it, so finish or remove pasted downloads before going back to an official ELF.
- The fork keeps upstream's native content version (1.7.0) and title ID; installing it replaces the official TV app.
- Native screens cannot type a URL (no practical on-screen keyboard flow); they hand off to the browser version.
- 1Fichier's own download API (`download/get_token`) needs a Premium account and is not used; Gofile's website token
  (`wt`) is obfuscated and deliberately not reimplemented.
- Orbit Zero has no pasted-link feature and none can be added from this repository ([docs/ORBIT-ZERO.md](docs/ORBIT-ZERO.md)).
- The sandbox build is a test aid. It has no updater and no icon, and it is not a release channel.
- Cloudflare- or login-gated hosts that need a human cannot be automated; Orbit shows the reason instead.
