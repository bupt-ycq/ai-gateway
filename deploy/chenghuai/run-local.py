#!/usr/bin/env python3
"""Run the checksum-pinned official New API release on Linux amd64."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / '.local'
BINARY = LOCAL / 'bin' / 'new-api'
DEMO_BINARY = LOCAL / 'bin' / 'new-api-demo'
PID_FILE = LOCAL / 'server.pid'
ENV_FILE = LOCAL / 'runtime-env.json'
DATABASE = LOCAL / 'gateway.db'
LOG = LOCAL / 'server.log'
VERSION = 'v1.0.0-rc.23'
SHA256 = '885df6969b6937b9cd649de7461539a41b020e2390ce88c368e8452844e75e68'
RELEASE = f'https://github.com/QuantumNous/new-api/releases/download/{VERSION}'


def private_json(path, value):
    with open(path, 'w', opener=lambda name, flags: os.open(name, flags, 0o600)) as f:
        json.dump(value, f, indent=2)
        f.write('\n')
    path.chmod(0o600)


def process_environment(pid):
    return dict(
        item.decode().split('=', 1)
        for item in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
        if b'=' in item
    )


def is_our_process(pid):
    if pid <= 1:
        return False
    try:
        proc = Path(f'/proc/{pid}')
        return (
            Path(os.readlink(proc / 'exe').removesuffix(' (deleted)'))
            in {BINARY.resolve(), DEMO_BINARY.resolve()}
            and (proc / 'cwd').resolve(strict=True) == LOCAL.resolve()
            and process_environment(pid).get('SQLITE_PATH') == str(DATABASE)
        )
    except (OSError, ValueError, UnicodeError):
        return False


def running_pid():
    try:
        pid = int(PID_FILE.read_text().strip())
        if is_our_process(pid):
            return pid
    except (OSError, ValueError):
        pass
    # Also detect a live instance if the PID file was removed or became stale.
    for proc in Path('/proc').iterdir():
        if proc.name.isdigit() and is_our_process(int(proc.name)):
            return int(proc.name)
    return None


def ensure_binary():
    BINARY.parent.mkdir(parents=True, exist_ok=True)
    if not BINARY.exists():
        checksum_url = f'{RELEASE}/checksums-linux.txt'
        with urllib.request.urlopen(checksum_url, timeout=60) as response:
            checksums = response.read().decode()
        expected = next(
            (line.split()[0] for line in checksums.splitlines()
             if len(line.split()) == 2
             and line.split()[1] == f'new-api-{VERSION}'), None
        )
        if expected != SHA256:
            raise RuntimeError('Official checksum differs from the pinned checksum.')
        (BINARY.parent / 'checksums-linux.txt').write_text(checksums)
        download = BINARY.with_suffix('.download')
        try:
            print(f'Downloading official New API {VERSION}...', flush=True)
            with urllib.request.urlopen(f'{RELEASE}/new-api-{VERSION}', timeout=60) as response:
                with download.open('wb') as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
            with download.open('rb') as binary_file:
                if hashlib.file_digest(binary_file, 'sha256').hexdigest() != SHA256:
                    raise RuntimeError('Downloaded binary checksum mismatch.')
            download.replace(BINARY)
        finally:
            download.unlink(missing_ok=True)
    with BINARY.open('rb') as binary_file:
        actual = hashlib.file_digest(binary_file, 'sha256').hexdigest()
    if actual != SHA256:
        raise RuntimeError(f'Existing binary checksum mismatch: {BINARY}')
    BINARY.chmod(0o755)


def persistent_environment(pid=None):
    if ENV_FILE.exists():
        env = json.loads(ENV_FILE.read_text())
        if not isinstance(env.get('SESSION_SECRET'), str) or len(env['SESSION_SECRET']) < 32:
            raise RuntimeError(f'Invalid SESSION_SECRET in {ENV_FILE}')
        ENV_FILE.chmod(0o600)
        return env
    # Adopt a manually started local instance without changing its sessions.
    current = process_environment(pid) if pid else {}
    env = {'SESSION_SECRET': current.get('SESSION_SECRET') or secrets.token_hex(32)}
    if current.get('CRYPTO_SECRET'):
        env['CRYPTO_SECRET'] = current['CRYPTO_SECRET']
    private_json(ENV_FILE, env)
    return env


def print_running(pid):
    args = Path(f'/proc/{pid}/cmdline').read_bytes().decode().split('\0')
    port = process_environment(pid).get('PORT', '3000')
    for i, arg in enumerate(args):
        if arg in ('--port', '-port') and i + 1 < len(args):
            port = args[i + 1]
        elif arg.startswith(('--port=', '-port=')):
            port = arg.split('=', 1)[1]
    print(f'Running: PID {pid}; http://localhost:{port}')
    if process_environment(pid).get('PAYMENT_DEMO_ENABLED') == 'true':
        print('Payment demo enabled: isolated test balance; no real payment or API credit.')
    print('Network: upstream listens on ALL interfaces; localhost is not an access restriction.')
    print(f'Database: {DATABASE}\nLog: {LOG}')


def start(port, demo_payments=False):
    binary = DEMO_BINARY if demo_payments else BINARY
    if demo_payments:
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise RuntimeError('Build the demo first: deploy/chenghuai/build-local.sh')
    else:
        ensure_binary()
    pid = running_pid()
    if pid:
        current_demo = process_environment(pid).get('PAYMENT_DEMO_ENABLED') == 'true'
        if current_demo != demo_payments:
            raise RuntimeError('Stop the running instance before changing payment demo mode.')
        persistent_environment(pid)
        print_running(pid)
        return
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(('0.0.0.0', port))
    env = os.environ.copy()
    # Prevent inherited deployment variables from selecting an external database.
    for key in ('SQL_DSN', 'LOG_SQL_DSN', 'REDIS_CONN_STRING'):
        env.pop(key, None)
    env.update(persistent_environment())
    env.update(VERSION=VERSION + ('-chenghuai' if demo_payments else ''),
               SQLITE_PATH=str(DATABASE), PORT=str(port))
    env['PAYMENT_DEMO_ENABLED'] = 'true' if demo_payments else 'false'
    (LOCAL / 'logs').mkdir(exist_ok=True)
    with LOG.open('ab') as log:
        process = subprocess.Popen(
            [str(binary), '--port', str(port), '--log-dir', str(LOCAL / 'logs')],
            cwd=LOCAL, env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
    PID_FILE.write_text(str(process.pid) + '\n')
    for _ in range(100):
        if process.poll() is not None:
            PID_FILE.unlink(missing_ok=True)
            raise RuntimeError(f'Service exited during startup. Inspect {LOG}')
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status', timeout=1) as response:
                if response.status == 200:
                    print_running(process.pid)
                    return
        except OSError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f'Service PID {process.pid} started but is not ready; inspect {LOG}')


def stop():
    pid = running_pid()
    if not pid:
        print('Not running; no process was signaled.')
        return
    # A pidfd prevents PID reuse from directing a signal at an unrelated process.
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise RuntimeError('Safe stop requires Python/Linux pidfd support.')
    fd = os.pidfd_open(pid)
    try:
        if not is_our_process(pid):
            raise RuntimeError('Process identity changed; refusing to signal it.')
        persistent_environment(pid)
        signal.pidfd_send_signal(fd, signal.SIGTERM)
        for _ in range(100):
            if not is_our_process(pid):
                PID_FILE.unlink(missing_ok=True)
                print(f'Stopped PID {pid}. Database and session secret retained.')
                return
            time.sleep(0.1)
        raise RuntimeError(f'PID {pid} did not exit within 10 seconds; no forced kill sent.')
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('start', 'stop', 'status'))
    parser.add_argument('--port', type=int, default=3080, help='Port for start (default: 3080).')
    parser.add_argument('--demo-payments', action='store_true',
                        help='Use the source-built binary with isolated payment simulation enabled.')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error('Python 3.11 or newer is required.')
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'amd64'):
        parser.error('This pinned binary supports Linux amd64 only.')
    if not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535.')
    if args.demo_payments and args.command != 'start':
        parser.error('--demo-payments is only valid with start.')
    LOCAL.mkdir(mode=0o700, exist_ok=True)
    LOCAL.chmod(0o700)
    with (LOCAL / 'launcher.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.command == 'start':
            start(args.port, args.demo_payments)
        elif args.command == 'stop':
            stop()
        else:
            pid = running_pid()
            if pid:
                print_running(pid)
            else:
                print('Not running.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
