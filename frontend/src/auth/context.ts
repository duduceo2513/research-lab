import { createContext, useContext } from 'react'
import type { User } from '@/api/types'

export interface AuthState {
  user: User | null
  status: 'loading' | 'authenticated' | 'anonymous'
  isStaff: boolean
  isAdmin: boolean
  login: (email: string, password: string) => Promise<void>
  register: (input: { email: string; password: string; first_name: string; last_name: string }) => Promise<void>
  logout: () => void
  refreshUser: () => Promise<void>
}

export const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>')
  return value
}
