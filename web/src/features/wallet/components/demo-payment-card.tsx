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
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FlaskConical, Loader2 } from 'lucide-react'
import { useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { SiAlipay, SiWechat } from 'react-icons/si'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TitledCard } from '@/components/ui/titled-card'
import { handleServerError } from '@/lib/handle-server-error'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth-store'

import {
  createDemoPayment,
  demoPaymentSchema,
  formatDemoAmount,
  getDemoPaymentStatus,
  resolveDemoPayment,
  type DemoPaymentForm,
  type DemoPaymentOrder,
  type DemoPaymentOutcome,
} from '../lib/demo-payment'
import { DemoCheckoutDialog } from './demo-checkout-dialog'

export function DemoPaymentCard() {
  const { t } = useTranslation()
  const userId = useAuthStore((state) => state.auth.user?.id)
  const queryClient = useQueryClient()
  const queryKey = ['wallet', 'demo-payment', userId]
  const status = useQuery({
    queryKey,
    queryFn: getDemoPaymentStatus,
    retry: false,
  })
  const [checkout, setCheckout] = useState<DemoPaymentOrder | null>(null)
  const requestInFlight = useRef(false)
  const form = useForm<DemoPaymentForm>({
    resolver: zodResolver(demoPaymentSchema),
    defaultValues: { amount: '50', payment_method: 'alipay' },
  })
  const amount = form.watch('amount')
  const create = useMutation({
    mutationFn: createDemoPayment,
    onError: handleServerError,
    onSuccess: async (order) => {
      setCheckout(order)
      await queryClient.invalidateQueries({ queryKey })
    },
  })
  const resolve = useMutation({
    mutationFn: resolveDemoPayment,
    onError: handleServerError,
    onSuccess: async () => {
      setCheckout(null)
      toast.success(t('Demo order updated. Your real balance is unchanged.'))
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey })
    },
  })
  const processing =
    create.isPending || resolve.isPending || form.formState.isSubmitting

  async function onSubmit(values: DemoPaymentForm): Promise<void> {
    if (requestInFlight.current) return
    requestInFlight.current = true
    try {
      await create.mutateAsync(values)
    } catch {
      // The mutation error handler displays the API error.
    } finally {
      requestInFlight.current = false
    }
  }

  async function onResolve(outcome: DemoPaymentOutcome): Promise<void> {
    if (!checkout || requestInFlight.current) return
    requestInFlight.current = true
    try {
      await resolve.mutateAsync({ order_no: checkout.order_no, outcome })
    } catch {
      // Refresh order state even if a response was lost or the order expired.
      setCheckout(null)
    } finally {
      requestInFlight.current = false
    }
  }

  if (status.isError) {
    return (
      <div role='alert' className='rounded-xl border p-4 text-sm'>
        {t('Could not load demo payments.')}
        <Button
          type='button'
          variant='ghost'
          disabled={status.isFetching}
          onClick={() => void status.refetch()}
        >
          {t('Retry')}
        </Button>
      </div>
    )
  }
  if (!status.data?.enabled) return null

  return (
    <>
      <TitledCard
        title={t('Simulated recharge')}
        description={t('Try Alipay and WeChat Pay without a merchant account.')}
        icon={<FlaskConical aria-hidden='true' />}
        iconTone='warning'
        action={
          <span className='inline-flex rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-800 dark:text-amber-300'>
            {t('Demo only · No real charge')}
          </span>
        }
        contentClassName='space-y-5'
      >
        <div className='grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]'>
          <form
            noValidate
            onSubmit={form.handleSubmit(onSubmit)}
            className='min-w-0 space-y-4'
            aria-busy={processing}
          >
            <fieldset disabled={processing} className='space-y-4'>
              <legend className='mb-2 text-sm font-medium'>
                {t('Demo amount (CNY)')}
              </legend>
              <div className='grid grid-cols-2 gap-2 sm:grid-cols-4'>
                {[10, 50, 100, 200].map((preset) => (
                  <Button
                    key={preset}
                    type='button'
                    variant={amount === String(preset) ? 'default' : 'outline'}
                    aria-pressed={amount === String(preset)}
                    onClick={() =>
                      form.setValue('amount', String(preset), {
                        shouldValidate: true,
                      })
                    }
                  >
                    ¥{preset}
                  </Button>
                ))}
              </div>
              <div className='space-y-2'>
                <Label htmlFor='demo-amount'>{t('Custom demo amount')}</Label>
                <Input
                  id='demo-amount'
                  inputMode='decimal'
                  {...form.register('amount')}
                  aria-invalid={!!form.formState.errors.amount}
                  aria-describedby='demo-amount-help'
                />
                <p
                  id='demo-amount-help'
                  className={cn(
                    'text-xs',
                    form.formState.errors.amount
                      ? 'text-destructive'
                      : 'text-muted-foreground'
                  )}
                  role={form.formState.errors.amount ? 'alert' : undefined}
                >
                  {t('Enter ¥1–¥1,000, with up to two decimal places.')}
                </p>
              </div>
              <fieldset className='space-y-2'>
                <legend className='text-sm font-medium'>
                  {t('Demo payment method')}
                </legend>
                <div className='grid gap-2 sm:grid-cols-2'>
                  <label className='has-checked:border-primary has-checked:bg-primary/5 flex cursor-pointer items-center gap-2 rounded-lg border p-3 text-sm'>
                    <input
                      type='radio'
                      value='alipay'
                      {...form.register('payment_method')}
                      className='accent-primary'
                    />
                    <SiAlipay
                      aria-hidden='true'
                      className='size-5 text-blue-600 dark:text-blue-400'
                    />
                    {t('Alipay (demo)')}
                  </label>
                  <label className='has-checked:border-primary has-checked:bg-primary/5 flex cursor-pointer items-center gap-2 rounded-lg border p-3 text-sm'>
                    <input
                      type='radio'
                      value='wxpay'
                      {...form.register('payment_method')}
                      className='accent-primary'
                    />
                    <SiWechat
                      aria-hidden='true'
                      className='size-5 text-green-700 dark:text-green-400'
                    />
                    {t('WeChat Pay (demo)')}
                  </label>
                </div>
              </fieldset>
            </fieldset>
            <Button type='submit' className='w-full' disabled={processing}>
              {processing && (
                <Loader2 aria-hidden='true' className='size-4 animate-spin' />
              )}
              {t('Open demo checkout')}
            </Button>
          </form>
          <aside className='bg-muted/50 flex min-w-0 flex-col justify-center gap-3 rounded-xl border p-5'>
            <p className='text-sm font-medium'>
              {t('Independent demo balance')}
            </p>
            <p
              role='status'
              className='text-4xl font-semibold tracking-tight tabular-nums'
            >
              {formatDemoAmount(status.data.balance_cents)}
            </p>
            <p className='text-muted-foreground text-sm'>
              {t('Demo funds cannot pay for model requests or be withdrawn.')}
            </p>
            <p className='text-muted-foreground border-t pt-3 text-xs'>
              {t(
                'No real charge. No merchant account or payment app is connected.'
              )}
            </p>
          </aside>
        </div>
        <section className='border-t pt-4' aria-label={t('Recent demo orders')}>
          <h3 className='mb-3 text-sm font-medium'>
            {t('Recent demo orders')}
          </h3>
          {status.data.orders.length === 0 ? (
            <p className='text-muted-foreground py-3 text-sm'>
              {t('No demo orders yet. Try your first simulated recharge.')}
            </p>
          ) : (
            <ul className='divide-y'>
              {status.data.orders.map((order) => (
                <li
                  key={order.order_no}
                  className='flex flex-wrap items-center justify-between gap-3 py-3 text-sm'
                >
                  <div className='min-w-0 flex-1'>
                    <p className='font-medium'>
                      {order.payment_method === 'alipay'
                        ? t('Alipay (demo)')
                        : t('WeChat Pay (demo)')}{' '}
                      · {formatDemoAmount(order.amount_cents)}
                    </p>
                    <p className='text-muted-foreground mt-1 font-mono text-xs break-all'>
                      {order.order_no}
                    </p>
                    <time
                      className='text-muted-foreground text-xs'
                      dateTime={new Date(order.created_at * 1000).toISOString()}
                    >
                      {new Date(order.created_at * 1000).toLocaleString()}
                    </time>
                  </div>
                  <span
                    className={cn(
                      'rounded-full px-2.5 py-1 text-xs',
                      order.status === 'success'
                        ? 'bg-green-500/10 text-green-800 dark:text-green-300'
                        : 'bg-muted text-muted-foreground'
                    )}
                  >
                    {order.status === 'pending' && t('Awaiting simulation')}
                    {order.status === 'success' && t('Simulated success')}
                    {order.status === 'failed' && t('Simulated failure')}
                    {order.status === 'cancelled' && t('Cancelled')}
                    {order.status === 'expired' && t('Expired')}
                  </span>
                  {order.status === 'pending' && (
                    <Button
                      type='button'
                      variant='outline'
                      size='sm'
                      disabled={processing}
                      onClick={() => setCheckout(order)}
                    >
                      {t('Continue demo')}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </TitledCard>
      <DemoCheckoutDialog
        order={checkout}
        processing={processing}
        onClose={() => setCheckout(null)}
        onResolve={(outcome) => void onResolve(outcome)}
      />
    </>
  )
}
