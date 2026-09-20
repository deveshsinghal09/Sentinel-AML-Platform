import {
  type PropsWithChildren,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react'
import {
  getSession,
  login as requestLogin,
  logout as requestLogout,
} from './authClient'
import { AuthContext, type AuthContextValue } from './AuthContext'
import type {
  AuthSession,
  AuthStatus,
  LoginCredentials,
} from './types'

export function AuthProvider({ children }: PropsWithChildren) {
  const [status, setStatus] = useState<AuthStatus>('checking')
  const [session, setSession] = useState<AuthSession | null>(null)

  const refreshSession = useCallback(async () => {
    const nextSession = await getSession()
    setSession(nextSession)
    setStatus(nextSession ? 'authenticated' : 'unauthenticated')
    return nextSession
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let active = true

    getSession(controller.signal)
      .then((nextSession) => {
        if (!active) return
        setSession(nextSession)
        setStatus(nextSession ? 'authenticated' : 'unauthenticated')
      })
      .catch(() => {
        if (!active) return
        setSession(null)
        setStatus('unauthenticated')
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [])

  const signIn = useCallback(async (credentials: LoginCredentials) => {
    setStatus('authenticating')
    try {
      const nextSession = await requestLogin(credentials)
      setSession(nextSession)
      setStatus('authenticated')
      return nextSession
    } catch (reason) {
      setSession(null)
      setStatus('unauthenticated')
      throw reason
    }
  }, [])

  const signOut = useCallback(async () => {
    try {
      await requestLogout()
    } catch {
      // Clear local identity even if the server is temporarily unreachable.
    } finally {
      setSession(null)
      setStatus('unauthenticated')
    }
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      session,
      signIn,
      signOut,
      refreshSession,
    }),
    [refreshSession, session, signIn, signOut, status],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
