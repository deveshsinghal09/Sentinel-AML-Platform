import { type FormEvent, useMemo, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { AuthenticationError } from '../auth/authClient'
import { useAuth } from '../auth/AuthContext'
import '../auth/auth.css'

interface LoginLocationState {
  from?: string
}

function safeDestination(candidate: unknown) {
  return (
    typeof candidate === 'string'
    && candidate.startsWith('/')
    && !candidate.startsWith('//')
    && candidate !== '/login'
  )
    ? candidate
    : '/'
}

export default function Login() {
  const location = useLocation()
  const navigate = useNavigate()
  const { status, session, signIn } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const destination = useMemo(
    () => safeDestination((location.state as LoginLocationState | null)?.from),
    [location.state],
  )

  if (status === 'checking') {
    return (
      <main className="auth-state" aria-busy="true">
        <span className="auth-state__spinner" aria-hidden="true" />
        <div>
          <strong>Checking existing session</strong>
          <span>Restoring governed analyst access.</span>
        </div>
      </main>
    )
  }

  if (session) {
    return <Navigate to={destination} replace />
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (status === 'authenticating') return
    setError('')
    try {
      await signIn({ email, password })
      navigate(destination, { replace: true })
    } catch (reason) {
      setError(
        reason instanceof AuthenticationError && reason.status === 401
          ? 'The credentials were not accepted. Check your details or contact an administrator.'
          : 'Secure sign-in is temporarily unavailable. Please try again.',
      )
    }
  }

  return (
    <main className="login-page">
      <section className="login-context" aria-labelledby="login-context-title">
        <div className="login-brand">
          <span className="sidebar-brand__mark" aria-hidden="true">
            <i /><i /><i />
          </span>
          <div>
            <strong>Sentinel AML</strong>
            <span>Suspicious activity intelligence</span>
          </div>
        </div>
        <div className="login-context__copy">
          <span className="section-kicker">Controlled analyst access</span>
          <h1 id="login-context-title">
            Evidence stays governed.<br />Decisions stay attributable.
          </h1>
          <p>
            Sign in with issued compliance credentials to access investigations,
            review queues, governed datasets, and immutable decision traces.
          </p>
        </div>
        <ul className="login-controls" aria-label="Access safeguards">
          <li><span aria-hidden="true">01</span>Server-managed session</li>
          <li><span aria-hidden="true">02</span>Role-aware workspaces</li>
          <li><span aria-hidden="true">03</span>Auditable reviewer identity</li>
        </ul>
        <p className="login-disclaimer">
          Authorized compliance personnel only. Access attempts may be logged.
        </p>
      </section>

      <section className="login-panel" aria-labelledby="login-title">
        <form className="login-form" onSubmit={handleSubmit}>
          <div className="login-form__heading">
            <span className="section-kicker">AML investigation workspace</span>
            <h2 id="login-title">Sign in to Sentinel</h2>
            <p>Use the identity assigned by your compliance administrator.</p>
          </div>

          <label className="login-field">
            <span>Email address</span>
            <input
              type="email"
              name="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="username"
              inputMode="email"
              placeholder="analyst@institution.com"
              required
              maxLength={254}
              disabled={status === 'authenticating'}
            />
          </label>

          <label className="login-field">
            <span>Password</span>
            <span className="login-password">
              <input
                type={showPassword ? 'text' : 'password'}
                name="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                placeholder="Enter your password"
                required
                minLength={8}
                maxLength={256}
                disabled={status === 'authenticating'}
              />
              <button
                type="button"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                onClick={() => setShowPassword((visible) => !visible)}
              >
                {showPassword ? 'Hide' : 'Show'}
              </button>
            </span>
          </label>

          {error ? (
            <div className="login-error" role="alert">
              <span aria-hidden="true">!</span>
              <p>{error}</p>
            </div>
          ) : null}

          <button
            type="submit"
            className="login-submit"
            disabled={status === 'authenticating' || !email || !password}
          >
            {status === 'authenticating' ? (
              <>
                <span className="login-submit__spinner" aria-hidden="true" />
                Verifying access
              </>
            ) : (
              <>
                Continue securely
                <span aria-hidden="true">→</span>
              </>
            )}
          </button>

          <p className="login-support">
            Access problem? Contact your institution’s AML platform administrator.
          </p>
        </form>
      </section>
    </main>
  )
}
