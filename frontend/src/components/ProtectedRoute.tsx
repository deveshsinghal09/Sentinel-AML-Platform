import type { PropsWithChildren } from 'react'

/** Authentication is disabled — all routes are publicly accessible. */
export default function ProtectedRoute({ children }: PropsWithChildren) {
  return children
}
