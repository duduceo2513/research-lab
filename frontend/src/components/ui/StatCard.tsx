import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function StatCard({
  label,
  value,
  suffix,
  trend,
  accent = false,
  className,
}: {
  label: string
  value: ReactNode
  suffix?: string
  trend?: string
  accent?: boolean
  className?: string
}) {
  return (
    <div className={cn('border border-border bg-white px-5 py-4', className)}>
      <div className="flex items-baseline gap-1">
        <span className={cn('text-3xl font-bold tabular-nums tracking-tight', accent ? 'text-accent' : 'text-ink')}>
          {value}
        </span>
        {suffix ? <span className={cn('text-lg font-bold', accent ? 'text-accent' : 'text-ink')}>{suffix}</span> : null}
      </div>
      <div className="mt-1 flex items-center gap-2">
        <span className="text-[13px] text-ink-muted">{label}</span>
        {trend ? <span className="text-[11px] font-medium text-good">{trend}</span> : null}
      </div>
    </div>
  )
}
