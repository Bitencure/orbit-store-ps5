#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Checks build output against a SHA256SUMS file, and optionally rebuilds the committed tree to compare.
#
#   tools/fork/verify-build.sh dist-fork/1.3.5-custom.1/SHA256SUMS            # hash check only
#   tools/fork/verify-build.sh dist-fork/1.3.5-custom.1/SHA256SUMS --rebuild  # also rebuild HEAD from scratch
#
# --rebuild exports HEAD with `git archive` (so no local edits, build output or caches can leak in), builds
# the two ELFs in a temporary folder with tools/fork/build-ps5.sh --elf-only (Podman or Docker, network
# needed), and compares their hashes with the ones in the SHA256SUMS file. Nothing is installed or uploaded.
# Inputs that are not pinned by this repo: curl.se's current CA bundle (its SHA-256 is printed, so a
# difference can be traced to it) and the debian:trixie image tag.
set -euo pipefail
[ $# -ge 1 ] || { sed -n '3,6p' "$0" >&2; exit 2; }
sums=$(readlink -f "$1")
dir=$(dirname "$sums")
echo "== hashes in $dir"
(cd "$dir" && sha256sum -c --ignore-missing "$(basename "$sums")")
[ "${2:-}" = "--rebuild" ] || exit 0

root=$(cd "$(dirname "$0")/../.." && pwd)
[ -z "$(git -C "$root" status --porcelain)" ] || { echo "Commit or stash local changes first: the rebuild uses the committed tree." >&2; exit 2; }
commit=$(git -C "$root" rev-parse HEAD)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git -C "$root" archive HEAD | tar -x -C "$tmp"
echo "== rebuilding commit $commit in $tmp"
(cd "$tmp" && tools/fork/build-ps5.sh --elf-only >/dev/null)
echo "== CA bundle used: $(sha256sum "$tmp/.deps/cacert.pem" | cut -c1-64)"
built=$(echo "$tmp"/dist-fork/*)
status=0
for name in orbit_store.elf orbit_store_sandbox.elf; do
  want=$(awk -v n="$name" '$2 == n {print $1}' "$sums")
  got=$(sha256sum "$built/$name" | cut -c1-64)
  if [ -z "$want" ]; then echo "SKIP   $name (not listed in $sums)"
  elif [ "$want" = "$got" ]; then echo "SAME   $name $got"
  else echo "DIFFER $name expected $want got $got"; status=1; fi
done
exit $status
