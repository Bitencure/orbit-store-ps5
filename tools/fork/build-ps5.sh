#!/usr/bin/env bash
# Builds this fork's PS5 payload (orbit_store.elf) and, unless --elf-only, the native TV app
# (PPSA99177.ffpkg) with Podman or Docker, then writes SHA256SUMS next to them.
# Follows BUILDING.md exactly; only the engine and the output folder are different.
#
#   tools/fork/build-ps5.sh              # ELF + FFPKG
#   tools/fork/build-ps5.sh --elf-only   # just the service/browser payload
#   ENGINE=docker tools/fork/build-ps5.sh
#
# Short image names (debian:trixie, ubuntu:24.04) need an unqualified registry. If Podman says
# short-name resolution is enforced, point it at a config for this shell only:
#   printf 'unqualified-search-registries=["docker.io"]\nshort-name-mode="permissive"\n' > /tmp/registries.conf
#   export CONTAINERS_REGISTRIES_CONF=/tmp/registries.conf
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
engine=${ENGINE:-$(command -v podman || command -v docker || true)}
[ -n "$engine" ] || { echo "Install Podman or Docker first." >&2; exit 2; }
version=$(sed -n 's/^#define ORBIT_VERSION "\(.*\)"/\1/p' backend/orbit.h)
tag=$(sed -n 's/^#define ORBIT_FORK_TAG "\(.*\)"/\1/p' backend/orbit.h)
out="dist-fork/$version-$tag"

# The browser interface and catalogue snapshot are embedded by the host build.
[ -d node_modules ] || npm ci
[ -x .venv/bin/python ] || python3 -m venv .venv
[ -f .deps/cjson/cJSON.c ] || .venv/bin/python tools/bootstrap.py
npm run build

"$engine" build -f tools/Dockerfile.sdk -t orbit-sdk:0.43 .
"$engine" build -t orbit-build:0.1 .
"$engine" run --rm -v "$PWD:/work:Z" orbit-build:0.1 payload

mkdir -p "$out"
cp build/orbit_store.elf "$out/orbit_store.elf"
if [ "${1:-}" != "--elf-only" ]; then
  "$engine" build -t orbit-app-build:0.1 app
  "$engine" run --rm -v "$PWD:/work:Z" -w /work/app -e BUILD_JOBS="${BUILD_JOBS:-4}" orbit-app-build:0.1 make ffpkg
  "$engine" run --rm -v "$PWD:/work:Z" -w /work/app orbit-app-build:0.1 bash tools/verify-package.sh
  cp app/dist/PPSA99177.ffpkg "$out/PPSA99177.ffpkg"
fi
(cd "$out" && sha256sum * | grep -v '^SHA256SUMS' > SHA256SUMS && cat SHA256SUMS)
echo "Built $version ($tag) into $out. Nothing was installed or uploaded."
