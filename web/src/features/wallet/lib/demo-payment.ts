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
import { z } from 'zod'

import { api } from '@/lib/api'

export type DemoPaymentMethod = 'alipay' | 'wxpay'
export type DemoPaymentOutcome = 'success' | 'failed' | 'cancelled'
export interface DemoPaymentOrder {
  order_no: string
  amount_cents: number
  payment_method: DemoPaymentMethod
  status: DemoPaymentOutcome | 'pending' | 'expired'
  created_at: number
  expires_at: number
  resolved_at: number
}
export interface DemoPaymentStatus {
  enabled: boolean
  balance_cents: number
  orders: DemoPaymentOrder[]
}
interface DemoResponse<T> {
  success: boolean
  message?: string
  data: T
}

export const demoPaymentSchema = z.object({
  amount: z
    .string()
    .regex(/^\d+(\.\d{1,2})?$/)
    .refine((value) => {
      const amount = Number(value)
      return amount >= 1 && amount <= 1000
    }),
  payment_method: z.enum(['alipay', 'wxpay']),
})
export type DemoPaymentForm = z.infer<typeof demoPaymentSchema>

export async function getDemoPaymentStatus(): Promise<DemoPaymentStatus | null> {
  const response = await api.get<DemoResponse<DemoPaymentStatus>>(
    '/api/user/demo-payment/status',
    {
      skipErrorHandler: true,
      skipBusinessError: true,
      validateStatus: (status) =>
        status === 404 || (status >= 200 && status < 300),
    }
  )
  if (response.status === 404) return null
  if (!response.data.success) throw new Error(response.data.message)
  return response.data.data
}

export async function createDemoPayment(
  values: DemoPaymentForm
): Promise<DemoPaymentOrder> {
  const validated = demoPaymentSchema.parse(values)
  const response = await api.post<DemoResponse<DemoPaymentOrder>>(
    '/api/user/demo-payment/orders',
    {
      amount_cents: Math.round(Number(validated.amount) * 100),
      payment_method: validated.payment_method,
    },
    { skipErrorHandler: true, skipBusinessError: true }
  )
  if (!response.data.success) throw new Error(response.data.message)
  return response.data.data
}

export async function resolveDemoPayment(request: {
  order_no: string
  outcome: DemoPaymentOutcome
}): Promise<{ order: DemoPaymentOrder; balance_cents: number }> {
  const response = await api.post<
    DemoResponse<{ order: DemoPaymentOrder; balance_cents: number }>
  >(
    `/api/user/demo-payment/orders/${encodeURIComponent(request.order_no)}/resolve`,
    { outcome: request.outcome },
    { skipErrorHandler: true, skipBusinessError: true }
  )
  if (!response.data.success) throw new Error(response.data.message)
  return response.data.data
}

export function formatDemoAmount(cents: number): string {
  return `¥${(cents / 100).toFixed(2)}`
}
