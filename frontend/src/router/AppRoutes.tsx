import { lazy, Suspense, type ComponentType, type LazyExoticComponent } from 'react'
import { Route, Routes } from 'react-router-dom'
import NotFound from '../pages/NotFound'
import { WORKSPACE_ROUTES } from './manifest'
import './routes.css'

const ROUTE_COMPONENTS: Record<
  (typeof WORKSPACE_ROUTES)[number]['id'],
  LazyExoticComponent<ComponentType>
> = {
  command: lazy(() => import('../pages/CommandCenter')),
  investigations: lazy(() => import('../pages/Investigations')),
  queue: lazy(() => import('../pages/ReviewQueue')),
  customers: lazy(() => import('../pages/Customers')),
  transactions: lazy(() => import('../pages/Transactions')),
  datasets: lazy(() => import('../pages/Datasets')),
  model: lazy(() => import('../pages/ModelCard')),
  audit: lazy(() => import('../pages/AuditTrail')),
  policy: lazy(() => import('../pages/PolicySettings')),
}

function RouteFallback() {
  return (
    <div className="route-loading" role="status" aria-live="polite">
      <span className="route-loading__mark" aria-hidden="true" />
      <div>
        <strong>Opening workspace</strong>
        <span>Loading only the requested analyst module.</span>
      </div>
    </div>
  )
}

export default function AppRoutes() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        {WORKSPACE_ROUTES.map((route) => {
          const Page = ROUTE_COMPONENTS[route.id]
          return <Route key={route.id} path={route.path} element={<Page />} />
        })}
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  )
}
