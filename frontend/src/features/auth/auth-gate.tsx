import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'

import { useAuthConfig, useMe } from '@/services/queries'

function Splash() {
  return <div className="grid h-dvh place-items-center bg-background" aria-busy aria-label="Loading" />
}

/** Renders the app for signed-in users (or always, in local single-user mode). */
export function AuthGate({ children }: { children: ReactNode }) {
  const config = useAuthConfig()
  const authEnabled = config.data?.auth_enabled ?? false
  const me = useMe(authEnabled)
  const location = useLocation()

  // If the backend is unreachable, let the app render its own offline states.
  if (config.isLoading) return <Splash />
  if (!authEnabled) return <>{children}</>
  if (me.isLoading) return <Splash />
  if (!me.data) {
    const next = location.pathname + location.search
    return <Navigate to={`/login${next !== '/' ? `?next=${encodeURIComponent(next)}` : ''}`} replace />
  }
  return <>{children}</>
}
