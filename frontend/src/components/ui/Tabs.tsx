import { cn } from '@/lib/utils'

export function Tabs({
  items,
  active,
  onChange,
  className,
}: {
  items: { key: string; label: string; count?: number }[]
  active: string
  onChange: (key: string) => void
  className?: string
}) {
  return (
    <div className={cn('flex items-center gap-1 border-b border-border', className)}>
      {items.map((item) => {
        const isActive = item.key === active
        return (
          <button
            key={item.key}
            type="button"
            onClick={() => onChange(item.key)}
            className={cn(
              'relative flex items-center gap-1.5 px-3 py-2.5 text-[13px] font-medium transition-colors',
              isActive ? 'text-ink' : 'text-ink-muted hover:text-ink',
            )}
          >
            {item.label}
            {item.count !== undefined ? (
              <span className={cn('text-[11px] tabular-nums', isActive ? 'text-accent' : 'text-ink-faint')}>
                {item.count}
              </span>
            ) : null}
            {isActive ? <span className="absolute inset-x-0 -bottom-px h-0.5 bg-accent" /> : null}
          </button>
        )
      })}
    </div>
  )
}
