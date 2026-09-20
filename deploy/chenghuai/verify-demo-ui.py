#!/usr/bin/env python3
"""Exercise local simulated recharge through the real browser UI.

Creates four explicitly simulated orders for the local admin. Does not send
payments, call models, or modify real quota. Requires Playwright + Chromium.
"""

import json
from pathlib import Path
import re
import sqlite3
import sys

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
BASE_URL = 'http://127.0.0.1:3080'


def snapshot(username):
    with sqlite3.connect(f'file:{ROOT / ".local/gateway.db"}?mode=ro', uri=True) as db:
        user_id, quota = db.execute(
            'SELECT id, quota FROM users WHERE username = ?', (username,)).fetchone()
        balance = db.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM demo_payment_orders "
            "WHERE user_id = ? AND status = 'success'", (user_id,)).fetchone()[0]
        orders = db.execute(
            'SELECT COUNT(*) FROM demo_payment_orders WHERE user_id = ?',
            (user_id,)).fetchone()[0]
        consent = db.execute(
            "SELECT key,value FROM options WHERE key LIKE 'payment_setting.compliance_%' ORDER BY key"
        ).fetchall()
        return quota, balance, orders, consent


def main():
    credentials = json.loads((ROOT / '.local/credentials.json').read_text())
    output = ROOT / '.local/previews'
    output.mkdir(exist_ok=True)
    before = snapshot(credentials['username'])
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1080}, locale='zh-CN')
            page.goto(BASE_URL + '/sign-in', wait_until='networkidle')
            page.locator('input[name="username"]').fill(credentials['username'])
            page.locator('input[name="password"]').fill(credentials['password'])
            page.get_by_role('button', name='登录', exact=True).click()
            page.wait_for_url(re.compile('/dashboard'), timeout=15000)
            page.goto(BASE_URL + '/wallet', wait_until='networkidle')
            expect(page.get_by_text('模拟充值', exact=True)).to_be_visible()
            form = page.locator('form').filter(has=page.locator('#demo-amount'))
            form.get_by_label('自定义模拟金额').fill('0')
            form.get_by_role('button', name='体验模拟充值').click()
            expect(page.locator('#demo-amount')).to_have_attribute('aria-invalid', 'true')
            assert snapshot(credentials['username'])[2] == before[2]

            for method, amount, outcome in (
                ('支付宝（模拟）', '10', '模拟支付成功入账'),
                ('微信支付（模拟）', '50', '模拟支付成功入账'),
                ('支付宝（模拟）', '10', '取消模拟订单'),
                ('微信支付（模拟）', '10', '模拟支付失败'),
            ):
                form.get_by_label('自定义模拟金额').fill(amount)
                form.get_by_label(method, exact=True).check()
                form.get_by_role('button', name='体验模拟充值').click()
                dialog = page.get_by_role('dialog')
                expect(dialog).to_be_visible()
                expect(dialog).to_contain_text('无真实扣款')
                if method == '微信支付（模拟）' and outcome == '模拟支付成功入账':
                    page.screenshot(path=str(output / 'demo-payment-checkout.png'), animations='disabled')
                    page.set_viewport_size({'width': 390, 'height': 844})
                    expect(dialog.get_by_role('button', name=outcome)).to_be_visible()
                    page.screenshot(path=str(output / 'demo-payment-mobile.png'), animations='disabled')
                    page.set_viewport_size({'width': 1440, 'height': 1080})
                dialog.get_by_role('button', name=outcome).click()
                expect(dialog).not_to_be_visible()
                expect(form.get_by_role('button', name='体验模拟充值')).to_be_enabled()

            page.reload(wait_until='networkidle')
            expect(page.get_by_text('模拟充值', exact=True)).to_be_visible()
            expected_balance = f'¥{(before[1] + 6000) / 100:.2f}'
            expect(page.get_by_role('status').filter(has_text=expected_balance)).to_be_visible()
            page.get_by_text('模拟充值', exact=True).scroll_into_view_if_needed()
            page.screenshot(path=str(output / 'demo-payment-wallet.png'))
            browser.close()
        after = snapshot(credentials['username'])
        assert after[0] == before[0], 'Real quota changed during payment simulation.'
        assert after[1] == before[1] + 6000, 'Demo success balance mismatch.'
        assert after[2] == before[2] + 4, 'Expected exactly four simulated orders.'
        assert after[3] == before[3], 'Real payment consent changed.'
    except Exception as error:
        print(str(error).replace(credentials['password'], '[REDACTED]'), file=sys.stderr)
        return 1
    report = {
        'success': True,
        'checks': ['invalid amount blocked', 'Alipay simulated success',
                   'WeChat simulated success', 'cancel and failure do not credit',
                   'desktop and mobile checkout', 'balance persists after reload',
                   'real quota and payment consent unchanged'],
    }
    (output / 'demo-payment-ui-verification.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    raise SystemExit(main())
