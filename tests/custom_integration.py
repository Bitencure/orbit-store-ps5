#!/usr/bin/env python3
"""End-to-end tests for pasted-link downloads (fork).

Runs the ORBIT_TEST service (loopback http only) against local mock origins. No real host
is contacted and no game data is used: every file is a deterministic 1 MiB buffer.
Run through `make test-custom`. This proves the software; it is not PS5 hardware testing."""
import hashlib
import http.server
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
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BIN = ROOT / 'build' / 'orbit-test'
DATA = bytes((i * 7 + i // 251) % 256 for i in range(1 << 20))
ETAG = '"v1-' + hashlib.md5(DATA).hexdigest()[:12] + '"'
MODIFIED = 'Wed, 01 Jan 2025 00:00:00 GMT'
CUT_AT = 300_000


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.route(True)

    def do_HEAD(self):
        self.route(False)

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
    def __init__(self, root, origin):
        self.root = pathlib.Path(root)
        self.state, self.storage = self.root / 'state', self.root / 'storage'
        self.state.mkdir(exist_ok=True)
        self.storage.mkdir(exist_ok=True)
        self.origin, self.port, self.token, self.process = origin, free_port(), None, None

    def start(self, extra_env=None):
        env = dict(os.environ, ORBIT_TEST_URL=self.origin.base + '/fixture.bin', ORBIT_TEST_SIZE='1024')
        env.update(extra_env or {})
        self.process = subprocess.Popen(
            [str(BIN), '--state', str(self.state), '--storage', str(self.storage), '--port', str(self.port)],
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

    def test_recognised_but_unverified_hosts_are_refused_with_a_reason(self):
        for url, provider in [('https://rootz.so/file/abc', 'rootz'), ('https://fuckingfast.co/abc', 'fuckingfast'),
                              ('https://gofile.io/d/abc', 'gofile')]:
            reply = self.service.resolve(url)
            self.assertEqual((reply['state'], reply['provider']), ('unsupported', provider), reply)
            self.assertTrue(reply['message'])


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
        self.assertTrue(job['canRefreshUrl'], job)
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
        self.assertEqual(sorted(rejected), [1, 2, 3, 5, 6])
        self.assertIn('Rootz', rejected[2] + 'Rootz')
        self.assertEqual({l['title'] for l in body['links']}, {'Mine A', 'Fileditch'})
        self.assertTrue(all(l['id'].startswith('link-') for l in body['links']))

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


if __name__ == '__main__':
    if not BIN.exists():
        sys.exit('Build first: make build/orbit-test (tools/fork/host-build.sh build/orbit-test)')
    unittest.main(verbosity=2)
