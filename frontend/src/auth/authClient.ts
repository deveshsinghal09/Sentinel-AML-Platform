import type { AuthSession, LoginCredentials } from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'
const AUTH_TIMEOUT_MS = 15_000

interface ErrorPayload {
  detail?: string
  code?: string
}

export class AuthenticationError extends Error {
  readonly status: number
  readonly code: string | null

  constructor(
    message: string,
    options: { status?: number; code?: string | null; cause?: unknown } = {},
  ) {
    super(message)
    this.name = 'AuthenticationError'
    this.status = options.status ?? 0
    this.code = options.code ?? null
    this.cause = options.cause
  }
}

async function errorPayload(response: Response): Promise<ErrorPayload> {
  try {
    return (await response.json()) as ErrorPayload
  } catch {
    return {}
  }
}

async function authRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const controller = new AbortController()
  const abortRequest = () => controller.abort()
  if (init.signal?.aborted) controller.abort()
  init.signal?.addEventListener('abort', abortRequest, { once: true })
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    AUTH_TIMEOUT_MS,
  )

  try {
    const headers = new Headers(init.headers)
    if (!headers.has('Accept')) headers.set('Accept', 'application/json')
    if (init.body !== undefined && init.body !== null && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json')
    }
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: 'include',
      signal: controller.signal,
      headers,
    })
    if (!response.ok) {
      const payload = await errorPayload(response)
      throw new AuthenticationError(
        payload.detail ?? 'Authentication was not accepted.',
        {
          status: response.status,
          code: payload.code,
        },
      )
    }
    if (response.status === 204) return undefined as T
    return response.json() as Promise<T>
  } catch (reason) {
    if (reason instanceof AuthenticationError) throw reason
    throw new AuthenticationError(
      controller.signal.aborted
        ? 'Authentication service timed out.'
        : 'Authentication service is unavailable.',
      { cause: reason },
    )
  } finally {
    window.clearTimeout(timeoutId)
    init.signal?.removeEventListener('abort', abortRequest)
  }
}

export async function getSession(
  signal?: AbortSignal,
): Promise<AuthSession | null> {
  try {
    return await authRequest<AuthSession>('/auth/session', { signal })
  } catch (reason) {
    if (reason instanceof AuthenticationError && reason.status === 401) {
      return null
    }
    throw reason
  }
}

export function login(credentials: LoginCredentials) {
  return authRequest<AuthSession>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({
      email: credentials.email.trim().toLowerCase(),
      password: credentials.password,
    }),
  })
}

export function logout() {
  return authRequest<void>('/auth/logout', { method: 'POST' })
}
