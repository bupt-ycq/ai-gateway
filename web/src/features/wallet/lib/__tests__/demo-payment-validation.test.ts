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
import { describe, test } from 'node:test'

import { demoPaymentSchema } from '../demo-payment'

describe('demo recharge validation', () => {
  test('accepts both supported demo methods and exact cent amounts within the limits', () => {
    for (const payment_method of ['alipay', 'wxpay']) {
      for (const amount of ['1', '10.01', '1000.00']) {
        assert.equal(
          demoPaymentSchema.safeParse({ amount, payment_method }).success,
          true
        )
      }
    }
  })
  test('rejects empty, fractional-cent, negative, excessive and nondecimal amounts', () => {
    for (const amount of [
      '',
      '0',
      '0.99',
      '-1',
      '1000.01',
      '1.001',
      '1e2',
      'Infinity',
      'NaN',
    ]) {
      assert.equal(
        demoPaymentSchema.safeParse({ amount, payment_method: 'alipay' })
          .success,
        false,
        amount
      )
    }
  })
  test('rejects a payment method outside the two demo providers', () => {
    assert.equal(
      demoPaymentSchema.safeParse({ amount: '10', payment_method: 'stripe' })
        .success,
      false
    )
  })
})
