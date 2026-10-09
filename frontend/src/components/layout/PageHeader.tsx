import type { ReactNode } from 'react'

export function PageHeader({
  title,
  description,
  action,
}: {
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-border pb-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink">{title}</h1>
        {description ? <p className="mt-1.5 max-w-2xl text-[13px] text-ink-muted">{description}</p> : null}
      </div>
      {action}
    </div>
  )
}
