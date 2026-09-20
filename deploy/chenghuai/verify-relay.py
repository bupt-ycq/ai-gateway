#!/usr/bin/env python3
"""Verify real New API forwarding against a MOCK upstream, never a real AI model.

Uses a fresh temporary database and random credentials. The existing gateway is
not contacted. The temporary New API process binds all interfaces briefly;
run this development check on a trusted machine. Requires Python 3.11+ and the
official binary installed by run-local.py. All temporary services are stopped.
"""

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request


BINARY = Path(__file__).resolve().parents[2] / '.local/bin/new-api'
SHA256 = '885df6969b6937b9cd649de7461539a41b020e2390ce88c368e8452844e75e68'
MODEL = 'gpt-4o-mini'
PROMPT = 'Return the deterministic mock verification marker.'
ANSWER = 'MOCK ONLY: relay verification passed.'


class MockUpstream(BaseHTTPRequestHandler):
    """Deterministic protocol fixture; does not run any model inference."""

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        valid = (
            self.path == '/v1/chat/completions'
            and self.headers.get('Authorization') == 'Bearer ' + self.server.mock_key
            and body.get('model') == MODEL
            and body.get('messages') == [{'role': 'user', 'content': PROMPT}]
        )
        if not valid:
            self.send_error(400, 'Mock upstream contract mismatch')
            return
        self.server.requests.append(body.get('stream', False))
        self.send_response(200)
        usage = {'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20}
        base = {'id': 'chatcmpl-mock-only', 'created': int(time.time()), 'model': MODEL}
        if body.get('stream'):
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            events = [
                {**base, 'object': 'chat.completion.chunk', 'choices': [
                    {'index': 0, 'delta': {'role': 'assistant', 'content': ANSWER}, 'finish_reason': None}]},
                {**base, 'object': 'chat.completion.chunk', 'choices': [
                    {'index': 0, 'delta': {}, 'finish_reason': 'stop'}]},
                {**base, 'object': 'chat.completion.chunk', 'choices': [], 'usage': usage},
            ]
            for event in events:
                self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
                self.wfile.flush()
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
        else:
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                **base, 'object': 'chat.completion', 'usage': usage,
                'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': ANSWER},
                             'finish_reason': 'stop'}],
            }).encode())


class Gateway:
    def __init__(self, port):
        self.origin = f'http://127.0.0.1:{port}'
        self.admin_token = None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def raw(self, method, path, payload=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.origin + path, data=body, headers=headers, method=method)
        return self.opener.open(request, timeout=20)

    def api(self, method, path, payload=None):
        with self.raw(method, path, payload, self.admin_token) as response:
            result = json.load(response)
        if result.get('success') is not True:
            raise RuntimeError(f'{method} {path}: administrative API rejected request')
        return result.get('data')


def verify(gateway, mock):
    password = secrets.token_urlsafe(24)
    gateway.api('POST', '/api/setup', {
        'username': 'relaycheck', 'password': password, 'confirmPassword': password,
        'SelfUseModeEnabled': False, 'DemoSiteEnabled': False,
    })
    login = gateway.api('POST', '/api/user/login', {'username': 'relaycheck', 'password': password})
    gateway.admin_token = login['access_token']
    gateway.api('POST', '/api/channel/', {'mode': 'single', 'channel': {
        'name': 'MOCK ONLY verification', 'type': 1, 'key': mock.mock_key,
        'base_url': f'http://127.0.0.1:{mock.server_port}',
        'models': MODEL, 'group': 'default', 'status': 1,
    }})
    gateway.api('POST', '/api/token/', {
        'name': 'MOCK ONLY verification', 'unlimited_quota': True,
        'expired_time': -1, 'group': 'default',
    })
    token_id = gateway.api('GET', '/api/token/')['items'][0]['id']
    key = gateway.api('POST', f'/api/token/{token_id}/key')['key']
    payload = {'model': MODEL, 'messages': [{'role': 'user', 'content': PROMPT}], 'max_tokens': 32}

    for invalid_key in (None, 'sk-invalid-mock-only'):
        try:
            with gateway.raw('POST', '/v1/chat/completions', payload, invalid_key):
                raise RuntimeError('Unauthenticated relay unexpectedly succeeded')
        except urllib.error.HTTPError as error:
            if error.code != 401:
                raise RuntimeError(f'Expected unauthenticated HTTP 401, got {error.code}') from error
    if mock.requests:
        raise RuntimeError('Unauthenticated requests reached the upstream')
    print('PASS: fresh admin setup, login, channel/token creation, unauthorized request rejection')

    with gateway.raw('POST', '/v1/chat/completions', payload, key) as response:
        result = json.load(response)
    if result['choices'][0]['message']['content'] != ANSWER or result['usage']['total_tokens'] != 20:
        raise RuntimeError('Ordinary relay content/usage mismatch')
    print('PASS: ordinary chat forwarding, upstream credentials/model/messages, response and usage')

    stream_payload = {**payload, 'stream': True, 'stream_options': {'include_usage': True}}
    with gateway.raw('POST', '/v1/chat/completions', stream_payload, key) as response:
        if 'text/event-stream' not in response.headers.get('Content-Type', ''):
            raise RuntimeError('Streaming response is not SSE')
        events = [line[6:].strip() for line in response.read().decode().splitlines() if line.startswith('data: ')]
    if not events or events[-1] != '[DONE]':
        raise RuntimeError('SSE completion marker missing')
    parsed = [json.loads(event) for event in events[:-1]]
    content = ''.join(choice.get('delta', {}).get('content', '')
                      for event in parsed for choice in event.get('choices', []))
    if content != ANSWER or not any(event.get('usage', {}).get('total_tokens') == 20 for event in parsed):
        raise RuntimeError('SSE content/usage mismatch')
    if mock.requests != [False, True]:
        raise RuntimeError('Expected exactly one ordinary and one streaming upstream request')
    print('PASS: streaming chat forwarding, SSE content, usage and [DONE]')

    for _ in range(30):
        rows = gateway.api('GET', '/api/log/?type=2')['items']
        if len(rows) >= 2:
            break
        time.sleep(0.1)
    if len(rows) != 2 or any(row['model_name'] != MODEL or row['prompt_tokens'] != 12
                             or row['completion_tokens'] != 8 or row['quota'] <= 0 for row in rows):
        raise RuntimeError('Expected two persisted consume logs with exact token usage and positive quota')
    if {row['is_stream'] for row in rows} != {False, True}:
        raise RuntimeError('Usage logs do not distinguish ordinary and streaming requests')
    print('PASS: both requests persisted in usage logs with exact token counts and positive charges')


def main():
    with BINARY.open('rb') as binary_file:
        if hashlib.file_digest(binary_file, 'sha256').hexdigest() != SHA256:
            raise RuntimeError('Official binary checksum mismatch')
    mock = ThreadingHTTPServer(('127.0.0.1', 0), MockUpstream)
    mock.mock_key = 'sk-mock-' + secrets.token_hex(16)
    mock.requests = []
    thread = threading.Thread(target=mock.serve_forever, daemon=True)
    thread.start()
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix='new-api-mock-relay-') as workdir:
            with socket.socket() as port_probe:
                port_probe.bind(('127.0.0.1', 0))
                port = port_probe.getsockname()[1]
            gateway = Gateway(port)
            # Deliberately do not inherit production database, cache, or proxy settings.
            env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
                   'VERSION': 'v1.0.0-rc.23', 'SESSION_SECRET': secrets.token_hex(32),
                   'SQLITE_PATH': str(Path(workdir) / 'verify.db'),
                   'GIN_MODE': 'release', 'BATCH_UPDATE_ENABLED': 'false'}
            try:
                with open(Path(workdir) / 'server.log', 'wb') as log:
                    process = subprocess.Popen(
                        [str(BINARY), '--port', str(port), '--log-dir', str(Path(workdir) / 'logs')],
                        cwd=workdir, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    )
                for _ in range(150):
                    if process.poll() is not None:
                        raise RuntimeError('Temporary gateway exited during startup')
                    try:
                        gateway.api('GET', '/api/setup')
                        break
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(0.1)
                else:
                    raise RuntimeError('Temporary gateway did not become ready')
                verify(gateway, mock)
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
    finally:
        mock.shutdown()
        mock.server_close()
        thread.join(timeout=5)
    print('PASS: temporary services stopped; existing gateway untouched. MOCK test only, not real AI quality.')


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        print(f'FAIL: HTTP {error.code} during local mock integration check (response omitted).', file=sys.stderr)
        sys.exit(1)
    except (OSError, RuntimeError, KeyError, ValueError) as error:
        print(f'FAIL: {error}', file=sys.stderr)
        sys.exit(1)
