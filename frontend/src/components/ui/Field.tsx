import type { ReactNode, TextareaHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[12px] font-medium text-ink">{label}</span>
      {children}
      {hint ? <span className="text-[12px] text-ink-faint">{hint}</span> : null}
    </label>
  )
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        'min-h-20 w-full rounded-sm border border-border bg-white px-2.5 py-2 text-[13px] text-ink placeholder:text-ink-faint outline-none hover:border-border-strong focus:border-ink',
        className,
      )}
      {...props}
    />
  )
}

export function Toggle({
  checked,
  onChange,
  labels = ['ON', 'OFF'],
}: {
  checked: boolean
  onChange: (value: boolean) => void
  labels?: [string, string]
}) {
  return (
    <div className="flex w-fit overflow-hidden rounded-sm border border-border">
      <button
        type="button"
        onClick={() => onChange(true)}
        className={cn('px-2.5 py-1 text-[12px] font-semibold', checked ? 'bg-accent text-white' : 'bg-white text-ink-muted')}
      >
        {labels[0]}
      </button>
      <button
        type="button"
        onClick={() => onChange(false)}
        className={cn('px-2.5 py-1 text-[12px] font-semibold', !checked ? 'bg-ink text-white' : 'bg-white text-ink-muted')}
      >
        {labels[1]}
      </button>
    </div>
  )
}
