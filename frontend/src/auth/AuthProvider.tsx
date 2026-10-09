import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, AUTH_LOST_EVENT, request, tokenStore } from '@/api/client'
import type { TokenPair, User } from '@/api/types'
import { AuthContext, type AuthState } from './context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [user, setUser] = useState<User | null>(null)
  const [status, setStatus] = useState<AuthState['status']>(tokenStore.access ? 'loading' : 'anonymous')

  const loadUser = useCallback(async () => {
    const me = await api.get<User>('accounts/me/')
    setUser(me)
    setStatus('authenticated')
  }, [])

  const drop = useCallback(() => {
    tokenStore.clear()
    queryClient.clear()
    setUser(null)
    setStatus('anonymous')
  }, [queryClient])

  useEffect(() => {
    if (tokenStore.access) {
      loadUser().catch(drop)
    }
  }, [loadUser, drop])

  useEffect(() => {
    window.addEventListener(AUTH_LOST_EVENT, drop)
    return () => window.removeEventListener(AUTH_LOST_EVENT, drop)
  }, [drop])

  const login = useCallback(
    async (email: string, password: string) => {
      const tokens = await request<TokenPair>('accounts/auth/token/', {
        method: 'POST',
        json: { email, password },
        auth: false,
      })
      tokenStore.set(tokens.access, tokens.refresh)
      await loadUser()
    },
    [loadUser],
  )

  const register = useCallback(
    async (input: { email: string; password: string; first_name: string; last_name: string }) => {
      await request('accounts/auth/register/', { method: 'POST', json: input, auth: false })
      await login(input.email, input.password)
    },
    [login],
  )

  const value = useMemo<AuthState>(
    () => ({
      user,
      status,
      isStaff: user?.role === 'ADMIN' || user?.role === 'TEACHER',
      isAdmin: user?.role === 'ADMIN',
      login,
      register,
      logout: drop,
      refreshUser: loadUser,
    }),
    [user, status, login, register, drop, loadUser],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
