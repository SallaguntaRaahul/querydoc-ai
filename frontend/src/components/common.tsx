import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  CircleDashed,
  CircleHelp,
  Loader2,
  Monitor,
  Moon,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sun,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useTheme, type ThemePreference } from '@/hooks/use-theme'
import { cn } from '@/lib/utils'
import type { DocumentStatus } from '@/types/api'

export function Logo({ collapsed = false, className }: { collapsed?: boolean; className?: string }) {
  return (
    <div className={cn('flex items-center gap-2.5', className)}>
      <div
        aria-hidden
        className="relative grid size-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-primary to-[oklch(0.55_0.2_300)] text-primary-foreground shadow-sm shadow-primary/30"
      >
        <svg viewBox="0 0 24 24" className="size-4.5" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round">
          <path d="M7 3h7l5 5v9" />
          <path d="M5 7v12a2 2 0 0 0 2 2h8" />
          <circle cx="12.5" cy="13.5" r="3" />
          <path d="m15 16 2.5 2.5" />
        </svg>
      </div>
      {!collapsed && (
        <div className="leading-tight">
          <div className="text-[15px] font-semibold tracking-tight">QueryDoc AI</div>
          <div className="text-[11px] text-muted-foreground">Local document intelligence</div>
        </div>
      )}
    </div>
  )
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-balance">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground text-pretty">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function EmptyState({
  icon: Icon = Search,
  title,
  description,
  action,
  className,
  headingLevel = 2,
}: {
  icon?: LucideIcon
  headingLevel?: 2 | 3
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center rounded-xl border border-dashed px-6 py-14 text-center', className)}>
      <div className="mb-4 grid size-12 place-items-center rounded-full bg-accent text-accent-foreground">
        <Icon className="size-5" aria-hidden />
      </div>
      {headingLevel === 3 ? <h3 className="text-base font-medium">{title}</h3> : <h2 className="text-base font-medium">{title}</h2>}
      {description && <p className="mt-1.5 max-w-sm text-sm text-muted-foreground text-pretty">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

const DOC_STATUS: Record<DocumentStatus, { label: string; icon: LucideIcon; className: string; spin?: boolean }> = {
  queued: { label: 'Queued', icon: CircleDashed, className: 'text-muted-foreground bg-muted' },
  processing: { label: 'Indexing', icon: Loader2, className: 'text-info bg-info/12', spin: true },
  ready: { label: 'Ready', icon: CheckCircle2, className: 'text-success bg-success/12' },
  failed: { label: 'Failed', icon: XCircle, className: 'text-destructive bg-destructive/12' },
}

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  const s = DOC_STATUS[status]
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium', s.className)}>
      <s.icon className={cn('size-3', s.spin && 'animate-spin')} aria-hidden />
      {s.label}
    </span>
  )
}

const ANSWER_STATUS: Record<string, { label: string; icon: LucideIcon; className: string; hint: string }> = {
  verified: { label: 'Verified citations', icon: ShieldCheck, className: 'text-success bg-success/12',
    hint: 'Every sentence cites a retrieved passage that supports it.' },
  partially_verified: { label: 'Partially verified', icon: ShieldAlert, className: 'text-warning bg-warning/14',
    hint: 'Some sentences lack a well-supported citation. Check the evidence.' },
  unverified: { label: 'Could not verify', icon: AlertTriangle, className: 'text-destructive bg-destructive/12',
    hint: 'No valid citation supports this answer.' },
  insufficient_evidence: { label: 'Insufficient evidence', icon: CircleHelp, className: 'text-muted-foreground bg-muted',
    hint: 'The selected documents do not appear to contain the answer.' },
  retrieval_only: { label: 'Retrieval only', icon: Search, className: 'text-info bg-info/12',
    hint: 'The language model is unavailable; showing retrieved passages.' },
  cancelled: { label: 'Stopped', icon: Ban, className: 'text-muted-foreground bg-muted',
    hint: 'Generation was stopped; the partial answer was not verified.' },
  error: { label: 'Error', icon: XCircle, className: 'text-destructive bg-destructive/12', hint: 'The request failed.' },
}

export function AnswerStatusBadge({ status }: { status: string | null }) {
  const s = ANSWER_STATUS[status ?? ''] ?? ANSWER_STATUS.unverified
  return (
    <span title={s.hint} className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium', s.className)}>
      <s.icon className="size-3" aria-hidden />
      {s.label}
    </span>
  )
}

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const { preference, resolved, setPreference } = useTheme()
  const Icon = resolved === 'dark' ? Moon : Sun
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size={compact ? 'icon' : 'sm'} aria-label="Change theme" className={cn(!compact && 'w-full justify-start')}>
          <Icon className="size-4" />
          {!compact && <span className="capitalize">{preference} theme</span>}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-40">
        <DropdownMenuLabel>Theme</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={preference} onValueChange={(v) => setPreference(v as ThemePreference)}>
          <DropdownMenuRadioItem value="dark"><Moon className="size-4" /> Dark</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="light"><Sun className="size-4" /> Light</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system"><Monitor className="size-4" /> System</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="pointer-events-none inline-flex h-5 items-center rounded border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground">
      {children}
    </kbd>
  )
}
