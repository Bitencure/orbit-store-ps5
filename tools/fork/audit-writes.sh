#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Shows that the sandbox service only writes inside its own state folder and the download folder.
# Runs the integration tests against build/orbit-sandbox-test inside a bubblewrap jail whose whole
# filesystem is read-only except those two folders, with an LD_PRELOAD shim (wrlog.c) logging every
# filesystem mutation, then fails if any logged path is elsewhere.
# Limits: this is the host build, so PS5-only code (notification, browser launch, memory reads,
# ShadowMount calls) is not exercised; docs/SANDBOX-AUDIT.md covers those by reading the code.
# Needs: bwrap, cc, python3, and tools/fork/host-build.sh build/orbit-sandbox-test.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
[ -x build/orbit-sandbox-test ] || { echo "Build first: tools/fork/host-build.sh build/orbit-sandbox-test" >&2; exit 2; }
command -v bwrap >/dev/null || { echo "Install bubblewrap (bwrap)." >&2; exit 2; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cc -shared -fPIC -O1 -o "$work/wrlog.so" tools/fork/wrlog.c -ldl
cat > "$work/run.sh" <<RUN
#!/usr/bin/env bash
while [ \$# -gt 0 ]; do case "\$1" in --state) STATE=\$2;; --storage) STORAGE=\$2;; esac; ARGS+=("\$1"); shift; done
exec bwrap --ro-bind / / --dev /dev --proc /proc --bind "\$STATE" "\$STATE" --bind "\$STORAGE" "\$STORAGE" --bind "$work" "$work" \\
  --setenv LD_PRELOAD "$work/wrlog.so" --setenv WRLOG_FILE "$work/writes.log" --die-with-parent \\
  "$root/build/orbit-sandbox-test" "\${ARGS[@]}"
RUN
chmod +x "$work/run.sh"
ORBIT_SANDBOX_AUDIT=1 ORBIT_TEST_BIN="$work/run.sh" python3 tests/custom_integration.py
python3 -I - "$work/writes.log" <<'PY'
import collections, re, sys
rows = [line.rstrip('\n').split('\t') for line in open(sys.argv[1])]
inside = re.compile(r'^/tmp/(?:tmp[^/]*)/(?:state|storage)(?:/|$)')
outside = collections.Counter((op, path) for op, path, _ in rows if not inside.match(path))
print(f'\n{len(rows)} filesystem mutations logged.')
if outside:
    print('OUTSIDE the state and storage folders:')
    for (op, path), n in sorted(outside.items()):
        print(f'  {op}\t{path}\tx{n}')
    sys.exit(1)
print('None outside the state and storage folders.')
PY
