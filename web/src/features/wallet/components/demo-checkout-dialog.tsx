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
import { FlaskConical } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

import {
  formatDemoAmount,
  type DemoPaymentOrder,
  type DemoPaymentOutcome,
} from '../lib/demo-payment'

interface DemoCheckoutDialogProps {
  order: DemoPaymentOrder | null
  processing: boolean
  onClose: () => void
  onResolve: (outcome: DemoPaymentOutcome) => void
}

export function DemoCheckoutDialog(props: DemoCheckoutDialogProps) {
  const { t } = useTranslation()
  return (
    <Dialog
      open={props.order !== null}
      onOpenChange={(open) => {
        if (!open && !props.processing) props.onClose()
      }}
    >
      <DialogContent
        showCloseButton={!props.processing}
        className='max-h-[90dvh] overflow-y-auto sm:max-w-md'
      >
        <DialogHeader>
          <DialogTitle>{t('Demo checkout')}</DialogTitle>
          <DialogDescription>
            {t(
              'No real charge. No merchant account or payment app is connected.'
            )}
          </DialogDescription>
        </DialogHeader>
        {props.order && (
          <>
            <div className='bg-muted/60 flex flex-col items-center gap-3 rounded-xl border p-6 text-center'>
              <FlaskConical
                aria-hidden='true'
                className='text-primary size-10'
              />
              <span className='text-muted-foreground text-sm'>
                {props.order.payment_method === 'alipay'
                  ? t('Alipay (demo)')
                  : t('WeChat Pay (demo)')}
              </span>
              <strong className='text-4xl tracking-tight tabular-nums'>
                {formatDemoAmount(props.order.amount_cents)}
              </strong>
              <p className='text-muted-foreground text-xs'>
                {t(
                  'Choose a simulated outcome below. No scanning or transfer is needed.'
                )}
              </p>
            </div>
            <dl className='grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-xs'>
              <dt className='text-muted-foreground'>{t('Order number')}</dt>
              <dd className='text-right font-mono break-all'>
                {props.order.order_no}
              </dd>
              <dt className='text-muted-foreground'>{t('Expires at')}</dt>
              <dd className='text-right'>
                {new Date(props.order.expires_at * 1000).toLocaleString()}
              </dd>
            </dl>
            <p className='text-muted-foreground text-xs'>
              {t('Demo funds cannot pay for model requests or be withdrawn.')}
            </p>
            <div className='grid gap-2' aria-busy={props.processing}>
              <Button
                type='button'
                disabled={props.processing}
                onClick={() => props.onResolve('success')}
              >
                {t('Simulate payment success')}
              </Button>
              <div className='grid grid-cols-2 gap-2'>
                <Button
                  type='button'
                  variant='outline'
                  disabled={props.processing}
                  onClick={() => props.onResolve('failed')}
                >
                  {t('Simulate payment failure')}
                </Button>
                <Button
                  type='button'
                  variant='outline'
                  disabled={props.processing}
                  onClick={() => props.onResolve('cancelled')}
                >
                  {t('Cancel demo order')}
                </Button>
              </div>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
