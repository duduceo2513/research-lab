import type { InputHTMLAttributes } from 'react'
import { Search } from 'lucide-react'
import { cn } from '@/lib/utils'

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        'h-8 w-full rounded-sm border border-border bg-white px-2.5 text-[13px] text-ink placeholder:text-ink-faint outline-none hover:border-border-strong focus:border-ink',
        className,
      )}
      {...props}
    />
  )
}

export function SearchInput({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="relative">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
      <input
        className={cn(
          'h-8 w-full rounded-sm border border-border bg-white pl-8 pr-2.5 text-[13px] text-ink placeholder:text-ink-faint outline-none hover:border-border-strong focus:border-ink',
          className,
        )}
        {...props}
      />
    </div>
  )
}
