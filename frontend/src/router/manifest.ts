import type { WorkspaceRouteMetadata } from '../types'

export const WORKSPACE_ROUTES = [
  {
    id: 'command',
    path: '/',
    title: 'Command center',
    context: 'Query-aware investigation',
  },
  {
    id: 'investigations',
    path: '/investigations',
    title: 'Investigations',
    context: 'Retained decision evidence',
  },
  {
    id: 'queue',
    path: '/queue',
    title: 'Review queue',
    context: 'Human escalation workflow',
  },
  {
    id: 'customers',
    path: '/customers',
    title: 'Customers',
    context: 'Entity risk intelligence',
  },
  {
    id: 'transactions',
    path: '/transactions',
    title: 'Transactions',
    context: 'Transaction evidence',
  },
  {
    id: 'datasets',
    path: '/datasets',
    title: 'Datasets',
    context: 'Governed data workspace',
  },
  {
    id: 'model',
    path: '/model',
    title: 'Model intelligence',
    context: 'Detection controls',
  },
  {
    id: 'audit',
    path: '/audit',
    title: 'Audit trail',
    context: 'Immutable decision trace',
  },
  {
    id: 'policy',
    path: '/policy',
    title: 'Policy settings',
    context: 'Risk governance',
  },
] as const satisfies readonly WorkspaceRouteMetadata[]

export function resolveWorkspaceRoute(pathname: string) {
  return WORKSPACE_ROUTES.find((route) => route.path === pathname)
}
