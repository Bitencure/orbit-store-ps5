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
- **More hosts**, matched by their real domain (see the matrix).
- **Resume that is checked, not assumed.** A partial file continues only if the host proves it is the same file.
- **New link for an expired download.** Paste a fresh address; Orbit resumes only if size and validators match.
- **Saved links.** A local, importable JSON list of your own links ([format](docs/custom-catalogue.md)). Upstream's
  encrypted catalogue is never modified, so upstream catalogue updates keep working.
- **TorBox for pasted links**, only when your account is connected and TorBox's own live host list names the host.
- The in-app updaters read **this fork's** feeds, so an official build is never offered over it.

Everything else (appearance, favourites, Archive.org sign-in, AkiraBox/Vikingfile catalogue downloads, TorBox, the queue
format for people who never paste a link) is upstream's code, unchanged.

## Support matrix (pasted links)

"Verified" below means what I could observe on **2026-10-20 without a PS5**. Nothing was tested on console hardware.

| Host | Route for a pasted link | Resume | TorBox | Status |
|---|---|---|---|---|
| Any public `https://` file | Direct, after a one-request check | If the host honours byte ranges and sends an ETag or Last-Modified (checked per link) | Only if TorBox lists the domain | **Verified:** 43 mock-server tests; a real file behind a CDN redirect resolved and downloaded byte-identical through the real transfer code |
| Vikingfile | PS5 browser step; name and size from Vikingfile's public file listing | As the existing flow | Yes, when connected | Listing **verified live**. Capture is tested against a mock; the PS5 browser step is **unverified** (needs a console) |
| 1Fichier | PS5 browser step, with the name and size you enter; or TorBox | As the existing flow | Yes, when connected | **Unverified** against the real site (mock-tested only) |
| DataNodes | Same as 1Fichier | As the existing flow | Yes, when connected | **Unverified** |
| AkiraBox | PS5 browser step, with the name and size you enter | As the existing flow | Not on TorBox's list | **Unverified** |
| Gofile | **TorBox only** | n/a | Yes, when connected | Direct is **not possible**: its guest API answered `error-notPremium` (live). TorBox path mock-tested, **unverified** with a real account |
| FuckingFast | **TorBox only** | n/a | Yes, when connected | Its page sits behind a Cloudflare challenge (live). TorBox path mock-tested, **unverified** |
| FileDitch | Recognised, **refused with its reason** | n/a | Not on TorBox's list | Its file links and status API returned a Cloudflare human-verification challenge to plain HTTP (live); Orbit does not try to answer that |
| Rootz | Recognised, **refused with its reason** | n/a | Not on TorBox's list | No verifiable public download flow found (file pages redirect to a login) |
| Archive.org | Catalogue entries: unchanged. A pasted `archive.org/download/…` link is an ordinary direct link | as above | Only if listed | Public files only; a login-only file gets the host's "needs a login" message |

**About the names you listed.** Akia, Viki and Data are consistent with AkiraBox, Vikingfile and DataNodes, and Dith with
FileDitch, but nothing in upstream's source or in the hosts' own sites confirms those short names. Names ending in `1`
were not found anywhere. They are treated only as search aliases, never as a way to classify a link.

A provider is offered for use only when its real flow worked for what the host returned. Rootz and FileDitch are
refused, and Gofile and FuckingFast are TorBox-only, for the reasons above. If a host later removes its challenge or
adds a public API, re-run `tools/fork/host-build.sh build/orbit-live && python3 tests/live_hosts.py --yes` before changing its entry in
`backend/hosts.c`.

## Which parts must match

| You want | PS5 service (`orbit_store.elf`) | Native app (`PPSA99177.ffpkg`) | Orbit Zero |
|---|---|---|---|
| Pasted links, new hosts, saved links, TorBox for links (in the browser version) | **fork** | any | not supported |
| Native **More settings → Add a download link** button | **fork** | **fork** | not supported |
| Only existing features | either | either | upstream's |

The fork service keeps upstream's version number (`1.3.5`) because upstream's apps compare it; the fork's own tag
(`custom.1`) is reported as `forkTag` by `/api/v1/system`. The official native app 1.7.0 should keep working against
the fork service (the API only gained fields) but this was **not tried on a console**.

**Orbit Zero** (the desktop app) is not changed: its source is not in upstream's source bundle, so this fork cannot
add pasted links or hosts there. Its computer-to-PS5 transfers are untouched.

## Install on a jailbroken PS5 (firmware 13.60)

This fork does not change anything about your jailbreak, ELF loader, kstuff or ShadowMountPlus. Whether those work on
13.60 is up to your setup. Follow upstream's [getting-started guide](https://github.com/saawant12/orbit-store-ps5/blob/main/guides/getting-started.md);
only the files differ.

1. Build the files ([below](#build-it-yourself)) or take a fork release if one is published. Check them against
   `SHA256SUMS`: `sha256sum -c SHA256SUMS`.
2. **Browser version:** load `orbit_store.elf` with your payload manager or ELF loader, exactly as for the official one.
   Open Orbit Store from the Media tab, then **App settings → Sources** and turn on **Direct links** (and any other host
   you want). You must have accepted the download notice there; pasting a link never bypasses it.
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
./build/orbit-hosts-test               # 110 unit checks
python3 tests/custom_integration.py    # 43 integration tests (local mock servers only)
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

**Artifacts from my build** (commit `f2d5596`, Podman 6.1.4, 2026-10-20; nothing was installed or uploaded):

| File | Size | SHA-256 |
|---|---|---|
| `orbit_store.elf` | 42,569,880 | `20ed85ca1bafa6acba136a655f363e063ebb8aafd621929841ccf5b10a742de8` |
| `PPSA99177.ffpkg` | 114,294,784 | `56d9b0df527fbd5b0e2c8ab5cbf7eacc6a7998a93e179b67d4968d9b6d4b54af` |

`app/tools/verify-package.sh` passed: the FFPKG carries exactly this ELF, its version marker, metadata, executable and
translations match the build.

**Reproducibility, honestly.** Rebuilding the *unmodified* upstream 1.3.5 source with this pipeline is deterministic
(two runs, identical bytes) and gives the same size, section layout, compiler string and embedded web bundle as the
official ELF, but **not the same bytes** (mine `8a954347…`, official `561a8e80…`). I did not find why, so these
artifacts are not claimed to be byte-identical to anything upstream publishes.

## What was and was not tested

| Layer | Result |
|---|---|
| Host filter, URL and filename rules, socket guard (production rules) | 110 checks pass |
| Pasted-link service against mock origins (redirects, HTML and error pages, filenames, Range and range-less hosts, interruption and resume, missing validators, expired link refresh, size change after check, late off-site redirect, saved links, restart, tampered queue, TorBox and Vikingfile mocks) | 43 tests pass; the key safety rules were mutation-checked |
| Web UI | Type-checks and builds; driven in headless Chromium through add, rename, errors, TorBox-only, needs-details, new-link prompt and all four looks |
| Native app | 180 unit tests pass, including the new hand-off |
| Real hosts | `tests/live_hosts.py`: 6 checks pass (listed above) |
| **PS5 hardware** | **Not tested.** No ELF run, no FFPKG install, no PS5 browser capture, no controller navigation of the new screens |
| Real TorBox account | Not tested (mock API only) |
| Orbit Zero | Not changed, not tested |
| Languages | New strings are in `i18n/en.json` only; the other ten show English |

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
`backend/{api,catalog,debrid,diagnostics,main,orbit,providers,queue,sources,state,transfer,tvapp,updates}.c|h`,
`Makefile`, `i18n/en.json`, `src/{App,Downloads,TvApp,components,types}.tsx|ts`, `src/interfaces/SettingsPage.tsx`,
`src/styles.css`, and in the native app `main.cpp`, `orbit/{browser_handoff,screens}.hpp`, `orbit/settings*.cpp`,
`preview_main.cpp`, `image_app_test.cpp`. Everything else is new (`backend/{hosts,resolve,custom}.c`, `src/AddLink.tsx`,
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
- Cloudflare- or login-gated hosts that need a human cannot be automated; Orbit shows the reason instead.
