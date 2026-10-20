#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Repeatable checks of progress, cancellation and recovery against a real console, driven through the sandbox's own API.

A click in the browser cannot reliably cancel a download that finishes in six seconds. This starts a download, watches the
service's counter and the .part file on the console (over FTP), and acts at exact byte counts, so each check gives the same
answer every time. It needs the sandbox running, its pairing code, and (for the file checks) an FTP server on the console.

    tools/fork/hardware-check.py --ps5 192.168.1.50 --code 123456 --ftp-port 2121 --drive usb0 progress cancel-delete cancel-keep
    tools/fork/hardware-check.py --ps5 192.168.1.50 --code 123456 --ftp-port 2121 --drive internal restart

Scenarios: progress, cancel-delete, cancel-keep, restart (asks you to send the ELF again). Direct links must already be turned on in
the sandbox page. It downloads a public test file (default: a 116 MB GitHub release asset) under names starting orbit-fork-hw-,
and removes only those. The pairing token is never printed or saved."""
import argparse
import ftplib
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_URL = 'https://github.com/saawant12/orbit-store-ps5/releases/download/v1.3.5/Orbit-Zero-1.3.5-linux-arm64.deb'
DEFAULT_SHA256 = '7f916af83ab3ab20944c3178beb2c43e79d5d0b4a70628428b94754838761d71'  # upstream's SHA256SUMS entry for it


class Console:
    def __init__(self, args):
        self.args, self.token, self.results = args, args.token, []
        self.base = f'http://{args.ps5}:{args.port}/api/v1'

    # ---- the service ----
    def call(self, method, path, body=None, auth=True):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            request.add_header('Content-Type', 'application/json')
        if auth and self.token:
            request.add_header('Authorization', 'Bearer ' + self.token)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read() or b'null')
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                return error.code, json.loads(raw)
            except ValueError:
                return error.code, {'error': raw.decode(errors='replace')}

    def connect(self):
        status, system = self.call('GET', '/system', auth=False)
        if status != 200 or not system.get('sandbox'):
            sys.exit('That address is not answering as the sandbox build (/api/v1/system has no "sandbox": true).')
        if not self.token:
            status, body = self.call('POST', '/pair', {'code': self.args.code}, auth=False)
            if status != 200:
                sys.exit(f'Pairing failed ({status}). Use "Show code on PS5" on the sandbox page for a fresh code.')
            self.token = body['token']
        status, sources = self.call('GET', '/sources')
        if status != 200 or 'web' not in sources.get('enabled', []):
            sys.exit('Turn on Direct links in the sandbox page (Download sources) first; this tool does not accept the notice for you.')
        drives = self.call('GET', '/storage')[1]
        match = [d for d in drives if d['id'] == self.args.drive]
        if not match:
            sys.exit(f'No drive "{self.args.drive}". Available: ' + ', '.join(d['id'] for d in drives))
        self.drive = match[0]
        print(f"Saving to {self.drive['label']}: {self.drive['path']}/")

    def resolve_and_queue(self, name):
        status, _ = self.call('POST', '/custom/resolve', {'action': 'resolve', 'url': self.args.url, 'filename': name})
        if status != 202:
            sys.exit('The service would not start checking the link.')
        for _ in range(120):
            status, reply = self.call('GET', '/custom/resolve')
            if status == 200 and reply.get('state') != 'resolving':
                break
            time.sleep(0.5)
        if reply.get('state') != 'ready':
            sys.exit(f"The test file is not usable right now: {reply.get('message', reply.get('state'))}")
        status, job = self.call('POST', '/downloads', {'releaseId': reply['releaseId'], 'storageId': self.drive['id'], 'delivery': 'direct'})
        if status != 201:
            sys.exit(f"Could not queue it: {job.get('error', status)}")
        return job['id'], reply['sizeBytes']

    def job(self, job_id):
        status, jobs = self.call('GET', '/downloads')
        return next((j for j in jobs if j['id'] == job_id), None) if status == 200 else None

    def wait(self, job_id, states, timeout=300):
        end = time.time() + timeout
        while time.time() < end:
            job = self.job(job_id)
            if job and job['status'] in states:
                return job
            time.sleep(0.4)
        sys.exit(f'Timed out waiting for {sorted(states)}; the job is {self.job(job_id)}')

    def wait_received(self, job_id, minimum):
        while True:
            job = self.job(job_id)
            if not job or job['status'] in ('complete', 'error', 'cancelled'):
                sys.exit(f"The download ended before reaching {minimum:,} bytes ({job and job['status']}). Use --url with a bigger file.")
            if job['received'] >= minimum:
                return job
            time.sleep(0.1)

    # ---- the files on the console ----
    def ftp(self):
        if not self.args.ftp_port:
            return None
        client = ftplib.FTP()
        client.connect(self.args.ps5, self.args.ftp_port, timeout=20)
        client.login()
        client.voidcmd('TYPE I')
        return client

    def size_of(self, name):
        if self.args.local_folder:
            path = os.path.join(self.args.local_folder, name)
            return os.path.getsize(path) if os.path.exists(path) else -1
        client = self.ftp()
        if not client:
            return None
        try:
            return client.size(f"{self.drive['path']}/{name}")
        except ftplib.error_perm:
            return -1  # not there
        finally:
            client.close()

    def sha256_of(self, name):
        digest = hashlib.sha256()
        if self.args.local_folder:
            with open(os.path.join(self.args.local_folder, name), 'rb') as handle:
                for block in iter(lambda: handle.read(1 << 20), b''):
                    digest.update(block)
            return digest.hexdigest()
        client = self.ftp()
        try:
            client.retrbinary(f"RETR {self.drive['path']}/{name}", digest.update, blocksize=1 << 20)
        finally:
            client.close()
        return digest.hexdigest()

    def delete_file(self, name):
        if self.args.local_folder:
            if os.path.exists(os.path.join(self.args.local_folder, name)):
                os.remove(os.path.join(self.args.local_folder, name))
            return
        client = self.ftp()
        if client:
            try:
                client.delete(f"{self.drive['path']}/{name}")
            except ftplib.error_perm:
                pass
            client.close()

    # ---- reporting ----
    def check(self, ok, text, detail=''):
        self.results.append(ok)
        print(f"  {'PASS' if ok else 'FAIL'}  {text}" + (f'  [{detail}]' if detail else ''))

    def name(self, scenario):
        return f'orbit-fork-hw-{scenario}-{int(time.time())}.bin'

    def verify_file(self, name):
        if not (self.args.ftp_port or self.args.local_folder) or self.args.no_hash:
            print('  (hash check skipped)')
            return
        got = self.sha256_of(name)
        self.check(got == self.args.sha256, 'file is byte-identical to the published hash', got[:16])


def progress(c):
    print('progress: the counter against the .part file, then pause and resume')
    name = c.name('progress')
    job_id, size = c.resolve_and_queue(name)
    print('     t   counter(bytes)   .part(bytes)')
    start, last = time.time(), None
    while True:
        job = c.job(job_id)
        part = c.size_of(name + '.part')
        print(f"  {time.time() - start:5.1f}  {job['received']:14,}  {part if part is not None else '-':>13}")
        if job['received'] >= c.args.at or job['status'] != 'downloading':
            break
        time.sleep(0.4)
    c.call('POST', f'/downloads/{job_id}/pause', {})
    paused = c.wait(job_id, {'paused', 'complete'})
    if paused['status'] == 'complete':
        sys.exit('It finished before it could be paused; use --url with a bigger file.')
    part = c.size_of(name + '.part')
    time.sleep(3)
    again, part_again = c.job(job_id), c.size_of(name + '.part')
    c.check(again['received'] == paused['received'] and part_again == part, 'nothing moves while paused', f"counter {again['received']:,}, file {part_again}")
    c.check(part is None or part >= paused['received'], 'the file is never shorter than the counter', f"file {part}, counter {paused['received']:,}")
    c.check(paused['received'] < size, 'the counter is below the total at the pause')
    c.call('POST', f'/downloads/{job_id}/resume', {})
    done = c.wait(job_id, {'complete', 'error'})
    c.check(done['status'] == 'complete', 'resume finishes', done.get('error', ''))
    c.check(c.size_of(name + '.part') in (None, -1), 'the .part file is gone when it finishes')
    c.verify_file(name)
    c.delete_file(name)
    c.call('POST', f'/downloads/{job_id}/remove', {})


def cancel_delete(c):
    print('cancel-delete: Cancel, then Delete partial file')
    name = c.name('cancel-delete')
    job_id, _ = c.resolve_and_queue(name)
    job = c.wait_received(job_id, c.args.at)
    part = c.size_of(name + '.part')
    c.check(part is None or part > 0, 'a .part file exists while downloading', f'{part}')
    status, _ = c.call('POST', f'/downloads/{job_id}/cancel', {'deletePartial': True})
    c.check(status == 200, 'the cancel is accepted')
    job = c.wait(job_id, {'cancelled', 'complete'})
    c.check(job['status'] == 'cancelled', 'the job is Cancelled', job['status'])
    time.sleep(2)
    c.check(c.size_of(name + '.part') in (None, -1), 'the .part file was deleted', f"{c.size_of(name + '.part')}")
    c.check(c.size_of(name) in (None, -1), 'no finished file appeared')
    c.call('POST', f'/downloads/{job_id}/forget', {})


def cancel_keep(c):
    print('cancel-keep: Cancel, Keep partial file, then Delete download')
    name = c.name('cancel-keep')
    job_id, _ = c.resolve_and_queue(name)
    c.wait_received(job_id, c.args.at)
    status, _ = c.call('POST', f'/downloads/{job_id}/cancel', {'deletePartial': False})
    c.check(status == 200, 'the cancel is accepted')
    job = c.wait(job_id, {'cancelled', 'complete'})
    c.check(job['status'] == 'cancelled', 'the job is Cancelled', job['status'])
    time.sleep(1)
    part = c.size_of(name + '.part')
    time.sleep(2)
    c.check(c.size_of(name + '.part') == part and part not in (None, -1), 'the .part file is kept and stops growing', f'{part}')
    c.check(c.call('POST', f'/downloads/{job_id}/remove', {})[0] == 409, 'history refuses to drop an entry that owns a partial file')
    c.check(c.call('POST', f'/downloads/{job_id}/delete', {})[0] == 200, 'Delete download is accepted')
    c.check(c.size_of(name + '.part') in (None, -1), 'the partial file is gone after Delete download')


def restart(c):
    print('restart: stop the sandbox mid-download, send the ELF again, resume')
    name = c.name('restart')
    job_id, size = c.resolve_and_queue(name)
    c.wait_received(job_id, c.args.at)
    time.sleep(3)  # progress is saved about every two seconds
    before = c.job(job_id)
    status, _ = c.call('POST', '/updates', {'action': 'stop', 'confirmed': True})
    c.check(status == 202, 'Stop is accepted', f'{status}')
    for _ in range(40):  # wait for the port to close
        try:
            c.call('GET', '/system', auth=False)
            time.sleep(0.5)
        except OSError:
            break
    input('The sandbox has stopped. Send orbit_store_sandbox.elf again, then press Enter here... ')
    for _ in range(60):
        try:
            if c.call('GET', '/system', auth=False)[0] == 200:
                break
        except OSError:
            pass
        time.sleep(1)
    after = c.job(job_id)
    if not after:
        c.token = None
        c.args.token = None
        c.check(False, 'the interrupted download is still listed (you may need to pair again: pass a new --code)')
        return
    part = c.size_of(name + '.part')
    c.check(after['status'] in ('paused', 'queued', 'retrying', 'downloading'), 'the download survived the restart', after['status'])
    c.check(after['received'] > 0, 'it kept its progress', f"{after['received']:,} of the {before['received']:,} counted before the stop")
    c.check(part is None or part >= after['received'], 'the file is not shorter than the counter', f'{part}')
    if after['status'] == 'paused':
        c.call('POST', f'/downloads/{job_id}/resume', {})
    done = c.wait(job_id, {'complete', 'error'})
    c.check(done['status'] == 'complete', 'it finishes after the restart', done.get('error', ''))
    c.verify_file(name)
    c.delete_file(name)
    c.call('POST', f'/downloads/{job_id}/remove', {})


SCENARIOS = {'progress': progress, 'cancel-delete': cancel_delete, 'cancel-keep': cancel_keep, 'restart': restart}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('scenarios', nargs='+', choices=sorted(SCENARIOS))
    parser.add_argument('--ps5', required=True, help='the console address')
    parser.add_argument('--port', type=int, default=34178, help='the sandbox port (default 34178)')
    parser.add_argument('--code', help='the pairing code the sandbox shows')
    parser.add_argument('--token', help='an existing pairing token, instead of --code')
    parser.add_argument('--ftp-port', type=int, default=0, help="the console's FTP port, for the file checks (0 skips them)")
    parser.add_argument('--drive', default='internal', help='storage id: internal, usb0, ...')
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--sha256', default=DEFAULT_SHA256)
    parser.add_argument('--at', type=int, default=20_000_000, help='act when this many bytes are counted')
    parser.add_argument('--no-hash', action='store_true', help='skip downloading the finished file back for its hash')
    parser.add_argument('--local-folder', help='read file sizes from this local folder instead of FTP (for testing the tool itself)')
    args = parser.parse_args(argv)
    if not args.code and not args.token:
        parser.error('give --code (or --token)')
    console = Console(args)
    console.connect()
    for name in args.scenarios:
        SCENARIOS[name](console)
    print(f"\n{sum(console.results)} of {len(console.results)} checks passed.")
    return 0 if all(console.results) else 1


if __name__ == '__main__':
    sys.exit(main())
