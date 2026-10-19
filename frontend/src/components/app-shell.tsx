import {
  BarChart3,
  FileText,
  LayoutDashboard,
  Menu,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Settings,
} from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router'

import { Logo, ThemeToggle } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { relativeTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useConversations, useHealth } from '@/services/queries'

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/library', label: 'Library', icon: FileText },
  { to: '/chat', label: 'Chat', icon: MessageSquare },
  { to: '/analytics', label: 'Analytics', icon: BarChart3 },
  { to: '/settings', label: 'Settings', icon: Settings },
]
const COLLAPSE_KEY = 'querydoc.sidebar.collapsed'

function ModelStatus({ collapsed }: { collapsed: boolean }) {
  const { data, isError } = useHealth()
  const llm = data?.models.llm
  const state = isError ? 'offline' : !data ? 'checking' : llm?.error ? 'error' : llm?.loaded ? 'ready' : 'loading'
  const label = { offline: 'Backend offline', checking: 'Checking…', error: 'Model unavailable', ready: 'Model ready', loading: 'Loading model…' }[state]
  const dot = { offline: 'bg-destructive', checking: 'bg-muted-foreground', error: 'bg-destructive', ready: 'bg-success', loading: 'bg-warning animate-pulse' }[state]
  const content = (
    <div className={cn('flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-muted-foreground', collapsed && 'justify-center')}>
      <span className={cn('size-2 shrink-0 rounded-full', dot)} aria-hidden />
      {!collapsed && <span className="truncate">{label}{llm && state === 'ready' ? ` · ${llm.model.split('/').pop()}` : ''}</span>}
    </div>
  )
  return collapsed ? (
    <Tooltip><TooltipTrigger asChild><div role="status" aria-label={label}>{content}</div></TooltipTrigger><TooltipContent side="right">{label}</TooltipContent></Tooltip>
  ) : <div role="status">{content}</div>
}

function SidebarBody({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const navigate = useNavigate()
  const { data: conversations } = useConversations()
  const location = useLocation()

  const item = (to: string, label: string, Icon: typeof FileText, end?: boolean) => {
    const link = (
      <NavLink
        key={to}
        to={to}
        end={end}
        onClick={onNavigate}
        className={({ isActive }) =>
          cn(
            'group flex h-9 items-center gap-3 rounded-md px-2.5 text-sm font-medium text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
            isActive && 'bg-sidebar-accent text-sidebar-accent-foreground',
            collapsed && 'justify-center px-0',
          )
        }
      >
        <Icon className="size-4 shrink-0" aria-hidden />
        {!collapsed && <span>{label}</span>}
        {collapsed && <span className="sr-only">{label}</span>}
      </NavLink>
    )
    return collapsed ? (
      <Tooltip key={to}><TooltipTrigger asChild>{link}</TooltipTrigger><TooltipContent side="right">{label}</TooltipContent></Tooltip>
    ) : link
  }

  return (
    <div className="flex h-full flex-col">
      <div className={cn('flex h-14 items-center px-3', collapsed && 'justify-center px-0')}>
        <Link to="/" onClick={onNavigate} aria-label="QueryDoc AI home"><Logo collapsed={collapsed} /></Link>
      </div>
      <div className={cn('px-3 pb-3', collapsed && 'px-2')}>
        <Button
          className={cn('w-full shadow-sm', collapsed && 'size-9 p-0')}
          onClick={() => { navigate('/chat'); onNavigate?.() }}
          aria-label="New chat"
        >
          <Plus className="size-4" />
          {!collapsed && 'New chat'}
        </Button>
      </div>
      <nav aria-label="Main" className={cn('flex flex-col gap-0.5 px-3', collapsed && 'px-2')}>
        {NAV.map((n) => item(n.to, n.label, n.icon, n.end))}
      </nav>
      {!collapsed && (
        <div className="mt-6 flex min-h-0 flex-1 flex-col">
          <div className="px-5 pb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Recent conversations</div>
          <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-3">
            <ul className="flex flex-col gap-0.5 pb-3">
              {(conversations ?? []).slice(0, 30).map((c) => {
                const active = location.pathname === `/chat/${c.id}`
                return (
                  <li key={c.id}>
                    <Link
                      to={`/chat/${c.id}`}
                      onClick={onNavigate}
                      className={cn(
                        'block rounded-md px-2.5 py-1.5 text-sm text-sidebar-foreground/75 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
                        active && 'bg-sidebar-accent text-sidebar-accent-foreground',
                      )}
                    >
                      <div className="truncate">{c.title}</div>
                      <div className="text-[11px] text-muted-foreground">{relativeTime(c.updated_at)} · {c.message_count} messages</div>
                    </Link>
                  </li>
                )
              })}
              {conversations?.length === 0 && <li className="px-2.5 py-1.5 text-xs text-muted-foreground">No conversations yet.</li>}
            </ul>
          </div>
        </div>
      )}
      {collapsed && <div className="flex-1" />}
      <div className={cn('border-t border-sidebar-border p-3', collapsed && 'flex flex-col items-center gap-1 p-2')}>
        <ModelStatus collapsed={collapsed} />
        <ThemeToggle compact={collapsed} />
        {!collapsed && <p className="px-2 pt-1 text-[11px] text-muted-foreground">Built by Raahul Sallagunta</p>}
      </div>
    </div>
  )
}

export function AppShell({ children }: { children?: ReactNode }) {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === '1'
    } catch {
      return false
    }
  })
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0')
    } catch {
      /* ignore */
    }
  }, [collapsed])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault()
        setCollapsed((c) => !c)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground">
        Skip to content
      </a>
      <aside
        className={cn(
          'relative hidden shrink-0 border-r border-sidebar-border bg-sidebar transition-[width] duration-200 ease-out md:block',
          collapsed ? 'w-[60px]' : 'w-64',
        )}
        aria-label="Sidebar"
      >
        <SidebarBody collapsed={collapsed} />
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setCollapsed((c) => !c)}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!collapsed}
          className="absolute -right-3.5 top-4 z-10 size-7 rounded-full border bg-background shadow-sm hover:bg-accent"
        >
          {collapsed ? <PanelLeftOpen className="size-3.5" /> : <PanelLeftClose className="size-3.5" />}
        </Button>
      </aside>
      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent side="left" className="w-72 bg-sidebar p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SidebarBody collapsed={false} onNavigate={() => setMobileOpen(false)} />
        </SheetContent>
      </Sheet>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-3 md:hidden">
          <Button variant="ghost" size="icon" onClick={() => setMobileOpen(true)} aria-label="Open navigation">
            <Menu className="size-5" />
          </Button>
          <Logo />
        </header>
        <main id="main" className="min-h-0 flex-1 overflow-hidden">
          {children ?? <Outlet />}
        </main>
      </div>
    </div>
  )
}
