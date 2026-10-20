import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter, Link } from 'react-router'

import { AppShell } from '@/components/app-shell'
import { EmptyState } from '@/components/common'
import { Button } from '@/components/ui/button'
import { AuthGate } from '@/features/auth/auth-gate'
import DashboardPage from '@/pages/dashboard-page'

// Heavy pages (PDF.js, Recharts) are code-split.
const LibraryPage = lazy(() => import('@/pages/library-page'))
const ChatPage = lazy(() => import('@/pages/chat-page'))
const ViewerPage = lazy(() => import('@/pages/viewer-page'))
const AnalyticsPage = lazy(() => import('@/pages/analytics-page'))
const SettingsPage = lazy(() => import('@/pages/settings-page'))
const AuthPage = lazy(() => import('@/pages/auth-page'))

function Page({ children }: { children: ReactNode }) {
  return <Suspense fallback={<div className="h-full animate-pulse bg-muted/20" aria-busy aria-label="Loading page" />}>{children}</Suspense>
}

function NotFound() {
  return (
    <div className="p-8">
      <EmptyState title="Page not found" description="The page you are looking for does not exist." action={<Button asChild><Link to="/">Go to overview</Link></Button>} />
    </div>
  )
}

export const router = createBrowserRouter([
  { path: 'login', element: <Page><AuthPage mode="login" /></Page> },
  { path: 'signup', element: <Page><AuthPage mode="signup" /></Page> },
  {
    element: <AuthGate><AppShell /></AuthGate>,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'library', element: <Page><LibraryPage /></Page> },
      { path: 'chat', element: <Page><ChatPage /></Page> },
      { path: 'chat/:conversationId', element: <Page><ChatPage /></Page> },
      { path: 'documents/:documentId', element: <Page><ViewerPage /></Page> },
      { path: 'analytics', element: <Page><AnalyticsPage /></Page> },
      { path: 'settings', element: <Page><SettingsPage /></Page> },
      { path: '*', element: <NotFound /> },
    ],
  },
])
