import { NavLink } from 'react-router-dom'

const NAV_ITEMS = [
  { to: '/', label: 'Command center', icon: 'command' },
  { to: '/investigations', label: 'Investigations', icon: 'search' },
  { to: '/queue', label: 'Review queue', icon: 'queue' },
  { to: '/customers', label: 'Customers', icon: 'customers' },
  { to: '/transactions', label: 'Transactions', icon: 'transactions' },
  { to: '/datasets', label: 'Datasets', icon: 'datasets' },
  { to: '/model', label: 'Model intelligence', icon: 'model' },
  { to: '/audit', label: 'Audit trail', icon: 'audit' },
  { to: '/policy', label: 'Policy settings', icon: 'policy' },
] as const

const ICON_PATHS = {
  command: 'M4 5h16v14H4zM8 9h3v6H8zm5 2h3v4h-3z',
  search: 'm20 20-4.4-4.4m2.4-5.1a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0Z',
  queue: 'M5 5h14v14H5zM8 9h8M8 13h5',
  customers: 'M16 19v-1.5A3.5 3.5 0 0 0 12.5 14h-5A3.5 3.5 0 0 0 4 17.5V19m14-8a3 3 0 1 0 0-6m2 14v-1.5a3.5 3.5 0 0 0-2-3.15M10 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z',
  transactions: 'm7 7 3-3m-3 3 3 3M5 7h14m-2 10-3 3m3-3-3-3m5 3H5',
  datasets: 'M12 4c4.42 0 8 .9 8 2s-3.58 2-8 2-8-.9-8-2 3.58-2 8-2Zm-8 2v6c0 1.1 3.58 2 8 2s8-.9 8-2V6M4 12v6c0 1.1 3.58 2 8 2s8-.9 8-2v-6',
  model: 'm12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Zm0 0v18m8-13.5-8 4.5-8-4.5',
  audit: 'M7 3h10v4H7zM5 5H3v16h18V5h-2M7 12h10M7 16h7',
  policy: 'M12 3 4.5 6v5.5c0 4.5 3.2 7.4 7.5 9.5 4.3-2.1 7.5-5 7.5-9.5V6L12 3Zm-3 9 2 2 4-4',
} as const

interface NavigationIconProps {
  name: keyof typeof ICON_PATHS
}

function NavigationIcon({ name }: NavigationIconProps) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={ICON_PATHS[name]} />
    </svg>
  )
}

interface SidebarProps {
  activeDataset: string
  openAlerts: number | null
  isOpen: boolean
  onClose: () => void
  onNavigate: () => void
}

export default function Sidebar({
  activeDataset,
  openAlerts,
  isOpen,
  onClose,
  onNavigate,
}: SidebarProps) {
  return (
    <aside
      id="primary-workspace-navigation"
      className={`workspace-sidebar${isOpen ? ' workspace-sidebar--open' : ''}`}
      aria-label="Sentinel AML workspace"
    >
      <div className="workspace-sidebar__header">
        <div className="sidebar-brand">
          <span className="sidebar-brand__mark" aria-hidden="true"><i /><i /><i /></span>
          <div><strong>Sentinel AML</strong><span>Investigation workspace</span></div>
        </div>
        <button
          type="button"
          className="sidebar-close"
          aria-label="Close navigation"
          onClick={onClose}
        >
          <span aria-hidden="true">×</span>
        </button>
      </div>

      <div className="sidebar-environment">
        <span className="status-dot status-dot--live" aria-hidden="true" />
        <span><strong>Active evidence</strong>{activeDataset}</span>
      </div>

      <nav aria-label="Primary workspace navigation">
        <span className="sidebar-section-label">Workspace</span>
        {NAV_ITEMS.slice(0, 6).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) => `sidebar-link${isActive ? ' sidebar-link--active' : ''}`}
            title={item.label}
            onClick={onNavigate}
          >
            <span className="sidebar-link__icon"><NavigationIcon name={item.icon} /></span>
            <span>{item.label}</span>
            {item.to === '/queue' ? <span className="sidebar-count">{openAlerts ?? '—'}</span> : null}
          </NavLink>
        ))}

        <span className="sidebar-section-label sidebar-section-label--spaced">Governance</span>
        {NAV_ITEMS.slice(6).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => `sidebar-link${isActive ? ' sidebar-link--active' : ''}`}
            title={item.label}
            onClick={onNavigate}
          >
            <span className="sidebar-link__icon"><NavigationIcon name={item.icon} /></span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-safeguard">
        <span>Human decision required</span>
        <p>Sentinel prioritizes evidence. It does not file regulatory reports.</p>
      </div>
    </aside>
  )
}
