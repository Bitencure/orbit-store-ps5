#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in checks against REAL hosts (fork). Never part of `make test`.

For each host this uploads one random 1 KB file through the host's documented anonymous upload
API (or reuses a link you pass with --link), then asks a production-rules Orbit build to resolve
it. The generic web adapter is also downloaded for real through Orbit's transfer code.
Uploaded files are random bytes, not game data; they stay on the host until it expires them.

    tools/fork/host-build.sh build/orbit-live
    python3 tests/live_hosts.py --yes                       # upload, resolve, report
    python3 tests/live_hosts.py --yes --only web,viking
    python3 tests/live_hosts.py --yes --link viking=https://vikingfile.com/f/XXXXXXXXXX

A PASS means Orbit behaved correctly for what the host returned today, including refusing it.
It is not PS5 hardware testing, and the Vikingfile browser step needs a console."""
import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import secrets
import subprocess
import sys
import tempfile
import time
import types
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('ci', ROOT / 'tests' / 'custom_integration.py')
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)
ci.BIN = ROOT / 'build' / 'orbit-live'

# A tiny public file that redirects to a CDN with a signed URL, as a generic host would.
WEB_FILE = 'https://github.com/saawant12/orbit-store-ps5/releases/download/v1.3.5/SHA256SUMS'
UA = {'User-Agent': 'orbit-fork-live-check'}


def fetch(url, data=None, headers=None, method=None):
    request = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})}, method=method)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def multipart(fields, filename, payload):
    boundary = secrets.token_hex(16)
    body = b''
    for key, value in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
             f'Content-Type: application/octet-stream\r\n\r\n').encode() + payload + f'\r\n--{boundary}--\r\n'.encode()
    return body, {'Content-Type': f'multipart/form-data; boundary={boundary}'}


def upload(host, payload, name):
    if host == 'viking':
        server = json.loads(fetch('https://vikingfile.com/api/get-server'))['server']
        body, headers = multipart({'user': ''}, name, payload)
        return json.loads(fetch(server, body, headers))['url'].replace('\\/', '/')
    if host == 'ditch':
        return json.loads(fetch(f'https://new.fileditch.com/upload.php?filename={name}', payload, method='PUT'))['url']
    if host == 'gofile':
        body, headers = multipart({}, name, payload)
        return json.loads(fetch('https://upload.gofile.io/uploadfile', body, headers))['data']['downloadPage']
    if host == 'rootz':
        body, headers = multipart({}, name, payload)
        data = json.loads(fetch('https://rootz.so/api/files/upload', body, headers))['data']
        upload.rootz_uuid = data['id']
        return f"https://rootz.so/d/{data['shortId']}"
    raise ValueError(host)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--yes', action='store_true', help='confirm that uploading random 1 KB files to public hosts is fine')
    parser.add_argument('--only', default='web,viking,ditch,gofile,rootz')
    parser.add_argument('--rootz-uuid', help='the file id of a reused --link rootz=… (needed for the CDN step)')
    parser.add_argument('--link', action='append', default=[], metavar='HOST=URL', help='reuse an existing link instead of uploading')
    args = parser.parse_args()
    wanted = set(args.only.split(','))
    links = dict(item.split('=', 1) for item in args.link)
    uploads = [h for h in ('viking', 'ditch', 'gofile', 'rootz') if h in wanted and h not in links]
    if uploads and not args.yes:
        sys.exit('This uploads one random 1 KB file to: ' + ', '.join(uploads) + '. Re-run with --yes to allow it.')
    if not ci.BIN.exists():
        sys.exit('Build first: tools/fork/host-build.sh build/orbit-live')

    payload = os.urandom(1024)
    stem = f'orbit-fork-probe-{int(time.time())}'
    for host in uploads:
        links[host] = upload(host, payload, stem + '.bin')
        print(f'uploaded {host}: {links[host]}')

    tmp = tempfile.TemporaryDirectory()
    service = ci.Service(tmp.name, types.SimpleNamespace(base='http://127.0.0.1:1'))
    original = ci.subprocess.Popen
    ci.subprocess.Popen = lambda cmd, **kw: original(cmd, **{**kw, 'env': {k: v for k, v in kw['env'].items() if not k.startswith('ORBIT_TEST') or k == 'ORBIT_TEST_CAPTURE_URL'}})
    results = []

    def record(host, expectation, ok, observed):
        results.append((host, expectation, ok, observed))
        print(f"{'PASS' if ok else 'FAIL'}  {host:8} {expectation}\n      -> {observed}")

    try:
        service.start()
        service.enable('web', 'vikingfile', 'gofile', 'rootz')
        if 'web' in wanted:
            reply = service.resolve(WEB_FILE, 'live-web-check.bin', timeout=60)
            ok = reply['state'] == 'ready' and reply['sizeBytes'] > 0
            record('web', 'resolves a public file behind a CDN redirect', ok, f"{reply['state']} {reply.get('sizeBytes')} bytes resumable={reply.get('resumable')}")
            if ok:
                status, body = service.queue(reply['releaseId'])
                job = service.wait_job(body['id'], {'complete', 'error'}, 120) if status == 201 else {'status': 'error', 'error': str(body)}
                expected = hashlib.sha256(fetch(WEB_FILE)).hexdigest()
                got = ci.sha256_file(job['path']) if job['status'] == 'complete' else job.get('error')
                record('web', 'downloads it through the real transfer code, byte-identical', got == expected, f"{job['status']} sha256={str(got)[:16]}")
            page = service.resolve('https://raw.githubusercontent.com/DaveGamble/cJSON/v1.7.19/LICENSE', timeout=60)
            record('web', 'refuses a text page instead of saving it as a download', page['state'] == 'error', page.get('message', page['state']))
        if 'viking' in wanted:
            reply = service.resolve(links['viking'], timeout=60)
            ok = reply['state'] == 'needs-browser' and (reply['sizeBytes'] == 1024 or 'viking' not in uploads)
            record('viking', 'reads name and size from the public listing, then needs the PS5 browser step', ok,
                   f"{reply['state']} {reply.get('filename')} {reply.get('sizeBytes')} bytes")
        if 'ditch' in wanted:
            reply = service.resolve(links['ditch'], timeout=60)
            record('ditch', 'confirms the file through its open status endpoint, and refuses the download with its reason',
                   reply['state'] == 'unsupported' and reply['provider'] == 'fileditch' and reply.get('exists') is True, reply['message'])
            try:
                fetch(links['ditch'], headers={'Range': 'bytes=0-0'})
                challenged = 'no challenge seen: FileDitch may now be reachable by plain HTTP; re-evaluate enabling it'
            except urllib.error.HTTPError as error:
                challenged = f'plain HTTP got {error.code}, cf-mitigated={error.headers.get("cf-mitigated")}'
            print(f'      (direct probe: {challenged})')
        if 'rootz' in wanted:
            page = links['rootz']
            reply = service.resolve(page, timeout=60)
            record('rootz', 'resolves the share page to a browser-assisted download with the name and size still to be read',
                   reply['state'] == 'needs-browser' and reply.get('sizePending') is True, f"{reply['state']} pending={reply.get('sizePending')}")
            uuid = getattr(upload, 'rootz_uuid', None) or args.rootz_uuid
            if uuid:
                # What a person's browser reveals after pressing Download on the page, taken from Rootz's documented API.
                cdn = json.loads(fetch(f'https://rootz.so/api/files/download/{uuid}'))['data']['url']
                # Fed through the pasted-link route, as a person would after copying it from their own browser.
                reply = service.resolve(page, timeout=60)
                status, body = service.call('POST', '/api/v1/browser', {'action': 'start', 'releaseId': reply['releaseId'],
                                            'storageId': service.storage_id(), 'link': cdn})
                state = {}
                for _ in range(200):
                    state = service.call('GET', '/api/v1/browser')[1]
                    if state['state'] in ('queued', 'failed', 'cancelled'):
                        break
                    time.sleep(0.3)
                job = service.wait_job(state['jobId'], {'complete', 'error'}, 120) if state['state'] == 'queued' else {'status': 'error', 'error': state.get('message', '')}
                got = ci.sha256_file(job['path']) if job['status'] == 'complete' else job.get('error')
                record('rootz', 'a pasted real CDN link is validated, its name and size learned, and the file downloads byte-identical',
                       job['status'] == 'complete' and got == hashlib.sha256(payload).hexdigest() if 'rootz' in uploads else job['status'] == 'complete',
                       f"{job['status']} name={job.get('filename')} sha256={str(got)[:16]}")
            else:
                print('      (CDN step skipped: pass --rootz-uuid with a reused link)')
        if 'gofile' in wanted:
            reply = service.resolve(links['gofile'], timeout=60)
            record('gofile', 'is recognised and needs TorBox', reply['state'] == 'unsupported' and reply['provider'] == 'gofile', reply['message'])
    finally:
        service.stop()
        tmp.cleanup()
    print()
    failed = [r for r in results if not r[2]]
    print(f'{len(results) - len(failed)} passed, {len(failed)} failed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
