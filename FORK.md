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
- **A sandbox build for the first run** (`orbit_store_sandbox.elf`): its own state folder and port, no icon,
  updater, installer or autostart writes. See [docs/FIRST-TEST.md](docs/FIRST-TEST.md).
- The in-app updaters read **this fork's** feeds, so an official build is never offered over it.

Everything else (appearance, favourites, Archive.org sign-in, AkiraBox/Vikingfile catalogue downloads, TorBox, the queue
format for people who never paste a link) is upstream's code, unchanged.

## Support matrix (pasted links)

"Verified" means what I could observe on **2026-10-20 without a PS5**. Nothing was tested on console hardware, so
every browser-assisted row still has an unverified human step on the console.

| Host | Route for a pasted link | TorBox | Status |
|---|---|---|---|
| Any public `https://` file | Direct, after a one-request check. Resumes only if the host honours byte ranges and sends an ETag or Last-Modified | Only if TorBox lists the domain | **Verified.** 58 integration tests against mocks. Real files: GitHub's release CDN (redirect to a signed URL) paused at 20.7 MB, resumed from the saved offset and matched the published SHA-256; a 10 MiB file from OVH came back byte-identical |
| Rootz | PS5 browser step; name and size are read from the provider's file link | Not offered (not on TorBox's list) | **Verified live except the human step.** A real upload resolved, its real CDN link passed Orbit's production rules, the name and size were learned from it and the download was byte-identical. Pressing Download in the PS5 browser is **unverified** |
| Vikingfile | PS5 browser step; name and size from its public file listing | Yes, when connected | Listing **verified live**. Capture tested against a mock; the PS5 browser step is **unverified** |
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
python3 tests/custom_integration.py    # 58 integration tests (local mock servers only)
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

**Artifacts from my build** (source tree of commit `db23c3e`, Podman 6.1.4, 2026-10-20; nothing was installed or uploaded):

| File | Size | SHA-256 |
|---|---|---|
| `orbit_store.elf` | 42,575,016 | `2c5d33e60d0c4b908f0ab712e8c8018cde4b49cc63b5e5c37eb81a3003c555e4` |
| `orbit_store_sandbox.elf` | 22,050,432 | `9ce87a6d72e466394296a6cdb0d2602669fdd794566cca25378a7e676165981c` |
| `PPSA99177.ffpkg` | 114,294,784 | `ed8129c511d03c5ed0cf1fd0b98f0469972291993f5cfc1fdb253e2854eda5b2` |

**Check them yourself.** `tools/fork/verify-build.sh dist-fork/1.3.5-custom.1/SHA256SUMS` checks the hashes; add `--rebuild` to
export the committed tree with `git archive`, rebuild both ELFs from scratch in a temporary folder and compare. A later commit
only changed docs, tests or `tools/fork/` scripts if `git diff --stat db23c3e..HEAD -- backend src app Makefile Dockerfile tools/build-deps.sh`
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
| Pasted-link service against mock origins (redirects, HTML and error pages, filenames, Range and range-less hosts, interruption and resume, missing validators, expired link refresh, size change after check, late off-site redirect, saved links, restart, tampered queue, TorBox and Vikingfile mocks, learned names and sizes, hostile names, FileDitch status, the sandbox flags and its stop button) | 58 tests pass, also under AddressSanitizer and UBSan with no report; the key safety rules were mutation-checked |
| Web UI | Type-checks and builds; driven in headless Chromium through add, rename, errors, TorBox-only, the browser step, new-link prompt and all four looks; the sandbox notice and its two-step Stop button were driven against the host sandbox build, and the service exited cleanly |
| Native app | 180 unit tests pass, including the new hand-off |
| Real hosts | `tests/live_hosts.py`: 8 checks pass (generic CDN file, Vikingfile listing, FileDitch status and challenge, Rootz end to end, Gofile refusal) |
| Desktop rehearsal of the first-test steps | Direct URL, pause, resume and checksum against a real public file, using the production host rules and the real transfer code |
| **PS5 hardware** | **Not tested.** No ELF run, no FFPKG install, no PS5 browser capture, no controller navigation of the new screens |
| Real TorBox account | Not tested (mock API only) |
| Orbit Zero | Not changed. Its console calls were read from the distributed app; it was not run ([docs/ORBIT-ZERO.md](docs/ORBIT-ZERO.md)) |
| Languages | New strings are in `i18n/en.json` only; the other ten show English |

**Ready for a first hardware test?** Yes, with the sandbox build and [docs/FIRST-TEST.md](docs/FIRST-TEST.md) only. Not
ready to replace the installed Orbit, and not ready to claim any browser-assisted host works on a console.

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
