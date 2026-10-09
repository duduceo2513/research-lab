import type { ReactNode } from 'react'
import { errorMessage } from '@/api/client'

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return <p className="px-5 py-8 text-center text-[13px] text-ink-muted">{label}</p>
}

export function ErrorNotice({ error, className }: { error: unknown; className?: string }) {
  return (
    <p className={`rounded-sm border border-critical/20 bg-critical-soft px-3 py-2 text-[13px] text-critical ${className ?? ''}`}>
      {errorMessage(error)}
    </p>
  )
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-1.5 px-5 py-12 text-center">
      <p className="text-[14px] font-medium text-ink">{title}</p>
      {hint ? <p className="max-w-sm text-[13px] text-ink-muted">{hint}</p> : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  )
}
