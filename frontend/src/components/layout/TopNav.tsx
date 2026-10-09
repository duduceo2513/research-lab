import { NavLink } from 'react-router-dom'
import { LogOut, Settings } from 'lucide-react'
import { useResearchLabConfig } from '@/api/hooks'
import { useAuth } from '@/auth/context'
import { initials } from '@/lib/format'
import { cn } from '@/lib/utils'

const links = [{ to: '/research-lab', label: 'Runs', staff: true, researchLab: true, end: false }]

export function TopNav() {
  const { user, isStaff, logout } = useAuth()
  const researchLabConfig = useResearchLabConfig()
  // Hidden while unknown or disabled — RESEARCH_LAB_ENABLED=false makes the module invisible, not
  // just unusable (see research_lab/README.md).
  const visible = links.filter(
    (link) => (!link.staff || isStaff) && (!link.researchLab || researchLabConfig.data?.enabled),
  )

  return (
    <header className="sticky top-0 z-20 border-b border-border bg-white/95 backdrop-blur">
      <div className="container-page flex h-14 items-center justify-between">
        <div className="flex items-center gap-8">
          <NavLink to="/research-lab" className="flex items-center gap-1.5 text-[15px] font-bold tracking-tight text-ink">
            Research <span className="text-accent">Lab</span>
          </NavLink>
          <nav className="flex items-center gap-0.5">
            {visible.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.end}
                className={({ isActive }) =>
                  cn(
                    'relative px-2.5 py-2 text-[13px] font-medium transition-colors',
                    isActive ? 'text-ink' : 'text-ink-muted hover:text-ink',
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    {link.label}
                    {isActive ? <span className="absolute inset-x-2.5 -bottom-[1px] h-0.5 bg-accent" /> : null}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <NavLink
            to="/settings"
            aria-label="Settings"
            className={({ isActive }) =>
              cn(
                'flex h-8 w-8 items-center justify-center rounded-sm border border-border text-ink-muted transition-colors hover:text-ink',
                isActive && 'border-ink text-ink',
              )
            }
          >
            <Settings className="h-4 w-4" />
          </NavLink>
          <div
            title={user ? `${user.full_name || user.email} · ${user.role}` : undefined}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-ink text-[12px] font-semibold text-white"
          >
            {initials(user?.full_name || user?.email || '?')}
          </div>
          <button
            type="button"
            onClick={logout}
            aria-label="Sign out"
            className="flex h-8 w-8 items-center justify-center rounded-sm border border-border text-ink-muted transition-colors hover:text-accent"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </header>
  )
}
