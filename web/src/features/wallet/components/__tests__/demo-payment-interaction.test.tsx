/*
Copyright (C) 2023-2026 QuantumNous

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

For commercial licensing, please contact support@quantumnous.com
*/
import assert from 'node:assert/strict'
import { after, afterEach, beforeEach, describe, test } from 'node:test'

import type { AxiosAdapter } from 'axios'
import { Window } from 'happy-dom'

import type {
  DemoPaymentOrder,
  DemoPaymentOutcome,
  DemoPaymentStatus,
} from '../../lib/demo-payment'

const domWindow = new Window({ url: 'http://localhost/' })
for (const key of [
  'window',
  'document',
  'navigator',
  'HTMLElement',
  'HTMLButtonElement',
  'HTMLInputElement',
  'SVGElement',
  'Node',
  'Element',
  'Event',
  'CustomEvent',
  'MutationObserver',
  'ResizeObserver',
  'requestAnimationFrame',
  'cancelAnimationFrame',
  'getComputedStyle',
  'DocumentFragment',
  'localStorage',
] as const) {
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value: domWindow[key],
  })
}
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const { createInstance } = await import('i18next')
const { I18nextProvider, initReactI18next } = await import('react-i18next')
const { QueryClient, QueryClientProvider, notifyManager } =
  await import('@tanstack/react-query')
const { api } = await import('@/lib/api')
const { toast } = await import('sonner')
const { DemoPaymentCard } = await import('../demo-payment-card')

const i18n = createInstance()
await i18n
  .use(initReactI18next)
  .init({ lng: 'en', resources: { en: { translation: {} } } })
notifyManager.setScheduler(queueMicrotask)
let container: HTMLDivElement
let root: ReturnType<typeof createRoot>
let client: InstanceType<typeof QueryClient>
let status: DemoPaymentStatus
let unavailable: boolean
let requests: Array<{ url: string; body: Record<string, unknown> }>
const originalAdapter = api.defaults.adapter
let releaseCreation: (() => void) | undefined
let deferCreation: boolean
let failCreation: boolean
let statusReads: number

const adapter: AxiosAdapter = async (config) => {
  const url = config.url ?? ''
  if (url.endsWith('/status')) {
    statusReads += 1
    return {
      data: { success: !unavailable, data: structuredClone(status) },
      status: unavailable ? 404 : 200,
      statusText: '',
      headers: {},
      config,
    }
  }
  const body = JSON.parse(config.data as string) as Record<string, unknown>
  requests.push({ url, body })
  if (url.endsWith('/orders')) {
    if (deferCreation) {
      await new Promise<void>((resolve) => {
        releaseCreation = resolve
      })
    }
    if (failCreation) {
      return {
        data: { success: false, message: 'Demo creation failed' },
        status: 200,
        statusText: '',
        headers: {},
        config,
      }
    }
    const order: DemoPaymentOrder = {
      order_no: 'DEMO-TEST-1',
      amount_cents: Number(body.amount_cents),
      payment_method: body.payment_method as DemoPaymentOrder['payment_method'],
      status: 'pending',
      created_at: 1800000000,
      expires_at: 1900000000,
      resolved_at: 0,
    }
    status.orders = [order]
    return {
      data: { success: true, data: structuredClone(order) },
      status: 200,
      statusText: '',
      headers: {},
      config,
    }
  }
  const order = status.orders[0]
  order.status = body.outcome as DemoPaymentOutcome
  order.resolved_at = 1800000001
  if (order.status === 'success') status.balance_cents += order.amount_cents
  return {
    data: {
      success: true,
      data: {
        order: structuredClone(order),
        balance_cents: status.balance_cents,
      },
    },
    status: 200,
    statusText: '',
    headers: {},
    config,
  }
}

function button(name: string): HTMLButtonElement {
  const element = [
    ...document.querySelectorAll<HTMLButtonElement>('button'),
  ].find((item) => item.textContent === name)
  assert.ok(element, `Expected button: ${name}`)
  return element
}

async function renderCard(): Promise<void> {
  await act(async () =>
    root.render(
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={client}>
          <DemoPaymentCard />
        </QueryClientProvider>
      </I18nextProvider>
    )
  )
}

async function click(name: string): Promise<void> {
  await act(async () => button(name).click())
}

describe('simulated wallet checkout', () => {
  beforeEach(() => {
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
    client = new QueryClient({
      defaultOptions: {
        queries: { retry: false, gcTime: Infinity },
        mutations: { retry: false },
      },
    })
    status = { enabled: true, balance_cents: 0, orders: [] }
    unavailable = false
    requests = []
    deferCreation = false
    failCreation = false
    statusReads = 0
    releaseCreation = undefined
    api.defaults.adapter = adapter
  })
  afterEach(async () => {
    releaseCreation?.()
    await act(async () => root.unmount())
    client.clear()
    container.remove()
    api.defaults.adapter = originalAdapter
  })
  after(() => domWindow.close())

  test('disabled endpoint hides the demo card without treating 404 as a failed request', async () => {
    unavailable = true
    const previousToasts = toast.getHistory().length
    await renderCard()
    assert.equal(toast.getHistory().length, previousToasts)
    assert.equal(container.textContent, '')
    assert.equal(
      client.getQueryState(['wallet', 'demo-payment', undefined])?.status,
      'success'
    )
  })

  test('empty ledger shows isolated zero balance and an explicit no-charge notice', async () => {
    await renderCard()
    assert.ok(container.textContent?.includes('No demo orders yet.'))
    assert.ok(container.textContent?.includes('No real charge.'))
    assert.equal(
      container.querySelector('[role="status"]')?.textContent,
      '¥0.00'
    )
    assert.equal(button('¥50').getAttribute('aria-pressed'), 'true')
  })

  test('WeChat success refreshes the demo balance and order history', async () => {
    await renderCard()
    await click('¥100')
    await act(async () => {
      const radio = container.querySelector<HTMLInputElement>(
        'input[value="wxpay"]'
      )
      assert.ok(radio)
      radio.click()
      assert.equal(radio.checked, true)
    })
    await click('Open demo checkout')
    assert.deepEqual(requests[0].body, {
      amount_cents: 10000,
      payment_method: 'wxpay',
    })
    const dialog = document.querySelector('[role="dialog"]')
    assert.ok(dialog?.textContent?.includes('Demo checkout'))
    assert.ok(
      dialog?.textContent?.includes('No scanning or transfer is needed.')
    )
    await click('Simulate payment success')
    assert.equal(
      container.querySelector('[role="status"]')?.textContent,
      '¥100.00'
    )
    assert.ok(container.textContent?.includes('Simulated success'))
    assert.ok(statusReads >= 3)
    assert.ok(
      requests.every((request) =>
        request.url.startsWith('/api/user/demo-payment/')
      )
    )
  })

  for (const [label, outcome, displayed] of [
    ['Simulate payment failure', 'failed', 'Simulated failure'],
    ['Cancel demo order', 'cancelled', 'Cancelled'],
  ] as const) {
    test(`${outcome} Alipay demo order keeps the independent balance unchanged`, async () => {
      await renderCard()
      await click('Open demo checkout')
      assert.equal(requests[0].body.payment_method, 'alipay')
      await click(label)
      assert.equal(requests[1].body.outcome, outcome)
      assert.equal(
        container.querySelector('[role="status"]')?.textContent,
        '¥0.00'
      )
      assert.ok(container.textContent?.includes(displayed))
    })
  }

  test('invalid custom amount is announced and never sent to the API', async () => {
    await renderCard()
    await act(async () => {
      const input = container.querySelector<HTMLInputElement>('#demo-amount')
      assert.ok(input)
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value'
      )?.set
      assert.ok(setter)
      setter.call(input, '1000.01')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await click('Open demo checkout')
    assert.equal(
      container.querySelector('#demo-amount')?.getAttribute('aria-invalid'),
      'true'
    )
    assert.ok(
      container
        .querySelector('[role="alert"]')
        ?.textContent?.includes('¥1–¥1,000')
    )
    assert.equal(requests.length, 0)
  })

  test('an in-flight creation disables checkout and prevents a second order', async () => {
    deferCreation = true
    await renderCard()
    await click('Open demo checkout')
    assert.equal(button('Open demo checkout').disabled, true)
    await click('Open demo checkout')
    assert.equal(requests.length, 1)
    await act(async () => releaseCreation?.())
    assert.ok(document.querySelector('[role="dialog"]'))
  })

  test('a failed creation restores the submit button and permits retry', async () => {
    failCreation = true
    await renderCard()
    await click('Open demo checkout')
    assert.equal(button('Open demo checkout').disabled, false)
    assert.equal(document.querySelector('[role="dialog"]'), null)
    failCreation = false
    await click('Open demo checkout')
    assert.ok(document.querySelector('[role="dialog"]'))
  })
})
