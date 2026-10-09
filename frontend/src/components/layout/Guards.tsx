import type { ReactNode } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { EmptyState, Loading } from '@/components/ui/Feedback'
import { useAuth } from '@/auth/context'

export function RequireAuth() {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') return <Loading label="Signing in…" />
  if (status === 'anonymous') return <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />
  return <Outlet />
}

export function StaffOnly({ children }: { children: ReactNode }) {
  const { isStaff } = useAuth()
  if (!isStaff) {
    return <EmptyState title="Teachers and administrators only" hint="Your account does not have access to this section." />
  }
  return <>{children}</>
}
