import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Link, type LinkProps } from 'react-router-dom'
import { cn } from '@/lib/utils'

export type Variant = 'primary' | 'secondary' | 'accent' | 'ghost'
export type Size = 'sm' | 'md'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  icon?: ReactNode
}

const variants: Record<Variant, string> = {
  primary: 'bg-ink text-white hover:bg-ink/90 border border-ink',
  secondary: 'bg-white text-ink border border-border hover:border-border-strong hover:bg-surface',
  accent: 'bg-accent text-white hover:bg-accent-hover border border-accent',
  ghost: 'bg-transparent text-ink-muted hover:text-ink border border-transparent',
}

const sizes: Record<Size, string> = {
  sm: 'h-8 px-3 text-[13px] gap-1.5',
  md: 'h-9 px-4 text-sm gap-2',
}

export function buttonClasses(variant: Variant = 'secondary', size: Size = 'md', className?: string) {
  return cn(
    'inline-flex items-center justify-center rounded-sm font-medium transition-colors disabled:opacity-40 disabled:pointer-events-none whitespace-nowrap',
    variants[variant],
    sizes[size],
    className,
  )
}

export function Button({ variant = 'secondary', size = 'md', icon, className, children, ...props }: ButtonProps) {
  return (
    <button className={buttonClasses(variant, size, className)} {...props}>
      {icon}
      {children}
    </button>
  )
}

interface ButtonLinkProps extends LinkProps {
  variant?: Variant
  size?: Size
  icon?: ReactNode
}

export function ButtonLink({ variant = 'secondary', size = 'md', icon, className, children, ...props }: ButtonLinkProps) {
  return (
    <Link className={buttonClasses(variant, size, className)} {...props}>
      {icon}
      {children}
    </Link>
  )
}
