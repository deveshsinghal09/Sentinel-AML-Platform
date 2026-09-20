import { useLocation } from 'react-router-dom'
import { useTheme } from '../hooks/useTheme'
import { resolveWorkspaceRoute } from '../router/manifest'
import type { ApiStatus } from '../types'

const STATUS_LABELS: Record<ApiStatus, string> = {
  checking: 'Checking API',
  online: 'API connected',
  offline: 'API unavailable',
}

interface TopBarProps {
  apiStatus: ApiStatus
  activeDataset: string
  isMenuOpen: boolean
  onMenuToggle: () => void
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  )
}

export default function TopBar({
  apiStatus,
  activeDataset,
  isMenuOpen,
  onMenuToggle,
}: TopBarProps) {
  const location = useLocation()
  const page = resolveWorkspaceRoute(location.pathname)
  const { theme, toggleTheme } = useTheme()

  return (
    <header className="workspace-topbar">
      <div className="topbar-location">
        <button
          type="button"
          className="topbar-menu"
          aria-label={isMenuOpen ? 'Close workspace navigation' : 'Open workspace navigation'}
          aria-controls="primary-workspace-navigation"
          aria-expanded={isMenuOpen}
          onClick={onMenuToggle}
        >
          <span aria-hidden="true" />
          <span aria-hidden="true" />
          <span aria-hidden="true" />
        </button>
        <div>
          <span>{page?.context ?? 'Sentinel AML'}</span>
          <strong>{page?.title ?? 'Page not found'}</strong>
        </div>
      </div>

      <div className="topbar-operations">
        <div className="topbar-evidence" title={activeDataset}>
          <span>Evidence</span>
          <strong>{activeDataset}</strong>
        </div>
        <span
          className={`topbar-api-status topbar-api-status--${apiStatus}`}
          role="status"
          aria-live="polite"
        >
          <span className="status-dot" aria-hidden="true" />
          {STATUS_LABELS[apiStatus]}
        </span>
        <button
          type="button"
          className={`topbar-theme-toggle topbar-theme-toggle--${theme}`}
          aria-label={theme === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
          onClick={toggleTheme}
          title={theme === 'light' ? 'Dark mode' : 'Light mode'}
        >
          {theme === 'light' ? <MoonIcon /> : <SunIcon />}
        </button>
        <div className="topbar-reviewer">
          <span aria-hidden="true">A</span>
          <span>
            <strong>AML Analyst</strong>
            <small>investigator</small>
          </span>
        </div>
      </div>
    </header>
  )
}
