import { createContext, useContext } from 'react'
import type {
  AuthSession,
  AuthStatus,
  LoginCredentials,
} from './types'

export interface AuthContextValue {
  status: AuthStatus
  session: AuthSession | null
  signIn: (credentials: LoginCredentials) => Promise<AuthSession>
  signOut: () => Promise<void>
  refreshSession: () => Promise<AuthSession | null>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) {
    throw new Error('useAuth must be used inside AuthProvider')
  }
  return value
}
