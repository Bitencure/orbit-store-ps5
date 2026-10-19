# Orbit Store, unofficial fork

This is an **unofficial, community fork** of [Orbit Store](https://github.com/saawant12/orbit-store-ps5) by saawant12. It is not affiliated with or endorsed by the upstream project. Upstream copyright and attribution are retained, and the code remains licensed **GPL-3.0-or-later** (see `LICENSE`).

The `source` branch is the unmodified upstream source bundle (`src-v1.3.5` = release v1.3.5, bundle sha256 `c0fe51d94b199daa77b620b5d596afc13b77902076db313891885d0e54339858`). This `dev` branch is that source plus the changes listed below. The fork's `main` branch mirrors upstream's docs and catalogue feeds.

Use files only from a build whose version and fork tag you recognise. Do not mix a fork service with an official native app unless the compatibility table says it works.

## Goals of this fork

- More file-host support (Gofile, FileDitch, FuckingFast, Rootz, plus generic HTTPS) behind a provider adapter table.
- "Add download from URL": paste your own link instead of relying on the built-in catalogue.
- A local, user-importable custom catalogue. The encrypted upstream feeds are never modified.

Nothing here adds game links. A host is listed as supported only when its real download flow was verified; the support matrix will say which.

## Status

Work in progress. Baseline (unmodified upstream 1.3.5) on Linux x64:

| Step | Result |
|---|---|
| `npm ci`, `npm run build` (catalogue check, `tsc -b`, vite, embed) | passes |
| Host service `build/orbit-host` and test binary `build/orbit-test` (`-Werror`, clang 23) | compile; service starts and serves `/api/v1/system` as 1.3.5 |
| PS5 ELF / native FFPKG | not built yet (needs Docker or Podman) |
| PS5 hardware | **not tested** |

## Building on Linux without Docker

```sh
python3 -m venv .venv
.venv/bin/python tools/bootstrap.py
npm ci && npm run build
tools/fork/host-build.sh            # host service + ORBIT_TEST binary
```

The PS5 ELF and FFPKG are built exactly as upstream documents in `BUILDING.md` (Docker or Podman).
