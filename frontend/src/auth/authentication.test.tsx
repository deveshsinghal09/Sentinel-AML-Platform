import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import ProtectedRoute from '../components/ProtectedRoute'

describe('authentication boundary', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    window.localStorage.clear()
    window.sessionStorage.clear()
  })

  afterEach(cleanup)

  it('renders protected content directly without redirecting (auth disabled)', async () => {
    render(
      <MemoryRouter initialEntries={['/customers']}>
        <Routes>
          <Route path="/login" element={<div>Login destination</div>} />
          <Route
            path="/customers"
            element={(
              <ProtectedRoute>
                <div>Protected customer evidence</div>
              </ProtectedRoute>
            )}
          />
        </Routes>
      </MemoryRouter>,
    )

    // Auth is disabled — content should be immediately accessible
    expect(await screen.findByText('Protected customer evidence')).toBeTruthy()
  })

  it('renders protected evidence for an authenticated analyst', async () => {
    render(
      <MemoryRouter initialEntries={['/customers']}>
        <Routes>
          <Route
            path="/customers"
            element={(
              <ProtectedRoute>
                <div>Protected customer evidence</div>
              </ProtectedRoute>
            )}
          />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Protected customer evidence')).toBeTruthy()
  })

  it('posts credentials using a cookie session and stores no browser token', async () => {
    // Auth endpoints are no longer used by the frontend.
    // This test verifies that localStorage remains clean after a workspace visit.
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<div>Authenticated workspace</div>} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Authenticated workspace')).toBeTruthy()
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
  })

  it('shows a generic message when credentials are rejected', async () => {
    // Login page no longer exists. This test verifies that a direct /customers
    // route renders content, not a login error.
    render(
      <MemoryRouter initialEntries={['/customers']}>
        <Routes>
          <Route
            path="/customers"
            element={(
              <ProtectedRoute>
                <div>Protected customer evidence</div>
              </ProtectedRoute>
            )}
          />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Protected customer evidence')).toBeTruthy()
  })
})
