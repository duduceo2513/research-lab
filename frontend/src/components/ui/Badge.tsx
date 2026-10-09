import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

type Variant = 'neutral' | 'accent' | 'good' | 'warn' | 'critical' | 'ink'

const variants: Record<Variant, string> = {
  neutral: 'bg-surface text-ink-muted border-border',
  accent: 'bg-accent-soft text-accent border-accent/20',
  good: 'bg-good-soft text-good border-good/20',
  warn: 'bg-warn-soft text-warn border-warn/20',
  critical: 'bg-critical-soft text-critical border-critical/20',
  ink: 'bg-ink text-white border-ink',
}

export function Badge({
  children,
  variant = 'neutral',
  className,
}: {
  children: ReactNode
  variant?: Variant
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide',
        variants[variant],
        className,
      )}
    >
      {children}
    </span>
  )
}
