<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Why a rebuild of upstream's ELF differed, and what it means

**Short answer.** Rebuilding the unmodified 1.3.5 source did not give upstream's published `orbit_store.elf`
(`561a8e80…`) because the OpenSSL static library embeds its **build date**, and mine was built on a different day.
With that one date pinned, the rebuild is **byte-identical** to the published file. This is a harmless difference. It is
neither a security nor a compatibility problem, and the final match is, if anything, evidence that the published
binary really is the published source built with the published toolchain.

## What was observed (2026-10-20)

Rebuilding the `src-v1.3.5` tree (upstream's source bundle, unmodified) with `BUILDING.md`'s container recipe gave a
file of **exactly the same size** (41,997,992 bytes), the same sections, compiler string and embedded web bundle, but a
different hash (`8a954347…`). Two of my runs matched each other, so the build is deterministic on its own.

Comparing the two files byte by byte:

- 352,642 bytes differ (0.84%), in `.rodata` (330,642), `.text` (14,593), `.rela.dyn` (6,001) and debug data.
- The differences are spread over 3,767 functions, in OpenSSL, libcurl, libmicrohttpd, libunwind **and** Orbit's own
  code, as about 12,700 short runs of roughly one byte. That pattern is what changed *addresses* look like (relative
  jumps and references into shifting data), not what *different code* looks like.
- The first difference in `.rodata` sits inside OpenSSL's version strings. The official file contains
  `built on: Fri Oct  2 23:17:49 2026 UTC`; mine contained `built on: Tue Oct 20 00:06:45 2026 UTC`, the moment my
  container built its libraries.

## The likely mechanism

The linker merges identical read-only strings into one table. Changing one string's text can change where that string
and its neighbours land, which moves the target of every instruction and relocation that points at them. A same-length
date string therefore leaves the file size unchanged while altering many bytes elsewhere. That chain is my inference
from the pattern above; the experiment below is what actually establishes the cause.

## The experiment

OpenSSL's build honours `SOURCE_DATE_EPOCH`. I rebuilt the dependency layer of the container with
`SOURCE_DATE_EPOCH=1790983069` (2026-10-02T23:17:49Z, the date inside the official file), changing nothing else, and
rebuilt the untouched upstream source:

```
upstream published   561a8e8015d9564d44e32b58a84e1294ea7043e96146110801a9f62ad99ac93b
rebuilt, date pinned 561a8e8015d9564d44e32b58a84e1294ea7043e96146110801a9f62ad99ac93b
```

Zero bytes differ. Same Debian trixie container, Debian clang 19.1.7, ps5-payload-sdk v0.43, and the sha256-pinned
OpenSSL 3.5.2, curl 8.18.0, libmicrohttpd 1.0.1, zlib, bzip2, xz and libarchive tarballs from `tools/build-deps.sh`.

## Is it a security or compatibility concern?

- **Security: no evidence of one.** A tampered or differently-built binary would not reproduce to the byte once the
  one benign input is aligned. The match covers the whole 42 MB file, including the embedded runtime and web bundle.
- **Compatibility: none.** The date is a string in `OpenSSL_version()` output. It has no effect on behaviour.
- **What this does *not* prove.** It shows the published ELF equals the published source plus a stated toolchain. It
  says nothing about whether that source is benign, which needs a source review that I have not done. I also did not
  rebuild and compare upstream's FFPKG or Orbit Zero.
- **A limit that remains.** `Dockerfile.sdk` starts `FROM debian:trixie`, an image tag that moves. If Debian updates
  clang or its libraries, a later rebuild can differ again for reasons unrelated to this one.

## What the fork does about it

The fork's `Dockerfile` now sets `SOURCE_DATE_EPOCH=1790983069` for the dependency build (with a new cache id, so
older objects cannot leak in). A fork build and upstream's therefore differ **only** by the fork's own changes, which
makes the fork's diff reviewable against the official binary's inputs.

To repeat the check on the unmodified source (needs Podman or Docker; see `BUILDING.md` for the prerequisites):

```sh
git worktree add ../orbit-base src-v1.3.5      # upstream's source, unmodified
cp Dockerfile ../orbit-base/Dockerfile         # the fork's copy, which pins the date
cd ../orbit-base
python3 -m venv .venv && .venv/bin/python tools/bootstrap.py && npm ci && npm run build && python3 tools/embed-launcher.py
podman build -f tools/Dockerfile.sdk -t orbit-sdk:0.43 . && podman build -t orbit-build:0.1 .
podman run --rm -v "$PWD:/work:Z" orbit-build:0.1 payload
sha256sum build/orbit_store.elf    # 561a8e80...
```

With upstream's own `Dockerfile` instead, the hash differs, which is the whole finding.
