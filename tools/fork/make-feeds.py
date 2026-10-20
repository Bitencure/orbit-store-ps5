#!/usr/bin/env python3
"""Write fork-payloads.json and fork-tv-app.json for the fork's own update feed.

The in-app updater of this fork reads these two files from the fork's `dev` branch (never upstream's
payloads.json), so an official build is never offered over the fork. They use upstream's feed format.
Run after tools/fork/build-ps5.sh:  python3 tools/fork/make-feeds.py [dist-fork/<version>-<tag>]
The version is the unchanged upstream protocol version, so a rebuilt fork reads as up to date; update
the fork by replacing the ELF/FFPKG with a newer fork release by hand."""
import hashlib, json, pathlib, re, sys

root = pathlib.Path(__file__).resolve().parents[2]
header = (root / 'backend/orbit.h').read_text()
version = re.search(r'#define ORBIT_VERSION "([^"]+)"', header).group(1)
tag = re.search(r'#define ORBIT_FORK_TAG "([^"]+)"', header).group(1)
repo = re.search(r'#define ORBIT_UPDATE_REPO "([^"]+)"', header).group(1)
dist = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else root / 'dist-fork' / f'{version}-{tag}'
base = f'https://github.com/{repo}/releases/download/v{version}-{tag}'
param = json.loads((root / 'app/sce_sys/param.json').read_text())
content = param['contentVersion']  # 01.007.000 -> 1.7.0
tv_version = '.'.join(str(int(part)) for part in content.split('.'))

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

elf, pkg = dist / 'orbit_store.elf', dist / 'PPSA99177.ffpkg'
(root / 'fork-payloads.json').write_text(json.dumps({
    'name': 'Orbit Store (unofficial fork)',
    'payloads': [{
        'name': 'Orbit Store (Beta, fork)', 'filename': 'orbit_store.elf', 'url': f'{base}/orbit_store.elf',
        'description': 'Unofficial fork of Orbit Store with pasted links and extra hosts.',
        'version': f'v{version}', 'category': 'Utilities', 'checksum': digest(elf), 'receiveProtocol': 1}],
}, indent=2) + '\n')
(root / 'fork-tv-app.json').write_text(json.dumps({
    'name': 'Orbit Store for TV (unofficial fork)', 'filename': 'PPSA99177.ffpkg', 'version': tv_version,
    'url': f'{base}/PPSA99177.ffpkg', 'checksum': digest(pkg), 'size': pkg.stat().st_size}, indent=2) + '\n')
print('wrote fork-payloads.json and fork-tv-app.json for', dist)
