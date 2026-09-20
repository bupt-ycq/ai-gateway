#!/usr/bin/env python3
"""Exercise local mock recharge over HTTP against a source-built New API binary.

Uses Python's standard library, a fresh temporary database and random accounts.
Never contacts the running demo, a merchant, or a model provider. The temporary
upstream application listens on all interfaces; run on a trusted development
machine. All child processes and temporary files are removed on completion.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


BINARY = Path(__file__).resolve().parents[2] / '.local/bin/new-api-demo'
PREFIX = '/api/user/demo-payment'


class Gateway:
    def __init__(self, port, token=None):
        self.origin = f'http://127.0.0.1:{port}'
        self.token = token
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, method, path, payload=None):
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.origin + path, data=body, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read()
            try:
                result = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                result = None
            return response.status, result

    def api(self, method, path, payload=None):
        status, result = self.request(method, path, payload)
        if status != 200 or not isinstance(result, dict) or result.get('success') is not True:
            message = result.get('message', '') if isinstance(result, dict) else 'non-JSON response'
            raise RuntimeError(f'{method} {path}: expected success, received HTTP {status}: {message}')
        return result.get('data')

    def reject(self, method, path, payload=None, expected=(400,)):
        status, result = self.request(method, path, payload)
        if status not in expected or isinstance(result, dict) and result.get('success') is True:
            raise RuntimeError(f'{method} {path}: expected rejection {expected}, received HTTP {status}')


class TemporaryGateway:
    def __init__(self, binary, workdir):
        self.binary = binary
        self.workdir = Path(workdir)
        self.database = self.workdir / 'verification.db'
        self.secret = secrets.token_hex(32)
        self.process = None
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            self.port = probe.getsockname()[1]

    def start(self, enabled):
        # Do not inherit real database, cache, merchant, proxy or service settings.
        env = {
            'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
            'VERSION': 'v1.0.0-rc.23-demo-verification',
            'SQLITE_PATH': str(self.database),
            'SESSION_SECRET': self.secret,
            'PAYMENT_DEMO_ENABLED': 'true' if enabled else 'false',
            'GIN_MODE': 'release',
            'BATCH_UPDATE_ENABLED': 'false',
            'CRITICAL_RATE_LIMIT_ENABLE': 'false',
            'TRUSTED_PROXIES': 'none',
        }
        with (self.workdir / 'server.log').open('ab') as log:
            self.process = subprocess.Popen(
                [str(self.binary), '--port', str(self.port), '--log-dir', str(self.workdir / 'logs')],
                cwd=self.workdir, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            )
        gateway = Gateway(self.port)
        for _ in range(200):
            if self.process.poll() is not None:
                raise RuntimeError('Temporary gateway exited during startup')
            try:
                gateway.api('GET', '/api/setup')
                return gateway
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.1)
        raise RuntimeError('Temporary gateway did not become ready')

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


def real_accounting_snapshot(database):
    """Read real quota and real payment records; never seed or mutate via SQL."""
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
        return {
            'quotas': connection.execute('SELECT id, quota, used_quota FROM users ORDER BY id').fetchall(),
            'consent': connection.execute(
                "SELECT key, value FROM options WHERE key LIKE 'payment_setting.%' ORDER BY key"
            ).fetchall(),
            'real_orders': connection.execute('SELECT * FROM top_ups ORDER BY id').fetchall(),
        }


def verify_enabled(gateway, port, database):
    password = secrets.token_urlsafe(24)
    gateway.api('POST', '/api/setup', {
        'username': 'paymentcheck', 'password': password, 'confirmPassword': password,
        'SelfUseModeEnabled': False, 'DemoSiteEnabled': False,
    })
    gateway.token = gateway.api('POST', '/api/user/login', {
        'username': 'paymentcheck', 'password': password,
    })['access_token']
    guest_password = secrets.token_urlsafe(12)
    gateway.api('POST', '/api/user/', {
        'username': 'paymentguest', 'password': guest_password, 'role': 1,
    })
    guest = Gateway(port)
    guest.token = guest.api('POST', '/api/user/login', {
        'username': 'paymentguest', 'password': guest_password,
    })['access_token']
    before = real_accounting_snapshot(database)
    payment_info = gateway.api('GET', '/api/user/topup/info')
    if payment_info['payment_compliance_confirmed'] is not False:
        raise RuntimeError('Fresh database unexpectedly has real payment consent')
    status = gateway.api('GET', PREFIX + '/status')
    if status != {'enabled': True, 'balance_cents': 0, 'orders': []}:
        raise RuntimeError('Fresh demo payment state is not enabled with an empty ledger')
    anonymous = Gateway(port)
    anonymous.reject('GET', PREFIX + '/status', expected=(401,))
    anonymous.reject('POST', PREFIX + '/orders', {'amount_cents': 100, 'payment_method': 'alipay'}, (401,))
    print('PASS: fresh accounts, enabled demo, zero demo balance and authentication requirement')

    for payload in (
        {}, {'amount_cents': 0, 'payment_method': 'alipay'},
        {'amount_cents': -100, 'payment_method': 'alipay'},
        {'amount_cents': 99, 'payment_method': 'alipay'},
        {'amount_cents': 100001, 'payment_method': 'alipay'},
        {'amount_cents': 2**63, 'payment_method': 'alipay'},
        {'amount_cents': 100.5, 'payment_method': 'alipay'},
        {'amount_cents': '100', 'payment_method': 'alipay'},
        {'amount_cents': 100, 'payment_method': 'card'},
    ):
        gateway.reject('POST', PREFIX + '/orders', payload)
    if gateway.api('GET', PREFIX + '/status') != status:
        raise RuntimeError('Invalid order creation changed demo state')
    print('PASS: invalid amounts, out-of-range values, wrong types and payment methods rejected')

    expected_balance = 0
    orders = []
    for amount, method, outcome in (
        (100, 'alipay', 'success'), (100000, 'wxpay', 'success'),
        (500, 'alipay', 'failed'), (600, 'wxpay', 'cancelled'),
    ):
        order = gateway.api('POST', PREFIX + '/orders', {
            'amount_cents': amount, 'payment_method': method,
        })
        if (order['status'], order['amount_cents'], order['payment_method']) != ('pending', amount, method):
            raise RuntimeError('Created order does not match the submitted amount, method and pending state')
        if gateway.api('GET', PREFIX + '/status')['balance_cents'] != expected_balance:
            raise RuntimeError('Creating an unpaid order changed demo balance')
        path = PREFIX + '/orders/' + order['order_no'] + '/resolve'
        guest.reject('POST', path, {'outcome': 'success'}, (404,))
        anonymous.reject('POST', path, {'outcome': 'success'}, (401,))
        gateway.reject('POST', path, {'outcome': 'paid'})
        resolved = gateway.api('POST', path, {'outcome': outcome})
        if outcome == 'success':
            expected_balance += amount
        if resolved['order']['status'] != outcome or resolved['balance_cents'] != expected_balance:
            raise RuntimeError('Resolution status or credited demo amount is incorrect')
        repeated = gateway.api('POST', path, {'outcome': outcome})
        if repeated != resolved:
            raise RuntimeError('Repeated resolution is not idempotent')
        other_outcome = 'cancelled' if outcome == 'success' else 'success'
        if gateway.api('POST', path, {'outcome': other_outcome}) != resolved:
            raise RuntimeError('A settled order can be changed to a different outcome')
        orders.append(resolved['order'])
    if expected_balance != 100100:
        raise RuntimeError('Unexpected expected balance')
    print('PASS: Alipay/WeChat, minimum/maximum amounts, success/failure/cancel, idempotent resolution')

    created = gateway.api('POST', PREFIX + '/orders', {'amount_cents': 700, 'payment_method': 'alipay'})
    path = PREFIX + '/orders/' + created['order_no'] + '/resolve'
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda _: Gateway(port, gateway.token).api('POST', path, {'outcome': 'success'}), range(2),
        ))
    expected_balance += 700
    if any(result['balance_cents'] != expected_balance for result in results):
        raise RuntimeError('Concurrent resolution did not credit the order exactly once')
    orders.append(results[0]['order'])
    final = gateway.api('GET', PREFIX + '/status')
    if final['balance_cents'] != expected_balance:
        raise RuntimeError('Final demo balance mismatch')
    if {order['order_no']: order for order in final['orders']} != {
        order['order_no']: order for order in orders
    }:
        raise RuntimeError('Order history does not preserve final order states')
    guest_status = guest.api('GET', PREFIX + '/status')
    if guest_status['balance_cents'] != 0 or guest_status['orders']:
        raise RuntimeError('One user can see another user\'s balance or orders')
    guest_order = guest.api('POST', PREFIX + '/orders', {'amount_cents': 300, 'payment_method': 'wxpay'})
    guest_path = PREFIX + '/orders/' + guest_order['order_no'] + '/resolve'
    gateway.reject('POST', guest_path, {'outcome': 'success'}, (404,))
    guest_result = guest.api('POST', guest_path, {'outcome': 'success'})
    if guest_result['balance_cents'] != 300 or guest_result['order']['status'] != 'success':
        raise RuntimeError('An ordinary user cannot complete an independently owned demo recharge')
    if gateway.api('GET', PREFIX + '/status') != final:
        raise RuntimeError('Another user\'s payment changed the administrator\'s demo ledger')
    gateway.reject('POST', PREFIX + '/orders/does-not-exist/resolve', {'outcome': 'success'}, (404,))
    print('PASS: concurrent duplicate resolution credits once; order history and ownership isolation')

    if real_accounting_snapshot(database) != before:
        raise RuntimeError('Mock recharge changed real quota, payment consent or real payment orders')
    if gateway.api('GET', '/api/user/topup/info') != payment_info:
        raise RuntimeError('Mock recharge changed real payment availability or consent')
    print('PASS: real User.Quota, payment consent, real top-up records and payment availability unchanged')
    return gateway.token, final, before


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=BINARY,
                        help='Source-built gateway with mock payment support')
    args = parser.parse_args()
    binary = args.binary.resolve()
    if not binary.is_file():
        raise RuntimeError('Build .local/bin/new-api-demo from source before running this check')
    with tempfile.TemporaryDirectory(prefix='new-api-demo-payment-') as workdir:
        server = TemporaryGateway(binary, workdir)
        try:
            gateway = server.start(enabled=True)
            token, final, real_before = verify_enabled(gateway, server.port, server.database)
            server.stop()
            gateway = server.start(enabled=False)
            gateway.reject('GET', PREFIX + '/status', expected=(404,))
            gateway.token = token
            gateway.reject('GET', PREFIX + '/status', expected=(404,))
            gateway.reject('POST', PREFIX + '/orders', {'amount_cents': 100, 'payment_method': 'alipay'}, (404,))
            order_no = final['orders'][0]['order_no']
            gateway.reject('POST', PREFIX + '/orders/' + order_no + '/resolve', {'outcome': 'success'}, (404,))
            print('PASS: disabled flag returns HTTP 404 for status, create and resolve')
            server.stop()
            gateway = server.start(enabled=True)
            gateway.token = token
            if gateway.api('GET', PREFIX + '/status') != final:
                raise RuntimeError('Demo orders or balance did not survive service restart')
            if real_accounting_snapshot(server.database) != real_before:
                raise RuntimeError('Restart or disabled feature changed real accounting')
            print('PASS: mock ledger persists across restarts and feature disable/re-enable')
        finally:
            server.stop()
    print('PASS: temporary services and database removed; existing demo untouched. No real payment occurred.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, KeyError, ValueError, TypeError) as error:
        print(f'FAIL: {error}', file=sys.stderr)
        sys.exit(1)
