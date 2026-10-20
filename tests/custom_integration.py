#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end tests for pasted-link downloads (fork).

Runs the ORBIT_TEST service (loopback http only) against local mock origins. No real host
is contacted and no game data is used: every file is a deterministic 1 MiB buffer.
Run: python3 tests/custom_integration.py (after tools/fork/host-build.sh). This proves the software; it is not PS5 hardware testing."""
import builtins
import contextlib
import hashlib
import http.server
import importlib.util
import io
import json
import os
import pathlib
import re
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BIN = pathlib.Path(os.environ.get('ORBIT_TEST_BIN', ROOT / 'build' / 'orbit-test'))
DATA = bytes((i * 7 + i // 251) % 256 for i in range(1 << 20))
ETAG = '"v1-' + hashlib.md5(DATA).hexdigest()[:12] + '"'
MODIFIED = 'Wed, 01 Jan 2025 00:00:00 GMT'
CUT_AT = 300_000


# A 48 MiB file generated from its offset (nothing is stored), large enough for Orbit to split it into parallel ranges.
# Byte i is (7 * (i % 65536) + i // 65536) % 256, so a chunk that lands at the wrong offset can never match by accident.
BIG_SIZE = 48 * 1024 * 1024
_BIG_BASE = bytes((7 * j) % 256 for j in range(65536))
_BIG_SHIFT = [bytes((x + k) % 256 for x in range(256)) for k in range(256)]


def big_slice(start, end):
    out, pos = bytearray(), start
    while pos < end:
        offset = pos & 0xFFFF
        take = min(end - pos, 65536 - offset)
        out += _BIG_BASE[offset:offset + take].translate(_BIG_SHIFT[(pos >> 16) % 256])
        pos += take
    return bytes(out)


def big_sha256():
    digest = hashlib.sha256()
    for start in range(0, BIG_SIZE, 1 << 20):
        digest.update(big_slice(start, min(start + (1 << 20), BIG_SIZE)))
    return digest.hexdigest()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.route(True)

    def do_HEAD(self):
        self.route(False)

    def do_POST(self):
        length = int(self.headers.get('Content-Length') or 0)
        form = self.rfile.read(length).decode() if length else ''
        with self.server.lock:
            self.server.log.append(('POST', self.path, None, form))
        if self.path.split('?')[0] == '/viking/check-file':
            gone = 'hash=gonegonegone' in form
            body = json.dumps({'exist': not gone, 'hash': form.split('=')[-1], 'name': 'viking-sample.bin', 'size': len(DATA)}).encode()
            return self.reply(200, {'Content-Type': 'application/json'}, body)
        self.reply(404, {'Content-Type': 'text/plain'}, b'unknown')

    def serve_big(self, send_body, rng):
        """/big.bin, with a hold the test controls: once `hold_after` bytes have been served in total, every connection
        stalls until the test releases it, so "part-way through" is an exact, repeatable state."""
        server = self.server
        start, end, status = 0, BIG_SIZE - 1, 200
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', rng or '')
        if match:
            first, last = match.groups()
            start = int(first) if first else 0
            end = min(int(last), BIG_SIZE - 1) if last else BIG_SIZE - 1
            status = 206
        headers = {'Content-Type': 'application/octet-stream', 'ETag': '"big-v1"', 'Last-Modified': MODIFIED,
                   'Accept-Ranges': 'bytes', 'Content-Length': str(end - start + 1)}
        if status == 206:
            headers['Content-Range'] = f'bytes {start}-{end}/{BIG_SIZE}'
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if not send_body:
            return
        pos = start
        try:
            while pos <= end:
                deadline = time.time() + 120
                while time.time() < deadline:
                    with server.lock:
                        held = server.big_hold_after is not None and server.big_served >= server.big_hold_after
                    if not held:
                        break
                    time.sleep(0.02)
                take = min(65536, end - pos + 1)
                self.wfile.write(big_slice(pos, pos + take))
                with server.lock:
                    server.big_served += take
                    delay = server.big_delay
                if delay:
                    time.sleep(delay)
                pos += take
        except OSError:
            pass  # the client went away (paused, cancelled or killed)

    def serve_data(self, data, send_body, rng, if_match, extra):
        headers = {'Content-Type': 'application/octet-stream', 'ETag': ETAG, 'Last-Modified': MODIFIED, 'Accept-Ranges': 'bytes', **extra}
        start, end, status = 0, len(data) - 1, 200
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', rng or '')
        if match:
            first, last = match.groups()
            start = int(first) if first else 0
            end = min(int(last), len(data) - 1) if last else len(data) - 1
            status = 206
            headers['Content-Range'] = f'bytes {start}-{end}/{len(data)}'
        body = data[start:end + 1]
        headers['Content-Length'] = str(len(body))
        self.reply(status, headers, body, send_body)

    def reply(self, status, headers, body=b'', send_body=True):
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        if 'Content-Length' not in headers and 'Transfer-Encoding' not in headers:
            self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def route(self, send_body):
        server = self.server
        path = self.path.split('?')[0]
        rng, if_match = self.headers.get('Range'), self.headers.get('If-Match')
        with server.lock:
            server.log.append((self.command, path, rng, if_match))
        octet = {'Content-Type': 'application/octet-stream'}
        if path == '/big.bin':
            return self.serve_big(send_body, rng)
        simple = {
            '/html': (200, {'Content-Type': 'text/html; charset=utf-8'}, b'<html>Sorry, file not found</html>'),
            '/json': (200, {'Content-Type': 'application/json'}, b'{"error":"expired"}'),
            '/missing': (404, {'Content-Type': 'text/plain'}, b'no'),
            '/gone': (410, {'Content-Type': 'text/plain'}, b'no'),
            '/forbidden': (403, {'Content-Type': 'text/plain'}, b'no'),
            '/busy': (503, {'Content-Type': 'text/plain', 'Retry-After': '1'}, b'no'),
            '/redirect1': (302, {'Location': '/redirect2'}, b''),
            '/redirect2': (302, {'Location': '/file.bin'}, b''),
            '/loop': (302, {'Location': '/loop'}, b''),
            '/offsite': (302, {'Location': 'http://example.com/file.bin'}, b''),
            '/offscheme': (302, {'Location': 'ftp://127.0.0.1/file.bin'}, b''),
            '/file:nope': (200, octet, b'x'),
        }
        if path in simple:
            status, headers, body = simple[path]
            return self.reply(status, headers, body, send_body)
        if path.startswith('/api/alpha1/'):
            body = {'/api/alpha1/abc123/file.bin': {'file': path[4:], 'status': True, 'size': 52428800, 'views': 3, 'short_link': None},
                    '/api/alpha1/gone00/file.bin': {'file': path[4:], 'status': False, 'size': None, 'views': 3, 'short_link': None},
                    '/api/alpha1/unreachable/file.bin': {'file': path[4:], 'status': 'unknown', 'size': None, 'views': None, 'short_link': None}}.get(path)
            if body is None:
                return self.reply(404, {'Content-Type': 'text/plain'}, b'unknown', send_body)
            return self.reply(200, {'Content-Type': 'application/json'}, json.dumps(body).encode(), send_body)
        if path.startswith('/dl/'):
            named = {'/dl/learned.bin': 'attachment; filename="learned-name.bin"',
                     '/dl/evil.bin': 'attachment; filename="../../evil-name.bin"',
                     '/dl/nameless.bin': None}
            if path not in named:
                return self.reply(404, {'Content-Type': 'text/plain'}, b'unknown', send_body)
            extra = {'Content-Disposition': named[path]} if named[path] else {}
            return self.serve_data(DATA, send_body, rng, if_match, extra)
        if path.startswith('/torbox-cdn/'):
            name = path.rsplit('/', 1)[1]
            return self.serve_data(DATA, send_body, rng, if_match, {'Content-Disposition': f'attachment; filename="{name}"'})
        disposition = {
            '/disp-plain': 'attachment; filename="Report 1.bin"',
            '/disp-star': "attachment; filename=\"fallback.bin\"; filename*=UTF-8''%E2%82%AC%20price.bin",
            '/disp-evil': 'attachment; filename="../../etc/evil.bin"',
            '/disp-part': 'attachment; filename="game.part"',
            '/disp-dots': 'attachment; filename=".."',
        }.get(path)
        etag, modified, ranged, chunked, name_token = ETAG, MODIFIED, True, False, None
        if path in ('/file.bin', '/flaky.bin', '/noetag.bin', '/norange.bin', '/chunked.bin', '/nosize.bin', '/swap.bin', '/late-redirect.bin', '/changed.bin', '/short.bin') \
                or disposition or path.startswith('/expiring/') or path.startswith('/dir/'):
            pass
        else:
            return self.reply(404, {'Content-Type': 'text/plain'}, b'unknown', send_body)
        data = DATA
        if path == '/noetag.bin':
            etag = modified = None
        if path in ('/norange.bin', '/nosize.bin'):
            ranged = False
        if path in ('/chunked.bin', '/nosize.bin'):
            chunked = True
        if path == '/changed.bin':
            etag = '"v2-changed"'
        if path == '/short.bin':
            data = DATA[:500_000]
            etag = '"v1-short"'
        if path == '/late-redirect.bin' and len(server.requests('/late-redirect.bin')) > 1:
            return self.reply(302, {'Location': 'http://example.com/elsewhere.bin'}, b'', send_body)
        if path == '/swap.bin' and len(server.requests('/swap.bin')) > 1:
            data = DATA[:500_000]  # the file changed after it was resolved
        if path.startswith('/expiring/'):
            name_token = path.split('/')[2].split('.')[0]
            if name_token in server.expired:
                return self.reply(403, {'Content-Type': 'text/plain'}, b'expired', send_body)
        headers = dict(octet)
        if etag:
            headers['ETag'] = etag
        if modified:
            headers['Last-Modified'] = modified
        if ranged:
            headers['Accept-Ranges'] = 'bytes'
        if disposition:
            headers['Content-Disposition'] = disposition
        if if_match and etag and if_match != etag:
            return self.reply(412, {'Content-Type': 'text/plain'}, b'precondition', send_body)
        start, end, status = 0, len(data) - 1, 200
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', rng or '')
        if match and ranged:
            first, last = match.groups()
            start = int(first) if first else 0
            end = min(int(last), len(data) - 1) if last else len(data) - 1
            if start >= len(data):
                return self.reply(416, {'Content-Range': f'bytes */{len(data)}'}, b'', send_body)
            status = 206
            headers['Content-Range'] = f'bytes {start}-{end}/{len(data)}'
        body = data[start:end + 1]
        if chunked:
            headers['Transfer-Encoding'] = 'chunked'
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            if send_body:
                for i in range(0, len(body), 65536):
                    chunk = body[i:i + 65536]
                    self.wfile.write(f'{len(chunk):x}\r\n'.encode() + chunk + b'\r\n')
                self.wfile.write(b'0\r\n\r\n')
            return
        headers['Content-Length'] = str(len(body))
        cut = server.cut_once.get(path) if send_body and len(body) > 1000 else None
        if cut is not None and server.cut_once.pop(path, None) is not None:
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body[:cut])
            self.wfile.flush()
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return
        self.reply(status, headers, body, send_body)


class Origin(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self):
        super().__init__(('127.0.0.1', 0), Handler)
        self.log, self.cut_once, self.expired = [], {}, set()
        self.lock = threading.Lock()
        self.big_served, self.big_hold_after, self.big_delay = 0, None, 0.0
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def base(self):
        return f'http://127.0.0.1:{self.server_address[1]}'

    def requests(self, path):
        with self.lock:
            return [entry for entry in self.log if entry[1] == path]


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Service:
    def __init__(self, root, origin, binary=None):
        self.binary = binary or BIN
        self.root = pathlib.Path(root)
        self.state, self.storage = self.root / 'state', self.root / 'storage'
        self.state.mkdir(exist_ok=True)
        self.storage.mkdir(exist_ok=True)
        self.origin, self.port, self.token, self.process = origin, free_port(), None, None

    def start(self, extra_env=None):
        # A restart keeps the environment the service was first started with (a test of recovery must not change the layout).
        if extra_env is not None:
            self.extra_env = dict(extra_env)
        env = dict(os.environ, ORBIT_TEST_URL=self.origin.base + '/fixture.bin', ORBIT_TEST_SIZE='1024',
                   ORBIT_TEST_FILEDITCH_API='http://127.0.0.1:1/api')
        env.update(getattr(self, 'extra_env', {}))
        self.process = subprocess.Popen(
            [str(self.binary), '--state', str(self.state), '--storage', str(self.storage), '--port', str(self.port)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        code, lines = None, []
        deadline = time.time() + 20
        while time.time() < deadline and code is None:
            line = self.process.stdout.readline()
            if not line:
                break
            lines.append(line)
            match = re.search(r'Pairing code: (\d{6})', line)
            code = match.group(1) if match else None
        if code is None:
            raise RuntimeError('service did not start: ' + ''.join(lines))
        threading.Thread(target=lambda: [None for _ in self.process.stdout], daemon=True).start()
        for _ in range(100):
            try:
                if self.call('GET', '/api/v1/system', auth=False)[0] == 200:
                    break
            except OSError:
                time.sleep(0.1)
        if not self.token:
            status, body = self.call('POST', '/api/v1/pair', {'code': code}, auth=False)
            assert status == 200, body
            self.token = body['token']

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(15)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def call(self, method, path, body=None, auth=True):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=data, method=method)
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

    def enable(self, *sources):
        status, body = self.call('POST', '/api/v1/sources', {'enabled': list(sources), 'noticeVersion': 1, 'acknowledged': True})
        assert status == 200, body

    def resolve(self, url, filename=None, size=None, timeout=20):
        body = {'action': 'resolve', 'url': url}
        if filename:
            body['filename'] = filename
        if size:
            body['sizeBytes'] = size
        status, reply = self.call('POST', '/api/v1/custom/resolve', body)
        assert status == 202, (status, reply)
        return self.wait_resolve(timeout)

    def wait_resolve(self, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            status, reply = self.call('GET', '/api/v1/custom/resolve')
            if status == 200 and reply.get('state') != 'resolving':
                return reply
            time.sleep(0.1)
        raise AssertionError('resolve timed out')

    def storage_id(self):
        status, drives = self.call('GET', '/api/v1/storage')
        assert status == 200 and drives, drives
        return drives[0]['id']

    def queue(self, release_id, delivery='direct'):
        return self.call('POST', '/api/v1/downloads', {'releaseId': release_id, 'storageId': self.storage_id(), 'delivery': delivery})

    def jobs(self):
        return self.call('GET', '/api/v1/downloads')[1]

    def job(self, job_id):
        return next((j for j in self.jobs() if j['id'] == job_id), None)

    def wait_job(self, job_id, states, timeout=60):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = self.job(job_id)
            if last and last['status'] in states:
                return last
            time.sleep(0.2)
        raise AssertionError(f'job stuck at {last}')

    def act(self, job_id, action, **body):
        return self.call('POST', f'/api/v1/downloads/{job_id}/{action}', body or {})


def sha256_file(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


class Base(unittest.TestCase):
    sources = ('web',)

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.origin = Origin()
        cls.service = Service(cls.tmp.name, cls.origin)
        cls.service.start()
        if cls.sources:
            cls.service.enable(*cls.sources)

    @classmethod
    def tearDownClass(cls):
        cls.service.stop()
        cls.origin.shutdown()
        cls.tmp.cleanup()

    def name(self, suffix='.bin'):
        return self._testMethodName + suffix

    def ready(self, path, name=None, **extra):
        reply = self.service.resolve(self.origin.base + path, name or self.name(), **extra)
        self.assertEqual(reply['state'], 'ready', reply)
        return reply

    def download(self, reply, timeout=60):
        status, body = self.service.queue(reply['releaseId'])
        self.assertEqual(status, 201, body)
        job = self.service.wait_job(body['id'], {'complete', 'error'}, timeout)
        return body['id'], job


class SourceGate(Base):
    sources = ()

    def test_provider_must_be_enabled_first(self):
        reply = self.service.resolve(self.origin.base + '/file.bin')
        self.assertEqual(reply['state'], 'source-disabled')
        self.assertEqual(reply['provider'], 'web')
        self.assertNotIn('releaseId', reply)
        self.assertEqual(self.origin.requests('/file.bin'), [], 'nothing may be fetched before consent')

    def test_hosts_without_a_working_flow_are_refused_with_a_reason(self):
        for url in ('https://new.fileditch.com/a/b.bin', 'https://itsfileditchfiles.st/balpha34/abc/x.bin'):
            reply = self.service.resolve(url)
            self.assertEqual((reply['state'], reply['provider']), ('unsupported', 'fileditch'), reply)
            self.assertIn('Cloudflare', reply['message'])

    def test_torbox_only_hosts_need_their_toggle_first(self):
        for url in ('https://gofile.io/d/AbCdEf', 'https://fuckingfast.co/abc', 'https://rootz.so/d/ba7ua',
                    'https://1fichier.com/?abcdefghij0123456789'):
            self.assertEqual(self.service.resolve(url)['state'], 'source-disabled', url)


class Resolve(Base):
    def test_direct_file_details(self):
        reply = self.service.resolve(self.origin.base + '/file.bin')
        self.assertEqual(reply['state'], 'ready', reply)
        self.assertEqual((reply['filename'], reply['sizeBytes'], reply['provider']), ('file.bin', len(DATA), 'web'))
        self.assertTrue(reply['resumable'])
        self.assertTrue(reply['delivery']['direct'])
        self.assertFalse(reply['delivery']['torbox'])
        self.assertTrue(reply['releaseId'].startswith('custom-'))

    def test_redirect_chain_is_followed(self):
        reply = self.service.resolve(self.origin.base + '/redirect1')
        self.assertEqual((reply['state'], reply['filename']), ('ready', 'file.bin'), reply)

    def test_redirect_loop_is_an_error(self):
        self.assertEqual(self.service.resolve(self.origin.base + '/loop')['state'], 'error')

    def test_redirect_to_other_hosts_or_schemes_is_refused(self):
        for path in ('/offsite', '/offscheme'):
            reply = self.service.resolve(self.origin.base + path)
            self.assertEqual(reply['state'], 'error', reply)
            self.assertIn('will not download from', reply['message'])

    def test_pages_and_errors_are_never_reported_as_files(self):
        expectations = {'/html': 'web page', '/json': 'web page', '/missing': 'not found', '/gone': 'not found',
                        '/forbidden': 'refused access', '/busy': 'temporarily unavailable'}
        for path, text in expectations.items():
            reply = self.service.resolve(self.origin.base + path)
            self.assertEqual(reply['state'], 'error', (path, reply))
            self.assertIn(text, reply['message'], path)
            self.assertNotIn('releaseId', reply)

    def test_filename_sources(self):
        self.assertEqual(self.service.resolve(self.origin.base + '/disp-plain')['filename'], 'Report 1.bin')
        self.assertEqual(self.service.resolve(self.origin.base + '/disp-star')['filename'], '€ price.bin')
        self.assertEqual(self.service.resolve(self.origin.base + '/dir/My%20Archive.bin')['filename'], 'My Archive.bin')
        self.assertEqual(self.service.resolve(self.origin.base + '/file.bin', 'Custom Name.bin')['filename'], 'Custom Name.bin')

    def test_unsafe_names_are_made_safe_or_refused(self):
        self.assertEqual(self.service.resolve(self.origin.base + '/disp-evil')['filename'], 'evil.bin')
        self.assertEqual(self.service.resolve(self.origin.base + '/disp-part')['filename'], 'game_part')
        self.assertEqual(self.service.resolve(self.origin.base + '/file.bin', '../../x/evil.bin')['filename'], 'evil.bin')
        # With only an unusable name from the host, the URL's own name is used instead.
        self.assertEqual(self.service.resolve(self.origin.base + '/disp-dots')['state'], 'ready')

    def test_unknown_length_is_refused(self):
        # No Content-Length and no byte range: the queue needs the size up front.
        reply = self.service.resolve(self.origin.base + '/nosize.bin')
        self.assertEqual(reply['state'], 'error', reply)
        self.assertIn('file size', reply['message'])
        # A chunked reply that still reports its total through a byte range is fine.
        reply = self.service.resolve(self.origin.base + '/chunked.bin')
        self.assertEqual((reply['state'], reply['sizeBytes']), ('ready', len(DATA)), reply)

    def test_range_less_host_is_flagged_not_resumable(self):
        reply = self.service.resolve(self.origin.base + '/norange.bin')
        self.assertEqual((reply['state'], reply['resumable']), ('ready', False), reply)

    def test_invalid_input_never_reaches_the_network(self):
        for url in ('ftp://127.0.0.1/x', 'file:///etc/passwd', 'http://example.com/x', 'https://u:p@127.0.0.1/x',
                    'javascript:alert(1)', 'not a url', 'https://127.0.0.1:1/ x'):
            status, reply = self.service.call('POST', '/api/v1/custom/resolve', {'action': 'resolve', 'url': url})
            if status == 202:
                reply = self.service.wait_resolve()
                self.assertEqual(reply['state'], 'error', url)
            else:
                self.assertIn(status, (400,), url)
        status, _ = self.service.call('POST', '/api/v1/custom/resolve', {'action': 'resolve', 'url': 'x' * 3000})
        self.assertEqual(status, 400)
        status, _ = self.service.call('POST', '/api/v1/custom/resolve', {'action': 'resolve'})
        self.assertEqual(status, 400)

    def test_archives_are_identified(self):
        reply = self.service.resolve(self.origin.base + '/file.bin', 'bundle.7z')
        self.assertEqual((reply['state'], reply['archive']), ('ready', True), reply)

    def test_authentication_is_required(self):
        status, _ = self.service.call('POST', '/api/v1/custom/resolve', {'action': 'resolve', 'url': self.origin.base}, auth=False)
        self.assertEqual(status, 401)
        self.assertEqual(self.service.call('GET', '/api/v1/custom/catalog', auth=False)[0], 401)


class Downloads(Base):
    def test_download_matches_the_origin_exactly(self):
        reply = self.ready('/file.bin')
        _, job = self.download(reply)
        self.assertEqual(job['status'], 'complete', job)
        self.assertEqual(sha256_file(job['path'].replace(self.service.storage.as_posix(), self.service.storage.as_posix())),
                         hashlib.sha256(DATA).hexdigest())
        self.assertEqual(job['sourceId'], 'web')
        self.assertEqual(job['origin'], 'local')

    def test_download_through_redirects(self):
        _, job = self.download(self.ready('/redirect1'))
        self.assertEqual(job['status'], 'complete', job)
        self.assertEqual(sha256_file(job['path']), hashlib.sha256(DATA).hexdigest())

    def test_host_without_range_support_downloads_as_one_stream(self):
        reply = self.ready('/norange.bin')
        self.assertFalse(reply['resumable'])
        _, job = self.download(reply)
        self.assertEqual(job['status'], 'complete', job)
        self.assertEqual(sha256_file(job['path']), hashlib.sha256(DATA).hexdigest())

    def test_destination_is_never_overwritten(self):
        first = self.ready('/file.bin', 'collide.bin')
        self.assertEqual(self.download(first)[1]['status'], 'complete')
        second = self.ready('/file.bin', 'collide.bin')
        status, body = self.service.queue(second['releaseId'])
        self.assertEqual(status, 409, body)

    def test_unknown_release_id_is_rejected(self):
        status, _ = self.service.queue('custom-000000000000')
        self.assertIn(status, (404, 409))

    def test_interrupted_download_resumes_with_a_range_and_matches(self):
        self.origin.cut_once['/flaky.bin'] = CUT_AT
        reply = self.ready('/flaky.bin')
        job_id, job = self.download(reply, timeout=120)
        self.assertEqual(job['status'], 'complete', job)
        self.assertEqual(sha256_file(job['path']), hashlib.sha256(DATA).hexdigest())
        resumed = [r for r in self.origin.requests('/flaky.bin') if r[2] and re.match(r'bytes=(\d+)-', r[2])
                   and int(re.match(r'bytes=(\d+)-', r[2]).group(1)) > 0]
        self.assertTrue(resumed, 'the retry must ask for a byte range after the cut')
        self.assertTrue(all(r[3] == ETAG for r in resumed), 'resume must be conditioned on the validator')

    def test_interrupted_download_without_validators_is_not_resumed_blindly(self):
        self.origin.cut_once['/noetag.bin'] = CUT_AT
        reply = self.ready('/noetag.bin')
        status, body = self.service.queue(reply['releaseId'])
        self.assertEqual(status, 201, body)
        job = self.service.wait_job(body['id'], {'error', 'complete'}, 120)
        self.assertEqual(job['status'], 'error', job)
        self.assertIn('identity', job['error'])
        partial = pathlib.Path(job['path'] + '.part')
        self.assertTrue(partial.exists() and 0 < partial.stat().st_size < len(DATA), 'the partial file must be kept')

    def test_file_that_changes_after_resolve_is_not_accepted(self):
        reply = self.ready('/swap.bin')
        self.assertEqual(reply['sizeBytes'], len(DATA))
        status, body = self.service.queue(reply['releaseId'])
        self.assertEqual(status, 201, body)
        job = self.service.wait_job(body['id'], {'error', 'complete', 'retrying'}, 60)
        self.assertNotEqual(job['status'], 'complete', job)
        self.assertFalse(pathlib.Path(job['path']).exists(), 'no finished file may appear for a changed source')

    def test_redirect_added_after_resolve_is_refused_at_transfer_time(self):
        reply = self.ready('/late-redirect.bin')
        status, body = self.service.queue(reply['releaseId'])
        self.assertEqual(status, 201, body)
        job = self.service.wait_job(body['id'], {'error', 'complete', 'retrying'}, 60)
        self.assertEqual(job['status'], 'error', job)
        self.assertIn('unsupported download', job['error'])
        self.assertFalse(pathlib.Path(job['path']).exists())

    def test_pause_resume_and_cancel(self):
        reply = self.ready('/file.bin')
        status, body = self.service.queue(reply['releaseId'])
        self.assertEqual(status, 201, body)
        self.service.act(body['id'], 'pause')
        job = self.service.wait_job(body['id'], {'paused', 'complete'}, 30)
        if job['status'] == 'paused':
            self.assertEqual(self.service.act(body['id'], 'resume')[0], 200)
            job = self.service.wait_job(body['id'], {'complete', 'error'}, 60)
        self.assertEqual(job['status'], 'complete', job)
        again = self.ready('/file.bin', self.name('-b.bin'))
        status, body = self.service.queue(again['releaseId'])
        self.service.act(body['id'], 'cancel')
        job = self.service.wait_job(body['id'], {'cancelled', 'complete'}, 30)
        self.assertIn(job['status'], ('cancelled', 'complete'))


class Refresh(Base):
    def interrupted_expiring_job(self, token):
        self.origin.cut_once[f'/expiring/{token}.bin'] = CUT_AT
        reply = self.ready(f'/expiring/{token}.bin', self.name())
        status, body = self.service.queue(reply['releaseId'])
        self.assertEqual(status, 201, body)
        # The cut produces a retry; expire the link before the retry can use it.
        deadline = time.time() + 30
        while time.time() < deadline and not self.origin.requests(f'/expiring/{token}.bin')[2:]:
            time.sleep(0.05)
        self.origin.expired.add(token)
        job = self.service.wait_job(body['id'], {'error', 'retrying', 'paused'}, 120)
        if job['status'] == 'retrying':
            self.service.act(body['id'], 'pause')
            job = self.service.wait_job(body['id'], {'paused', 'error'}, 60)
        return body['id'], job

    def refresh(self, job_id, url):
        status, reply = self.service.call('POST', '/api/v1/custom/resolve', {'action': 'refresh', 'jobId': job_id, 'url': url})
        self.assertEqual(status, 202, reply)
        return self.service.wait_resolve()

    def test_expired_link_can_be_replaced_and_resumes(self):
        job_id, job = self.interrupted_expiring_job('old1')
        self.assertTrue(job['canRefreshUrl'] and job['canRefreshLink'], job)
        status, body = self.service.act(job_id, 'refresh-link')
        self.assertEqual(status, 409, body)
        self.assertIn('pasted link', body['error'])
        reply = self.refresh(job_id, self.origin.base + '/expiring/new1.bin')
        self.assertEqual(reply['state'], 'refreshed', reply)
        job = self.service.wait_job(job_id, {'complete', 'error'}, 120)
        self.assertEqual(job['status'], 'complete', job)
        self.assertEqual(sha256_file(job['path']), hashlib.sha256(DATA).hexdigest())

    def test_a_different_file_never_replaces_a_partial(self):
        job_id, job = self.interrupted_expiring_job('old2')
        for path, text in (('/changed.bin', 'confirm'), ('/short.bin', 'different size')):
            reply = self.refresh(job_id, self.origin.base + path)
            self.assertEqual(reply['state'], 'error', (path, reply))
            self.assertIn(text, reply['message'])
        self.assertTrue(pathlib.Path(job['path'] + '.part').exists(), 'the partial file must survive a refused refresh')
        reply = self.refresh(job_id, 'https://example.com/other.bin')
        self.assertEqual(reply['state'], 'error')

    def test_refresh_needs_a_stopped_download(self):
        reply = self.ready('/file.bin')
        job_id, job = self.download(reply)
        self.assertEqual(job['status'], 'complete')
        self.assertFalse(job['canRefreshUrl'])
        self.assertEqual(self.refresh(job_id, self.origin.base + '/file.bin')['state'], 'error')


class LinkCatalogue(Base):
    def entries(self):
        return [
            {'title': 'Mine A', 'titleId': 'PPSA01234', 'platform': 'ps5', 'format': 'exFAT', 'url': 'https://downloads.example.org/a.exfat'},
            {'title': 'Bad title id', 'titleId': 'PPSA1', 'url': 'https://downloads.example.org/b.exfat'},
            {'title': 'Rootz', 'url': 'https://rootz.so/file/abc'},
            {'title': 'Not https', 'url': 'http://downloads.example.org/c.bin'},
            {'title': 'Gofile', 'url': 'https://gofile.io/d/AbCdEf'},
            {'title': 'Fileditch', 'url': 'https://new.fileditch.com/x/y.bin', 'filename': 'y.bin', 'sizeBytes': 12},
            {'url': 'https://downloads.example.org/d.bin'},
            {'title': 'Unsafe name', 'url': 'https://downloads.example.org/e.bin', 'filename': '../e.bin'},
        ]

    def test_import_validates_each_entry_and_reports_why(self):
        status, body = self.service.call('POST', '/api/v1/custom/catalog',
                                         {'action': 'import', 'catalogue': {'format': 'orbit-custom-catalogue', 'version': 1, 'entries': self.entries()}})
        self.assertEqual(status, 200, body)
        self.assertEqual(body['result']['imported'], 2)
        rejected = {r['index']: r['reason'] for r in body['result']['rejected']}
        self.assertEqual(sorted(rejected), [1, 2, 3, 5, 6, 7])
        self.assertIn('human-verification', rejected[5])
        self.assertIn('not a link Orbit can open', rejected[2])
        self.assertEqual({l['title'] for l in body['links']}, {'Mine A', 'Gofile'})
        self.assertTrue(all(l['id'].startswith('link-') for l in body['links']))

    def test_the_documented_example_imports_cleanly(self):
        example = json.loads((ROOT / 'docs' / 'custom-catalogue.example.json').read_text())
        status, body = self.service.call('POST', '/api/v1/custom/catalog', {'action': 'import', 'catalogue': example})
        self.assertEqual(status, 200, body)
        self.assertEqual((body['result']['imported'], body['result']['rejected']), (len(example['entries']), []))
        self.service.call('POST', '/api/v1/custom/catalog', {'action': 'clear'})

    def test_merge_replace_remove_and_clear(self):
        one = {'title': 'One', 'url': 'https://downloads.example.org/1.bin'}
        two = {'title': 'Two', 'url': 'https://downloads.example.org/2.bin'}
        call = self.service.call
        call('POST', '/api/v1/custom/catalog', {'action': 'import', 'entries': [one]})
        links = call('POST', '/api/v1/custom/catalog', {'action': 'import', 'mode': 'merge', 'entries': [two, dict(one, title='One renamed')]})[1]['links']
        self.assertEqual(sorted(l['title'] for l in links), ['One renamed', 'Two'])
        first = next(l for l in links if l['title'] == 'One renamed')
        links = call('POST', '/api/v1/custom/catalog', {'action': 'import', 'entries': [two]})[1]['links']
        self.assertEqual([l['title'] for l in links], ['Two'])
        self.assertEqual(call('POST', '/api/v1/custom/catalog', {'action': 'remove', 'id': first['id']})[0], 404)
        self.assertEqual(call('POST', '/api/v1/custom/catalog', {'action': 'remove', 'id': links[0]['id']})[1]['links'], [])
        call('POST', '/api/v1/custom/catalog', {'action': 'import', 'entries': [one, two]})
        self.assertEqual(call('POST', '/api/v1/custom/catalog', {'action': 'clear'})[1]['links'], [])

    def test_malformed_catalogues_are_rejected_whole(self):
        for body in ({'action': 'import', 'entries': []}, {'action': 'import'}, {'action': 'import', 'entries': 'x'},
                     {'action': 'import', 'catalogue': {'format': 'other', 'entries': [{'title': 'x', 'url': 'https://a.example/b'}]}},
                     {'action': 'bogus'}):
            self.assertEqual(self.service.call('POST', '/api/v1/custom/catalog', body)[0], 400, body)

    def test_large_import_within_limit(self):
        entries = [{'title': f'Game {i}', 'url': f'https://downloads.example.org/{i}.bin'} for i in range(200)]
        status, body = self.service.call('POST', '/api/v1/custom/catalog', {'action': 'import', 'entries': entries})
        self.assertEqual((status, body['result']['imported']), (200, 200), body)
        self.service.call('POST', '/api/v1/custom/catalog', {'action': 'clear'})


class Persistence(Base):
    def test_links_and_queue_survive_a_restart(self):
        self.service.call('POST', '/api/v1/custom/catalog', {'action': 'import', 'entries': [
            {'title': 'Kept', 'url': 'https://downloads.example.org/kept.bin'}]})
        reply = self.ready('/file.bin', 'persist.bin')
        job_id, job = self.download(reply)
        self.assertEqual(job['status'], 'complete')
        self.service.act(job_id, 'forget')
        again = self.ready('/flaky.bin', 'persist-queued.bin')
        status, body = self.service.queue(again['releaseId'])
        self.assertEqual(status, 201, body)
        self.service.act(body['id'], 'pause')
        self.service.wait_job(body['id'], {'paused', 'complete'}, 30)
        self.service.stop()
        state = json.loads((self.service.state / 'state.json').read_text())
        local = [j for j in state['jobs'] if j['release'].get('origin') == 'local']
        self.assertTrue(local and state['schema'] == 7, 'a queue holding a pasted link must use schema 7')
        self.service.start()
        self.assertIn('Kept', [l['title'] for l in self.service.call('GET', '/api/v1/custom/catalog')[1]['links']])
        restored = self.service.job(body['id'])
        self.assertIsNotNone(restored, 'the queued pasted link must reload')
        self.assertEqual((restored['filename'], restored['sourceId'], restored['origin']), ('persist-queued.bin', 'web', 'local'))
        self.service.call('POST', '/api/v1/custom/catalog', {'action': 'clear'})

    def test_tampered_queue_cannot_escape_the_download_folder(self):
        reply = self.ready('/file.bin', 'tamper-source.bin')
        status, body = self.service.queue(reply['releaseId'])
        self.assertEqual(status, 201, body)
        self.service.act(body['id'], 'pause')
        self.service.wait_job(body['id'], {'paused', 'complete'}, 30)
        self.service.stop()
        path = self.service.state / 'state.json'
        original = path.read_text()
        state = json.loads(original)
        for job in state['jobs']:
            if job['release'].get('origin') == 'local':
                job['release']['filename'] = '../../escape.bin'
                job['filename'] = '../../escape.bin'
        path.write_text(json.dumps(state))
        try:
            # The safe outcome is to refuse the whole queue and keep it for recovery.
            with self.assertRaises(RuntimeError) as raised:
                self.service.start()
            self.assertIn('Preserving state', str(raised.exception))
            self.assertFalse((self.service.root / 'escape.bin').exists())
            self.assertFalse((self.service.storage.parent / 'escape.bin').exists())
        finally:
            self.service.stop()
            path.write_text(original)
            self.service.start()

    def test_queue_without_pasted_links_keeps_the_official_schema(self):
        state = json.loads((self.service.state / 'state.json').read_text()) if (self.service.state / 'state.json').exists() else {'schema': 4}
        if not any(j['release'].get('origin') == 'local' for j in state.get('jobs', [])):
            self.assertLessEqual(state['schema'], 6)



class TorBoxMock(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Just enough of TorBox's web-download API for one finished single-file download."""
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, origin, domains, hosters=None):
        super().__init__(('127.0.0.1', 0), TorBoxHandler)
        self.origin, self.domains, self.items, self.calls = origin, domains, {}, []
        self.hosters = hosters  # a complete /webdl/hosters answer, when a test needs TorBox's real shape
        self.create_error = None  # (http status, TorBox error code) to answer createwebdownload with
        self.item_state = 'completed'  # what a created download then reports
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def base(self):
        return f'http://127.0.0.1:{self.server_address[1]}'


class TorBoxHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    NAME = 'torbox-sample.bin'

    def log_message(self, *args):
        pass

    def send_json(self, data):
        body = json.dumps({'success': True, 'data': data}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def item(self, ident, link):
        done = self.server.item_state == 'completed'
        return {'id': ident, 'original_url': link, 'download_state': self.server.item_state, 'download_present': done,
                'download_finished': done, 'files': [{'id': 1, 'name': self.NAME, 'short_name': self.NAME,
                                                      'size': len(DATA), 'infected': False, 'zipped': False}]}

    def do_POST(self):
        length = int(self.headers.get('Content-Length') or 0)
        form = urllib.parse.parse_qs(self.rfile.read(length).decode())
        self.server.calls.append(('POST', self.path, form))
        if self.path.startswith('/webdl/createwebdownload') and self.server.create_error:
            status, code = self.server.create_error
            body = json.dumps({'success': False, 'error': code, 'detail': 'see https://secret.example/token=abc123 for your key sk-live-9999',
                               'data': None}).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith('/webdl/createwebdownload'):
            link = form['link'][0]
            self.server.items[77] = link
            return self.send_json({'webdownload_id': 77})
        self.send_json({})

    def do_GET(self):
        path, _, query = self.path.partition('?')
        args = urllib.parse.parse_qs(query)
        self.server.calls.append(('GET', self.path, None))
        if path == '/user/me':
            return self.send_json({'id': 4242})
        if path == '/webdl/hosters' and self.server.hosters is not None:
            return self.send_json(self.server.hosters)
        if path == '/webdl/hosters':
            return self.send_json([{'name': d, 'domains': [d], 'status': True, 'per_link_size_limit': 0,
                                    'daily_bandwidth_limit': 0, 'daily_link_limit': 0} for d in self.server.domains])
        if path == '/webdl/mylist':
            items = [self.item(i, link) for i, link in self.server.items.items()]
            return self.send_json(items[0] if 'id' in args and items else items)
        if path == '/webdl/requestdl':
            return self.send_json(f'{self.server.origin.base}/torbox-cdn/{self.NAME}')
        self.send_json({})


class TorBoxBase(Base):
    sources = ('gofile', 'fuckingfast', '1fichier')
    domains = ['gofile.io', '1fichier.com', '127.0.0.1']

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.origin = Origin()
        cls.torbox = TorBoxMock(cls.origin, cls.domains)
        cls.service = Service(cls.tmp.name, cls.origin)
        cls.service.start({'ORBIT_TEST_TORBOX_URL': cls.torbox.base})
        cls.service.enable(*cls.sources)

    @classmethod
    def tearDownClass(cls):
        cls.torbox.shutdown()
        super().tearDownClass()

    def connect(self):
        state = self.service.call('GET', '/api/v1/debrid')[1]
        if state['connected'] and not state['busy'] and state['checkedAt']:
            return state  # TorBox itself limits how often an account may be rechecked
        time.sleep(max(0, state.get('retryAt', 0) - time.time()) + 0.5)
        status, body = self.service.call('POST', '/api/v1/debrid', {'action': 'connect', 'apiKey': 'k' * 24})
        self.assertEqual(status, 202, body)
        deadline = time.time() + 20
        while time.time() < deadline:
            state = self.service.call('GET', '/api/v1/debrid')[1]
            if state['connected'] and not state['busy']:
                return state
            time.sleep(0.2)
        self.fail('TorBox did not connect')


class TorBoxLinks(TorBoxBase):
    def test_a_1_torbox_must_be_connected_first(self):
        reply = self.service.resolve('https://gofile.io/d/AbCdEf')
        self.assertEqual(reply['state'], 'unsupported', reply)
        self.assertIn('Connect TorBox', reply['message'])
        self.assertIn('premium', reply['message'])
        browser = self.service.resolve('https://1fichier.com/?abcdefghij0123456789')
        self.assertEqual(browser['state'], 'needs-browser', browser)
        self.assertTrue(browser['sizePending'] and browser['viaBrowser'])
        self.assertFalse(browser['delivery']['torbox'])

    def test_a_2_hosts_torbox_does_not_list_are_refused(self):
        self.connect()
        reply = self.service.resolve('https://fuckingfast.co/abc')
        self.assertEqual(reply['state'], 'unsupported', reply)
        self.assertIn('does not list', reply['message'])

    def test_b_1_one_pending_link_offers_both_the_browser_and_torbox(self):
        self.connect()
        reply = self.service.resolve('https://1fichier.com/?abcdefghij0123456789')
        self.assertEqual(reply['state'], 'needs-browser', reply)
        self.assertTrue(reply['delivery']['direct'] and reply['delivery']['torbox'], reply)
        self.assertTrue(reply['sizePending'])

    def test_c_torbox_only_download_adopts_torbox_name_and_size(self):
        self.connect()
        reply = self.service.resolve('https://gofile.io/d/AbCdEf')
        self.assertEqual(reply['state'], 'ready', reply)
        self.assertEqual((reply['delivery']['torbox'], reply['delivery']['direct'], reply['sizePending']), (True, False, True))
        # Direct delivery of a TorBox-only host must be impossible.
        status, body = self.service.queue(reply['releaseId'], 'direct')
        self.assertEqual(status, 409, body)
        status, body = self.service.queue(reply['releaseId'], 'torbox')
        self.assertEqual(status, 201, body)
        job = self.service.wait_job(body['id'], {'complete', 'error'}, 150)
        self.assertEqual(job['status'], 'complete', job)
        self.assertEqual((job['filename'], job['total']), (TorBoxHandler.NAME, len(DATA)), job)
        self.assertEqual(job['delivery'], 'torbox')
        self.assertEqual(sha256_file(job['path']), hashlib.sha256(DATA).hexdigest())
        folder = pathlib.Path(job['path']).parent
        self.assertEqual([p.name for p in folder.glob('*.part')], [], 'no placeholder partial may be left behind')
        created = [c for c in self.torbox.calls if c[1].startswith('/webdl/createwebdownload')]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0][2]['link'][0], 'https://gofile.io/d/AbCdEf')


def torbox_hosters(before, extra_domains=()):
    """A /webdl/hosters answer shaped like TorBox's real one (2026-10-20: 162 hosters, 378 domains, several domains per
    hoster, ViKiNG FiLE near the end with three), with `before` filler domains ahead of the hosters under test."""
    def hoster(n, name, domains, status=True):
        pattern = '|'.join(d.replace('.', '\\.') for d in domains)
        return {'id': n, 'name': name, 'domains': list(domains), 'url': f'https://{domains[0]}', 'icon': 'https://example.invalid/i.png',
                'status': status, 'type': 'hoster', 'note': None, 'nsfw': False, 'daily_link_limit': 100, 'daily_link_used': 0,
                'daily_bandwidth_limit': 10737418240000, 'daily_bandwidth_used': 0, 'per_link_size_limit': 107374182400,
                'regex': f'^https?://(?:[^./]+\\.)*({pattern})(/|$)'}
    rows = [hoster(n, f'Filler {n}', [f'filler{n}-a.example', f'filler{n}-b.example']) for n in range(before // 2)]
    rows += [hoster(9001, 'Off Host', ['rapidgator.example'], status=False),
             hoster(9002, 'Data Nodes', ['datanodes.to']),
             hoster(9003, 'ViKiNG FiLE', ['vikingfile.com', 'vikingf1le.us.to', 'vik1ngfile.site']),
             hoster(9004, 'Local', ['127.0.0.1'])]
    rows += [hoster(9100 + i, f'Late {i}', [d]) for i, d in enumerate(extra_domains)]
    return rows


class TorBoxRealShapeList(TorBoxBase):
    """Regression: Vikingfile was listed in settings but refused for pasted links, because the first fork build kept only the
    first 256 of TorBox's domains and Vikingfile sits at about number 340."""
    sources = ('vikingfile', 'datanodes')
    BEFORE = 338  # ViKiNG FiLE's first domain is then number 341, as in the real answer

    @classmethod
    def hosters(cls):
        return torbox_hosters(cls.BEFORE)

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.origin = Origin()
        cls.torbox = TorBoxMock(cls.origin, [], cls.hosters())
        cls.service = Service(cls.tmp.name, cls.origin)
        cls.service.start({'ORBIT_TEST_TORBOX_URL': cls.torbox.base,
                           'ORBIT_TEST_VIKING_API': cls.origin.base + '/viking/check-file'})
        cls.service.enable(*cls.sources)

    def test_every_vikingfile_domain_gets_a_torbox_choice(self):
        self.connect()
        for host in ('vikingfile.com', 'vik1ngfile.site'):  # the two Vikingfile domains Orbit itself recognises
            reply = self.service.resolve(f'https://{host}/f/abcdefghij')
            self.assertEqual(reply['state'], 'needs-browser', (host, reply))
            self.assertTrue(reply['delivery']['torbox'], (host, reply))

    def test_the_settings_list_and_the_link_dialog_agree(self):
        state = self.connect()
        offered = {h['sourceId']: h['available'] for h in state['hosts']}
        self.assertTrue(offered['vikingfile'] and offered['datanodes'], state)
        self.assertGreaterEqual(state['listedDomains'], 2 * (self.BEFORE // 2) + 5, 'every domain TorBox listed must be kept')
        reply = self.service.resolve('https://vikingfile.com/f/abcdefghij')
        self.assertEqual(reply['delivery']['torbox'], offered['vikingfile'], reply)

    def test_matching_stays_exact(self):
        self.connect()
        for link in ('https://notvikingfile.com/f/abcdefghij', 'https://vikingfile.com.evil.example/f/abcdefghij',
                     'https://vikingfile.co/f/abcdefghij'):
            reply = self.service.resolve(link)
            self.assertNotEqual(reply.get('state'), 'ready', (link, reply))
            self.assertFalse(reply.get('delivery', {}).get('torbox'), (link, reply))

    def test_a_listed_but_switched_off_host_is_still_refused(self):
        self.connect()
        reply = self.service.resolve('https://rapidgator.example/file/abc')
        self.assertFalse(reply.get('delivery', {}).get('torbox'), reply)


class TorBoxOversizedAnswer(TorBoxRealShapeList):
    """An answer past Orbit's 1 MiB limit must fail closed (no connection, no TorBox choice), never be cut short."""
    BEFORE = 17000

    def test_every_vikingfile_domain_gets_a_torbox_choice(self):
        self.service.call('POST', '/api/v1/debrid', {'action': 'connect', 'apiKey': 'k' * 24})
        for _ in range(100):
            state = self.service.call('GET', '/api/v1/debrid')[1]
            if not state['busy'] and state['error']:
                break
            time.sleep(0.2)
        self.assertFalse(state['connected'], state)
        self.assertTrue(state['error'], state)
        reply = self.service.resolve('https://vikingfile.com/f/abcdefghij')
        self.assertFalse(reply['delivery']['torbox'], reply)

    test_the_settings_list_and_the_link_dialog_agree = test_matching_stays_exact = None
    test_a_listed_but_switched_off_host_is_still_refused = None


class TorBoxRejections(unittest.TestCase):
    """A link TorBox refuses must be explained, never relayed as free text, and never queued as success."""
    CASES = [('LINK_OFFLINE', 'offline or has been removed'),
             ('DOWNLOAD_TOO_LARGE', 'exceeds your TorBox download limit'),
             ('PLAN_RESTRICTED_FEATURE', 'plan does not include'),
             ('ACTIVE_LIMIT', 'too many active TorBox downloads'),
             ('COOLDOWN_LIMIT', 'limiting how fast'),
             ('VENDOR_DISABLED', 'turned this host off'),
             ('NO_SERVERS_AVAILABLE', 'busy or having a problem'),
             ('SOMETHING_NEW', 'could not prepare this file (SOMETHING_NEW)'),
             ('not a code, has spaces!', 'could not prepare this file. Check your account')]

    def run_case(self, code, item_state='completed'):
        with tempfile.TemporaryDirectory() as tmp:
            origin = Origin()
            torbox = TorBoxMock(origin, ['gofile.io', '127.0.0.1'])
            torbox.create_error = (400, code) if code else None
            torbox.item_state = item_state
            service = Service(tmp, origin)
            try:
                service.start({'ORBIT_TEST_TORBOX_URL': torbox.base})
                service.enable('gofile')
                status, _ = service.call('POST', '/api/v1/debrid', {'action': 'connect', 'apiKey': 'k' * 24})
                self.assertEqual(status, 202)
                for _ in range(60):
                    state = service.call('GET', '/api/v1/debrid')[1]
                    if state['connected'] and not state['busy']:
                        break
                    time.sleep(0.2)
                reply = service.resolve('https://gofile.io/d/Rejected')
                self.assertEqual(reply['state'], 'ready', reply)
                status, body = service.queue(reply['releaseId'], 'torbox')
                self.assertEqual(status, 201, body)
                job = service.wait_job(body['id'], {'error', 'complete'}, 60)
                created = [c for c in torbox.calls if c[1].startswith('/webdl/createwebdownload')]
                return job, len(created)
            finally:
                service.stop()
                torbox.shutdown()
                origin.shutdown()

    def test_an_accepted_link_that_then_fails_is_reported(self):
        job, attempts = self.run_case(None, item_state='failed')
        self.assertEqual(job['status'], 'error', job)
        self.assertIn('could not prepare this file (failed)', job['error'])
        self.assertEqual(attempts, 1)

    def test_each_rejection_is_explained_and_nothing_is_relayed(self):
        for code, expected in self.CASES:
            with self.subTest(code=code):
                job, attempts = self.run_case(code)
                self.assertEqual(job['status'], 'error', job)
                self.assertIn(expected, job['error'])
                for leaked in ('secret.example', 'sk-live', 'abc123', 'see https'):
                    self.assertNotIn(leaked, job['error'])
                self.assertEqual(attempts, 1, 'a rejected link is not hammered')


class TorBoxNameClash(TorBoxBase):
    sources = ('gofile',)

    def test_a_name_that_already_exists_is_never_overwritten(self):
        self.connect()
        folder = self.service.storage / 'homebrew'
        folder.mkdir(exist_ok=True)
        existing = folder / TorBoxHandler.NAME
        existing.write_bytes(b'keep me')
        reply = self.service.resolve('https://gofile.io/d/ClashX')
        status, body = self.service.queue(reply['releaseId'], 'torbox')
        self.assertEqual(status, 201, body)
        job = self.service.wait_job(body['id'], {'complete', 'error'}, 120)
        self.assertEqual(job['status'], 'error', job)
        self.assertIn('already uses TorBox', job['error'])
        self.assertEqual(existing.read_bytes(), b'keep me')
        self.assertEqual([p.name for p in folder.glob('*.part')], [])


class FileDitchStatus(Base):
    """FileDitch cannot be downloaded by a script, but its open status endpoint can say whether a link is alive."""
    sources = ()

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.origin = Origin()
        cls.service = Service(cls.tmp.name, cls.origin)
        cls.service.start({'ORBIT_TEST_FILEDITCH_API': cls.origin.base + '/api'})

    def test_an_existing_file_is_confirmed_but_not_downloadable(self):
        reply = self.service.resolve('https://new.fileditch.com/alpha1/abc123/file.bin')
        self.assertEqual((reply['state'], reply['exists'], reply['sizeBytes']), ('unsupported', True, 52428800), reply)
        self.assertIn('confirms this file exists (50.0 MB)', reply['message'])
        self.assertIn('Cloudflare', reply['message'])
        self.assertNotIn('releaseId', reply)

    def test_a_removed_file_is_reported_as_gone(self):
        reply = self.service.resolve('https://itsfileditchfiles.st/alpha1/gone00/file.bin')
        self.assertEqual((reply['state'], reply['exists']), ('unsupported', False), reply)
        self.assertIn('no longer exists', reply['message'])

    def test_an_unreachable_origin_is_not_a_verdict(self):
        reply = self.service.resolve('https://new.fileditch.com/alpha1/unreachable/file.bin')
        self.assertNotIn('exists', reply)
        self.assertIn('Cloudflare', reply['message'])

    def test_malformed_paths_never_reach_the_network(self):
        before = len(self.origin.log)
        for url in ('https://new.fileditch.com/only-one/segment.bin', 'https://new.fileditch.com/a/../b/c.bin'):
            reply = self.service.resolve(url)
            self.assertEqual(reply['state'], 'unsupported')
            self.assertNotIn('exists', reply)
        self.assertEqual(len(self.origin.log), before)


class LearnedCapture(Base):
    """A browser-assisted link whose name and size the provider's own response supplies."""
    sources = ('1fichier',)
    capture = '/dl/learned.bin'

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.origin = Origin()
        cls.service = Service(cls.tmp.name, cls.origin)
        cls.service.start({'ORBIT_TEST_CAPTURE_URL': cls.origin.base + cls.capture})
        cls.service.enable(*cls.sources)

    def capture_job(self):
        reply = self.service.resolve('https://1fichier.com/?abcdefghij0123456789')
        self.assertEqual((reply['state'], reply['sizePending']), ('needs-browser', True), reply)
        status, body = self.service.call('POST', '/api/v1/browser', {
            'action': 'start', 'releaseId': reply['releaseId'], 'storageId': self.service.storage_id(), 'returnTarget': 'browser'})
        self.assertEqual(status, 202, body)
        deadline, state = time.time() + 60, {}
        while time.time() < deadline:
            state = self.service.call('GET', '/api/v1/browser')[1]
            if state['state'] in ('queued', 'failed', 'cancelled'):
                break
            time.sleep(0.3)
        return state

    def test_name_and_size_come_from_the_provider_response(self):
        state = self.capture_job()
        self.assertEqual(state['state'], 'queued', state)
        job = self.service.wait_job(state['jobId'], {'complete', 'error'}, 90)
        self.assertEqual(job['status'], 'complete', job)
        self.assertEqual((job['filename'], job['total']), ('learned-name.bin', len(DATA)))
        self.assertEqual(sha256_file(job['path']), hashlib.sha256(DATA).hexdigest())
        self.assertEqual((job['sourceId'], job['origin']), ('1fichier', 'local'))


class LearnedCaptureNeedsAName(LearnedCapture):
    capture = '/dl/nameless.bin'

    def test_name_and_size_come_from_the_provider_response(self):
        pass

    def test_a_provider_that_names_nothing_queues_nothing(self):
        state = self.capture_job()
        self.assertEqual(state['state'], 'failed', state)
        self.assertIn('did not identify', state['message'])
        self.assertEqual(self.service.jobs(), [])


class LearnedCaptureHostileName(LearnedCapture):
    capture = '/dl/evil.bin'

    def test_name_and_size_come_from_the_provider_response(self):
        pass

    def test_a_traversal_name_is_made_safe_not_trusted(self):
        state = self.capture_job()
        self.assertEqual(state['state'], 'queued', state)
        job = self.service.wait_job(state['jobId'], {'complete', 'error'}, 90)
        self.assertEqual((job['status'], job['filename']), ('complete', 'evil-name.bin'), job)
        self.assertEqual(pathlib.Path(job['path']).parent.name, 'homebrew')
        self.assertFalse((self.service.storage.parent / 'evil-name.bin').exists())


class Recovery(Base):
    """Progress, cancellation and recovery against a file big enough to be split into parallel ranges, held at an exact
    point so "part-way through" is the same state on every run. See docs/PROGRESS.md for what the counters mean."""
    sources = ('web',)
    HOLD = 20 * 1024 * 1024
    env = {}
    AHEAD = (8 * 1024 * 1024, BIG_SIZE)  # eight ranges: the last one starts at 7/8 of the file, far ahead of the sum
    STOP_SLACK = 4 * 1024 * 1024  # a clean stop may drop what is still in the socket

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.origin = Origin()
        cls.service = Service(cls.tmp.name, cls.origin)
        cls.service.start(cls.env)
        cls.service.enable(*cls.sources)

    def setUp(self):
        self.origin.big_served, self.origin.big_hold_after, self.origin.big_delay = 0, None, 0.0
        self.names = []

    def tearDown(self):
        self.origin.big_hold_after = None
        for job in self.service.jobs():
            if job['status'] in ('downloading', 'queued', 'retrying', 'paused'):
                self.service.act(job['id'], 'cancel', deletePartial=True)
        self.wait_idle()
        for job in self.service.jobs():
            self.service.act(job['id'], 'delete' if job['status'] == 'cancelled' else 'remove')
        for part in (self.service.storage / 'homebrew').glob('*'):
            part.unlink()

    def wait_idle(self, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not any(j['status'] in ('downloading', 'verifying', 'retrying') for j in self.service.jobs()):
                return
            time.sleep(0.2)

    def folder(self):
        return self.service.storage / 'homebrew'

    def begin(self, name, hold=True):
        self.names.append(name)
        if hold:
            self.origin.big_hold_after = self.HOLD
        reply = self.service.resolve(self.origin.base + '/big.bin', name)
        self.assertEqual(reply['state'], 'ready', reply)
        status, body = self.service.queue(reply['releaseId'])
        self.assertEqual(status, 201, body)
        return body['id']

    def wait_held(self, timeout=40):
        deadline = time.time() + timeout
        last = -1
        while time.time() < deadline:
            served = self.origin.big_served
            if served >= self.HOLD and served == last:
                return served
            last = served
            time.sleep(0.5)
        self.fail(f'the origin never reached its hold point ({self.origin.big_served} bytes served)')

    def part(self, name):
        return self.folder() / (name + '.part')

    def ranges(self, job_id):
        """The durable cursors Orbit keeps for a job (state.json is what a restart would read)."""
        state = json.loads((self.service.state / 'state.json').read_text())
        for entry in state['jobs']:
            if entry.get('id') == job_id:
                return entry.get('rangeReceived')
        return None

    def assert_durable_bytes_are_real(self, name, job_id, received):
        """Everything Orbit counts as received must be in the file, at the right place, with the right content."""
        cursors = self.ranges(job_id)
        self.assertIsNotNone(cursors, 'the job must have durable range cursors')
        self.assertEqual(sum(cursors), received, 'the counter is the sum of the durable cursors')
        count = len(cursors)
        data = self.part(name).read_bytes()
        for index, done in enumerate(cursors):
            base = (BIG_SIZE // count) * index + ((BIG_SIZE % count) * index) // count
            self.assertEqual(data[base:base + done], big_slice(base, base + done), f'range {index} holds wrong bytes')

    def finish(self, job_id, name):
        self.origin.big_hold_after = None
        job = self.service.wait_job(job_id, {'complete', 'error'}, 120)
        self.assertEqual(job['status'], 'complete', job)
        self.assertEqual(sha256_file(job['path']), big_sha256())
        self.assertFalse(self.part(name).exists())
        return job

    # ---- progress ----
    def test_progress_never_counts_a_byte_that_is_not_on_disk_and_resume_keeps_it(self):
        name = 'big-progress.bin'
        job_id = self.begin(name)
        samples = []
        deadline = time.time() + 40
        while time.time() < deadline and self.origin.big_served < self.HOLD:
            samples.append(self.service.job(job_id)['received'])
            time.sleep(0.1)
        self.wait_held()
        self.assertEqual(samples, sorted(samples), 'received must never go backwards while running')
        self.assertEqual(self.service.act(job_id, 'pause')[0], 200)
        job = self.service.wait_job(job_id, {'paused'}, 30)
        received, size = job['received'], self.part(name).stat().st_size
        self.assertGreater(received, 0)
        self.assertLessEqual(received, size, 'the file is never shorter than what is counted')
        self.assertLess(size, BIG_SIZE)
        self.assert_durable_bytes_are_real(name, job_id, received)
        served_before = self.origin.big_served
        self.assertEqual(self.service.act(job_id, 'resume')[0], 200)
        self.finish(job_id, name)
        refetched = self.origin.big_served - served_before
        self.assertLessEqual(refetched, BIG_SIZE - received + 4 * 1024 * 1024,
                             f'resume must continue from the counted bytes ({refetched} fetched, {BIG_SIZE - received} missing)')
        self.assertGreaterEqual(refetched, BIG_SIZE - received)

    def test_the_part_file_can_be_longer_than_the_counter(self):
        """Not a bug: ranges are written into a file that grows to the furthest byte written. This pins the behaviour
        down so a change to it is noticed, and so the documentation stays honest."""
        name = 'big-longer.bin'
        job_id = self.begin(name)
        self.wait_held()
        self.service.act(job_id, 'pause')
        job = self.service.wait_job(job_id, {'paused'}, 30)
        ahead = self.part(name).stat().st_size - job['received']
        self.assertGreater(ahead, self.AHEAD[0], f'in this layout the file should run ahead of the counter (ahead={ahead}, received={job["received"]})')
        self.assertLess(ahead, self.AHEAD[1], f'and by no more than the layout allows (ahead={ahead}, received={job["received"]})')
        self.finish_after_resume(job_id, name)

    def finish_after_resume(self, job_id, name):
        self.service.act(job_id, 'resume')
        self.finish(job_id, name)

    # ---- cancellation ----
    def test_cancel_and_delete_the_partial_leaves_nothing_and_the_name_is_reusable(self):
        name = 'big-cancel-delete.bin'
        job_id = self.begin(name)
        self.wait_held()
        self.assertTrue(self.part(name).exists())
        self.assertEqual(self.service.act(job_id, 'cancel', deletePartial=True)[0], 200)
        self.origin.big_hold_after = None
        job = self.service.wait_job(job_id, {'cancelled'}, 30)
        self.assertEqual(job['received'], 0)
        deadline = time.time() + 15
        while time.time() < deadline and self.part(name).exists():
            time.sleep(0.2)
        self.assertFalse(self.part(name).exists(), 'Delete partial file must remove the .part file')
        self.assertEqual([p.name for p in self.folder().iterdir()], [], 'nothing else may be left in the folder')
        self.service.act(job_id, 'forget')
        again = self.begin(name, hold=False)
        self.finish(again, name)

    def test_cancel_and_keep_the_partial_then_delete_it_later(self):
        name = 'big-cancel-keep.bin'
        job_id = self.begin(name)
        self.wait_held()
        self.assertEqual(self.service.act(job_id, 'cancel', deletePartial=False)[0], 200)
        self.origin.big_hold_after = None
        job = self.service.wait_job(job_id, {'cancelled'}, 30)
        time.sleep(1)  # nothing may touch the file after the job has stopped
        self.assertTrue(self.part(name).exists(), 'Keep partial file must keep the .part file')
        size = self.part(name).stat().st_size
        self.assertGreater(job['received'], 0)
        time.sleep(1)
        self.assertEqual(self.part(name).stat().st_size, size, 'a cancelled job must not keep writing')
        self.assertEqual(self.service.act(job_id, 'remove')[0], 409, 'history must not drop a job that still owns a partial file')
        self.assertEqual(self.service.act(job_id, 'delete')[0], 200)
        self.assertFalse(self.part(name).exists())
        self.assertIsNone(self.service.job(job_id))

    def test_a_kept_partial_can_be_resumed_after_cancelling(self):
        name = 'big-cancel-resume.bin'
        job_id = self.begin(name)
        self.wait_held()
        self.service.act(job_id, 'cancel', deletePartial=False)
        self.origin.big_hold_after = None
        job = self.service.wait_job(job_id, {'cancelled'}, 30)
        received = job['received']
        served_before = self.origin.big_served
        self.assertEqual(self.service.act(job_id, 'resume')[0], 200)
        self.finish(job_id, name)
        self.assertLessEqual(self.origin.big_served - served_before, BIG_SIZE - received + 4 * 1024 * 1024)

    def test_cancelling_a_paused_job_can_delete_its_partial(self):
        name = 'big-pause-cancel.bin'
        job_id = self.begin(name)
        self.wait_held()
        self.service.act(job_id, 'pause')
        self.service.wait_job(job_id, {'paused'}, 30)
        self.assertTrue(self.part(name).exists())
        self.assertEqual(self.service.act(job_id, 'cancel', deletePartial=True)[0], 200)
        self.service.wait_job(job_id, {'cancelled'}, 30)
        self.assertFalse(self.part(name).exists())

    # ---- recovery ----
    def recover(self, name, how):
        job_id = self.begin(name)
        served = self.wait_held()
        time.sleep(3.5)  # progress is checkpointed about every two seconds; a crash loses at most that much
        before = self.part(name).stat().st_size
        if how == 'kill':
            self.service.process.kill()
            self.service.process.wait(15)
        else:
            self.service.stop()
        self.origin.big_hold_after = None
        self.service.start()
        job = self.service.job(job_id)
        self.assertIsNotNone(job, 'an interrupted download must still be listed after a restart')
        self.assertIn(job['status'], ('paused', 'queued', 'retrying', 'downloading'), job)
        self.assertLessEqual(job['received'], self.part(name).stat().st_size)
        self.assertGreater(job['received'], 0, f'the restart should resume from saved progress, not from zero ({how})')
        if how == 'stop':
            # A clean stop flushes and checkpoints what was written: nothing near the hold point may be forgotten.
            self.assertGreaterEqual(job['received'], served - self.STOP_SLACK,
                                    f"a clean stop must save its progress ({job['received']} saved, {served} served)")
        if job['status'] == 'paused':
            self.assert_durable_bytes_are_real(name, job_id, job['received'])
            self.assertEqual(self.service.act(job_id, 'resume')[0], 200)
        return job_id, before

    def test_recovery_after_the_service_is_killed(self):
        name = 'big-killed.bin'
        job_id, _ = self.recover(name, 'kill')
        self.finish(job_id, name)

    def test_recovery_after_a_clean_stop(self):
        name = 'big-stopped.bin'
        job_id, _ = self.recover(name, 'stop')
        self.finish(job_id, name)

    def test_a_partial_file_that_does_not_match_the_saved_cursors_is_refused_not_trusted(self):
        name = 'big-truncated.bin'
        job_id = self.begin(name)
        self.wait_held()
        self.service.act(job_id, 'pause')
        self.service.wait_job(job_id, {'paused'}, 30)
        os.truncate(self.part(name), 1024)  # someone shortened the file behind Orbit's back
        self.origin.big_hold_after = None
        self.assertEqual(self.service.act(job_id, 'resume')[0], 200)
        job = self.service.wait_job(job_id, {'error', 'complete'}, 60)
        self.assertEqual(job['status'], 'error', job)
        self.assertIn('Partial file size is invalid', job['error'])
        self.assertEqual(self.service.act(job_id, 'cancel', deletePartial=True)[0], 200)


class RecoveryUsbWindows(Recovery):
    """The same on the USB path, which keeps one cursor and writes a bounded window ahead of it."""
    env = {'ORBIT_TEST_USB_STORAGE': '1'}
    AHEAD = (-1, 8 * 1024 * 1024)  # one cursor: the file runs at most a little ahead of it
    STOP_SLACK = 12 * 1024 * 1024  # a window (8 MiB) is committed whole, so an unfinished one is not counted


class ManualLink(Base):
    """The fallback for when the PS5 browser cannot be used: the person finishes the provider's steps on their own computer
    and pastes the link from the Download button. It must be held to every check a link read from the browser gets."""
    sources = ('1fichier', 'vikingfile')

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.origin = Origin()
        cls.service = Service(cls.tmp.name, cls.origin)
        # The simulated capture URL is deliberately useless, to prove the pasted link is what gets used.
        cls.service.start({'ORBIT_TEST_CAPTURE_URL': cls.origin.base + '/dl/nameless.bin',
                           'ORBIT_TEST_VIKING_API': cls.origin.base + '/viking/check-file'})
        cls.service.enable(*cls.sources)

    def paste(self, page, path, **extra):
        reply = self.service.resolve(page)
        self.assertEqual(reply['state'], 'needs-browser', reply)
        link = path if '://' in path or ' ' in path else self.origin.base + path
        status, body = self.service.call('POST', '/api/v1/browser', {
            'action': 'start', 'releaseId': reply['releaseId'], 'storageId': self.service.storage_id(), 'link': link, **extra})
        if status != 202:
            return status, body, None
        deadline, state = time.time() + 60, {}
        while time.time() < deadline:
            state = self.service.call('GET', '/api/v1/browser')[1]
            if state['state'] in ('queued', 'failed', 'cancelled'):
                break
            time.sleep(0.2)
        return status, body, state

    def test_a_pasted_link_is_checked_and_queued_with_the_name_the_provider_gives(self):
        status, _, state = self.paste('https://1fichier.com/?abcdefghij0123456789', '/dl/learned.bin')
        self.assertEqual((status, state['state']), (202, 'queued'), state)
        job = self.service.wait_job(state['jobId'], {'complete', 'error'}, 90)
        self.assertEqual((job['status'], job['filename'], job['total']), ('complete', 'learned-name.bin', len(DATA)), job)
        self.assertEqual(sha256_file(job['path']), hashlib.sha256(DATA).hexdigest())
        self.assertEqual((job['sourceId'], job['origin']), ('1fichier', 'local'))

    def test_a_pasted_link_for_a_listed_file_must_match_the_listing(self):
        _, _, state = self.paste('https://vikingfile.com/f/abcdefghij', '/file.bin')
        self.assertEqual(state['state'], 'queued', state)
        job = self.service.wait_job(state['jobId'], {'complete', 'error'}, 90)
        self.assertEqual(job['status'], 'complete', job)
        pathlib.Path(job['path']).unlink()  # the listing always names the same file; free the name for the next attempt
        before = len(self.service.jobs())
        _, _, state = self.paste('https://vikingfile.com/f/abcdefghik', '/short.bin')  # 500,000 bytes, the listing says 1 MiB
        self.assertEqual(state['state'], 'failed', state)
        self.assertEqual(len(self.service.jobs()), before, 'a link that does not fit the listing must queue nothing')

    def test_a_link_that_is_not_a_download_link_is_refused_with_a_reason(self):
        before = len(self.service.jobs())
        for link in ('https://evil.example/file.bin', 'http://example.com/x', 'ftp://127.0.0.1/file.bin', 'not a link'):
            _, _, state = self.paste('https://1fichier.com/?abcdefghij0123456789', link)
            self.assertEqual(state['state'], 'failed', (link, state))
            self.assertIn('not a download link', state['message'], (link, state))
        self.assertEqual(len(self.service.jobs()), before)

    def test_a_dead_or_html_link_queues_nothing(self):
        before = len(self.service.jobs())
        for path in ('/missing', '/gone', '/html'):
            _, _, state = self.paste('https://1fichier.com/?abcdefghij0123456789', path)
            self.assertEqual(state['state'], 'failed', (path, state))
        self.assertEqual(len(self.service.jobs()), before)

    def test_the_pasted_link_is_never_reported_back(self):
        token = 'SECRETTOKEN0123456789'
        status, body, state = self.paste('https://1fichier.com/?abcdefghij0123456789', f'/dl/learned.bin?sig={token}')
        self.assertEqual(status, 202, body)
        for text in (json.dumps(state), json.dumps(self.service.call('GET', '/api/v1/browser')[1]), json.dumps(self.service.jobs()),
                     json.dumps(self.service.call('GET', '/api/v1/system')[1])):
            self.assertNotIn(token, text)
        state_file = (self.service.state / 'state.json').read_text()
        self.assertNotIn(token, state_file)

    def test_bad_requests_are_rejected_before_anything_starts(self):
        reply = self.service.resolve('https://1fichier.com/?abcdefghij0123456789')
        base = {'action': 'start', 'releaseId': reply['releaseId'], 'storageId': self.service.storage_id()}
        for extra in ({'link': 5}, {'link': ''}, {'link': 'x' * 3000}, {'link': self.origin.base + '/file.bin', 'nativeDialog': True,
                      'returnTarget': 'native', 'clientId': 'abc'}):
            status, body = self.service.call('POST', '/api/v1/browser', {**base, **extra})
            self.assertEqual(status, 400, (extra.keys(), body))
        status, body = self.service.call('POST', '/api/v1/browser', {'action': 'refresh', 'jobId': 'x', 'link': self.origin.base + '/file.bin'})
        self.assertEqual(status, 400, body)
        self.assertFalse(self.service.call('GET', '/api/v1/browser')[1]['active'])

    def test_counters_are_reported_without_any_link(self):
        _, _, state = self.paste('https://1fichier.com/?abcdefghij0123456789', '/dl/learned.bin')
        timing = state['timing']
        for key in ('scannedBytes', 'readableBytes', 'readFailures', 'passes', 'rejected', 'candidates', 'browserProcesses'):
            self.assertIn(key, timing)
        self.assertEqual(timing['candidates'], 1)


class VikingPastedLinks(Base):
    sources = ('vikingfile',)

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.origin = Origin()
        cls.service = Service(cls.tmp.name, cls.origin)
        cls.service.start({'ORBIT_TEST_VIKING_API': cls.origin.base + '/viking/check-file',
                           'ORBIT_TEST_CAPTURE_URL': cls.origin.base + '/file.bin'})
        cls.service.enable(*cls.sources)

    def test_listing_gives_name_and_size_then_the_browser_flow_queues_it(self):
        reply = self.service.resolve('https://vikingfile.com/f/abcdefghij')
        self.assertEqual(reply['state'], 'needs-browser', reply)
        self.assertEqual((reply['filename'], reply['sizeBytes'], reply['viaBrowser']), ('viking-sample.bin', len(DATA), True))
        status, body = self.service.call('POST', '/api/v1/browser', {
            'action': 'start', 'releaseId': reply['releaseId'], 'storageId': self.service.storage_id(), 'returnTarget': 'browser'})
        self.assertEqual(status, 202, body)
        deadline = time.time() + 60
        state = {}
        while time.time() < deadline:
            state = self.service.call('GET', '/api/v1/browser')[1]
            if state['state'] in ('queued', 'failed', 'cancelled'):
                break
            time.sleep(0.3)
        self.assertEqual(state['state'], 'queued', state)
        job = self.service.wait_job(state['jobId'], {'complete', 'error'}, 90)
        self.assertEqual(job['status'], 'complete', job)
        self.assertEqual(sha256_file(job['path']), hashlib.sha256(DATA).hexdigest())
        self.assertEqual((job['sourceId'], job['origin']), ('vikingfile', 'local'))

    def test_removed_files_and_bad_links_are_reported(self):
        self.assertEqual(self.service.resolve('https://vikingfile.com/f/gonegonegone')['state'], 'error')
        self.assertEqual(self.service.resolve('https://vikingfile.com/f/short')['state'], 'error')


SANDBOX_BIN = ROOT / 'build' / 'orbit-sandbox-test'


@unittest.skipUnless(SANDBOX_BIN.exists(), 'build/orbit-sandbox-test is not built')
class Sandbox(unittest.TestCase):
    """The first-test build must name itself and keep off the installed Orbit's port (34177)."""

    def run_without_port(self, binary):
        origin = Origin()
        tmp = tempfile.TemporaryDirectory()
        process = subprocess.Popen(
            [str(binary), '--state', tmp.name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=dict(os.environ, ORBIT_TEST_URL=origin.base + '/fixture.bin', ORBIT_TEST_SIZE='1024'))
        try:
            for port in (34178, 34177):
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/system', timeout=1) as r:
                            return port, json.load(r)
                    except OSError:
                        time.sleep(0.1)
            self.fail('service did not answer on 34177 or 34178')
        finally:
            process.terminate()
            process.wait(10)
            origin.shutdown()
            tmp.cleanup()

    def test_sandbox_build_uses_its_own_port_and_says_so(self):
        port, system = self.run_without_port(SANDBOX_BIN)
        self.assertEqual((port, system.get('sandbox'), system['httpPort']), (34178, True, 34178))

    def stop_from_page(self, binary):
        origin = Origin()
        tmp = tempfile.TemporaryDirectory()
        service = Service(tmp.name, origin, binary)
        try:
            service.start()
            status, body = service.call('POST', '/api/v1/updates', {'action': 'stop', 'confirmed': True})
            exited = None
            for _ in range(150):
                exited = service.process.poll()
                if exited is not None:
                    break
                time.sleep(0.1)
            return status, exited
        finally:
            service.stop()
            origin.shutdown()
            tmp.cleanup()

    def test_sandbox_build_can_be_stopped_from_its_own_page(self):
        status, exited = self.stop_from_page(SANDBOX_BIN)
        self.assertEqual((status, exited), (202, 0))

    @unittest.skipIf(os.environ.get('ORBIT_SANDBOX_AUDIT'), 'the audit runs everything through the sandbox binary')
    def test_normal_test_build_still_refuses_stop_without_an_updater(self):
        status, exited = self.stop_from_page(BIN)
        self.assertEqual((status, exited), (409, None))

    @unittest.skipIf(os.environ.get('ORBIT_SANDBOX_AUDIT'), 'the audit runs everything through the sandbox binary')
    def test_normal_build_keeps_the_original_port_and_is_not_a_sandbox(self):
        port, system = self.run_without_port(BIN)
        self.assertEqual((port, system.get('sandbox'), system['httpPort']), (34177, None, 34177))


@unittest.skipUnless(SANDBOX_BIN.exists(), 'build/orbit-sandbox-test is not built')
class HardwareTool(unittest.TestCase):
    """tools/fork/hardware-check.py, the script used on a real console, run against the sandbox build with local file checks."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('hardware_check', ROOT / 'tools' / 'fork' / 'hardware-check.py')
        cls.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.tool)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.origin = Origin()
        cls.service = Service(cls.tmp.name, cls.origin, SANDBOX_BIN)
        cls.service.start()
        cls.service.enable('web')

    @classmethod
    def tearDownClass(cls):
        cls.service.stop()
        cls.origin.shutdown()
        cls.tmp.cleanup()

    def run_tool(self, *scenarios, delay=0.03):
        self.origin.big_served, self.origin.big_hold_after, self.origin.big_delay = 0, None, delay
        argv = [*scenarios, '--ps5', '127.0.0.1', '--port', str(self.service.port), '--token', self.service.token,
                '--drive', self.service.storage_id(), '--url', self.origin.base + '/big.bin', '--sha256', big_sha256(),
                '--at', str(12 << 20), '--local-folder', str(self.service.storage / 'homebrew')]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.tool.main(argv)
        self.assertNotIn(self.service.token, out.getvalue(), 'the pairing token must never be printed')
        return code, out.getvalue()

    def test_progress_scenario_passes(self):
        code, out = self.run_tool('progress')
        self.assertEqual(code, 0, out)
        self.assertIn('file is byte-identical', out)

    def test_cancel_scenarios_pass(self):
        code, out = self.run_tool('cancel-delete', 'cancel-keep')
        self.assertEqual(code, 0, out)
        self.assertEqual(list((self.service.storage / 'homebrew').glob('orbit-fork-hw-*')), [])

    def test_restart_scenario_passes(self):
        original = builtins.input
        builtins.input = lambda *_: self.service.start()  # "send the ELF again"
        try:
            code, out = self.run_tool('restart', delay=0.15)  # slow enough that the stop lands mid-download
        finally:
            builtins.input = original
        self.assertEqual(code, 0, out)
        self.assertIn('it kept its progress', out)


if __name__ == '__main__':
    if not BIN.exists():
        sys.exit('Build first: tools/fork/host-build.sh build/orbit-test')
    unittest.main(verbosity=2)
