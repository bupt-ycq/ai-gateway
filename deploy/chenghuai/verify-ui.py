#!/usr/bin/env python3
"""Verify the deployed custom pages and admin navigation in Chromium.

Requires Playwright and Chromium. Uses the local instance's credentials file;
does not call any model or edit gateway configuration.
"""

import argparse
import json
from pathlib import Path
import re
import sys

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:3080')
    parser.add_argument('--credentials', type=Path,
                        default=ROOT / '.local/credentials.json')
    parser.add_argument('--output', type=Path,
                        default=ROOT / '.local/previews')
    args = parser.parse_args()
    credentials = json.loads(args.credentials.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={'width': 1440, 'height': 1000}, locale='zh-CN')
            page = context.new_page()
            page.goto(args.base_url, wait_until='networkidle')
            expect(page).to_have_title('骋怀AI模型网关')
            expect(page.locator('.gateway-page h1')).to_contain_text('一钥启万象')
            expect(page.locator('[data-pane="python"]')).to_be_visible()
            page.get_by_text('Node.js', exact=True).click()
            expect(page.locator('[data-pane="nodejs"]')).to_be_visible()
            expect(page.locator('[data-pane="python"]')).to_be_hidden()
            page.locator('#code-nodejs').focus()
            page.keyboard.press('ArrowRight')
            expect(page.locator('[data-pane="curl"]')).to_be_visible()
            expect(page.locator('[data-pane="curl"]')).to_contain_text(
                args.base_url + '/v1/chat/completions')
            page.get_by_text('Python', exact=True).click()
            results.append('Code examples switch by pointer and keyboard after HTML sanitization.')

            images = page.locator('.gateway-page img')
            assert images.evaluate_all(
                '(images) => images.every(image => image.complete && image.naturalWidth > 0)'
            ), 'A homepage image failed to load.'
            assert not page.locator('.gateway-page').inner_text().count('llmgw.chenghuai.xin')
            for width in (1440, 768, 390):
                page.set_viewport_size({'width': width, 'height': 1000})
                page.evaluate('window.scrollTo({top: 0, behavior: "instant"})')
                page.wait_for_function('window.scrollY === 0')
                assert page.evaluate(
                    'document.documentElement.scrollWidth <= document.documentElement.clientWidth'
                ), f'Homepage overflows at {width}px.'
                if width in (1440, 390):
                    label = 'desktop' if width == 1440 else 'mobile'
                    page.screenshot(path=str(args.output / f'home-{label}.png'))
                    page.screenshot(path=str(args.output / f'home-{label}-full.png'), full_page=True)
            results.append('Homepage images load; 1440px, 768px and 390px layouts have no page overflow.')

            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.emulate_media(color_scheme='dark')
            expect(page.locator('html')).to_have_class(re.compile('dark'))
            page.screenshot(path=str(args.output / 'home-desktop-dark.png'))
            page.emulate_media(color_scheme='light')
            expect(page.locator('html')).to_have_class(re.compile('light'))
            results.append('Public page follows the application light/dark theme for navigation contrast.')

            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.goto(args.base_url + '/about', wait_until='networkidle')
            expect(page.locator('.gateway-page')).to_contain_text('安徽方控智能科技有限公司')
            page.screenshot(path=str(args.output / 'about-desktop.png'))
            page.set_viewport_size({'width': 390, 'height': 1000})
            assert page.evaluate(
                'document.documentElement.scrollWidth <= document.documentElement.clientWidth'
            ), 'About page overflows on mobile.'
            results.append('About page renders with local content on desktop and mobile.')

            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.goto(args.base_url, wait_until='networkidle')
            page.get_by_role('link', name='执钥入门', exact=True).click()
            expect(page).to_have_url(re.compile('/sign-in'))
            page.locator('input[name="username"]').fill(credentials['username'])
            page.locator('input[name="password"]').fill(credentials['password'])
            page.get_by_role('button', name='登录', exact=True).click()
            expect(page).to_have_url(re.compile('/dashboard/overview'), timeout=15000)
            expect(page.locator('main').last).to_be_visible()
            page.screenshot(path=str(args.output / 'dashboard-desktop.png'))
            results.append('Homepage CTA reaches sign-in and administrator login reaches real dashboard.')

            for path, label in (('/channels', 'channels'), ('/keys', 'tokens')):
                response = page.goto(args.base_url + path, wait_until='networkidle')
                assert response and response.ok
                assert '/sign-in' not in page.url
                assert '404' not in page.locator('main').last.inner_text(), path
                page.screenshot(path=str(args.output / f'{label}-desktop.png'))
            results.append('Authenticated channels and API-token management pages load.')
            context.close()
            browser.close()
    except Exception as error:
        # Browser assertion snapshots can include password input values.
        message = str(error).replace(credentials['password'], '[REDACTED]')
        print(message, file=sys.stderr)
        return 1
    report = {'success': True, 'checks': results}
    (args.output / 'ui-verification.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    raise SystemExit(main())
