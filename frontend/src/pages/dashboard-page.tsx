import { ArrowRight, BarChart3, BookOpen, Boxes, Cpu, FileText, Layers, Loader2, MessageSquare, Settings } from 'lucide-react'
import { motion } from 'motion/react'
import { Link } from 'react-router'

import { DocumentStatusBadge, EmptyState, PageHeader } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { UploadDropzone } from '@/features/documents/upload-dropzone'
import { formatBytes, formatNumber, relativeTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useConversations, useDocuments, useHealth } from '@/services/queries'
import type { ModelState } from '@/types/api'

function Stat({ icon: Icon, label, value, hint, loading }: { icon: typeof FileText; label: string; value: string; hint?: string; loading?: boolean }) {
  return (
    <Card className="gap-0 py-4">
      <CardContent className="px-4">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Icon className="size-3.5" aria-hidden />
          {label}
        </div>
        {loading ? <Skeleton className="mt-2 h-7 w-16" /> : <div className="mt-1.5 text-2xl font-semibold tabular-nums tracking-tight">{value}</div>}
        {hint && <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>}
      </CardContent>
    </Card>
  )
}

function ModelRow({ name, state }: { name: string; state?: ModelState }) {
  const status = !state ? 'unknown' : state.error ? 'error' : state.loaded ? 'ready' : 'idle'
  return (
    <div className="flex items-center justify-between gap-3 py-2">
      <div className="min-w-0">
        <div className="text-sm font-medium">{name}</div>
        <div className="truncate text-xs text-muted-foreground" title={state?.model}>{state?.model ?? '—'} · {state?.device ?? '—'}</div>
      </div>
      <span
        className={cn(
          'shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium',
          status === 'ready' && 'bg-success/12 text-success',
          status === 'idle' && 'bg-warning/14 text-warning',
          status === 'error' && 'bg-destructive/12 text-destructive',
          status === 'unknown' && 'bg-muted text-muted-foreground',
        )}
        title={state?.error ?? undefined}
      >
        {status === 'ready' ? 'Loaded' : status === 'idle' ? 'Loads on first use' : status === 'error' ? 'Unavailable' : 'Unknown'}
      </span>
    </div>
  )
}

export default function DashboardPage() {
  const { data: docs, isLoading } = useDocuments()
  const { data: conversations } = useConversations()
  const { data: health, isError: healthError } = useHealth()
  const items = docs?.items ?? []
  const ready = items.filter((d) => d.status === 'ready')
  const processing = items.filter((d) => d.status === 'queued' || d.status === 'processing')
  const failed = items.filter((d) => d.status === 'failed')
  const pages = ready.reduce((a, d) => a + d.page_count, 0)
  const chunks = ready.reduce((a, d) => a + d.chunk_count, 0)
  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'

  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-8 sm:py-8">
        <PageHeader
          title={greeting}
          description="Your private document workspace. Everything runs on this machine."
          actions={
            <Button asChild>
              <Link to="/chat"><MessageSquare className="size-4" /> Ask a question</Link>
            </Button>
          }
        />
        {healthError && (
          <div role="alert" className="mb-5 rounded-lg border border-destructive/40 bg-destructive/8 px-4 py-3 text-sm text-destructive">
            Cannot reach the QueryDoc AI backend. Start it with <code className="font-mono">scripts/dev.sh</code>.
          </div>
        )}
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }} className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat icon={FileText} label="Documents" value={formatNumber(items.length)} hint={`${ready.length} ready${failed.length ? ` · ${failed.length} failed` : ''}`} loading={isLoading} />
          <Stat icon={BookOpen} label="Indexed pages" value={formatNumber(pages)} hint={formatBytes(ready.reduce((a, d) => a + d.size_bytes, 0))} loading={isLoading} />
          <Stat icon={Layers} label="Chunks" value={formatNumber(chunks)} hint={health ? `${formatNumber(health.index_vectors)} vectors in FAISS` : undefined} loading={isLoading} />
          <Stat icon={MessageSquare} label="Conversations" value={formatNumber(conversations?.length ?? 0)} loading={!conversations} />
        </motion.div>

        <div className="mt-6 grid gap-5 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-base">Recent documents</CardTitle>
              <Button asChild variant="ghost" size="sm"><Link to="/library">Library <ArrowRight className="size-3.5" /></Link></Button>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div>
              ) : items.length === 0 ? (
                <UploadDropzone compact />
              ) : (
                <ul className="divide-y">
                  {items.slice(0, 6).map((d) => (
                    <li key={d.id} className="flex items-center gap-3 py-2.5">
                      <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground"><FileText className="size-4" aria-hidden /></div>
                      <div className="min-w-0 flex-1">
                        <Link to={d.status === 'ready' ? `/documents/${d.id}` : '/library'} className="block truncate text-sm font-medium hover:underline" title={d.filename}>{d.filename}</Link>
                        <div className="text-xs text-muted-foreground">
                          {d.page_count ? `${d.page_count} pages · ` : ''}{relativeTime(d.created_at)}
                        </div>
                        {(d.status === 'queued' || d.status === 'processing') && <Progress value={d.progress * 100} className="mt-1.5 h-1" aria-label={`Progress for ${d.filename}`} />}
                      </div>
                      <DocumentStatusBadge status={d.status} />
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">Model readiness</CardTitle></CardHeader>
            <CardContent className="divide-y">
              <ModelRow name="Embeddings" state={health?.models.embedder} />
              <ModelRow name="Reranker" state={health?.models.reranker} />
              <ModelRow name="Language model" state={health?.models.llm} />
              <div className="flex items-center justify-between pt-3 text-xs text-muted-foreground">
                <span className="flex items-center gap-1.5"><Cpu className="size-3.5" aria-hidden /> Ingestion queue</span>
                <span className="flex items-center gap-1.5 tabular-nums">
                  {processing.length > 0 && <Loader2 className="size-3 animate-spin" aria-hidden />}
                  {processing.length} processing
                </span>
              </div>
            </CardContent>
          </Card>

          <Card className="lg:col-span-2">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-base">Recent conversations</CardTitle>
              <Button asChild variant="ghost" size="sm"><Link to="/chat">New chat <ArrowRight className="size-3.5" /></Link></Button>
            </CardHeader>
            <CardContent>
              {!conversations?.length ? (
                <EmptyState icon={MessageSquare} title="No conversations yet" description="Ask a question and it will be saved here." className="py-8" />
              ) : (
                <ul className="divide-y">
                  {conversations.slice(0, 5).map((c) => (
                    <li key={c.id}>
                      <Link to={`/chat/${c.id}`} className="block rounded-md py-2.5 hover:bg-accent/40">
                        <div className="truncate text-sm font-medium">{c.title}</div>
                        <div className="truncate text-xs text-muted-foreground">{c.last_message ?? '—'}</div>
                        <div className="text-[11px] text-muted-foreground">{relativeTime(c.updated_at)} · {c.message_count} messages</div>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">Quick start</CardTitle></CardHeader>
            <CardContent className="grid gap-2">
              {[
                { to: '/library', icon: Boxes, label: 'Upload and manage PDFs' },
                { to: '/chat', icon: MessageSquare, label: 'Ask a question with citations' },
                { to: '/analytics', icon: BarChart3, label: 'Review measured performance' },
                { to: '/settings', icon: Settings, label: 'Tune retrieval and models' },
              ].map((q) => (
                <Link key={q.to} to={q.to} className="flex items-center gap-3 rounded-lg border px-3 py-2.5 text-sm transition-colors hover:border-primary/40 hover:bg-accent">
                  <q.icon className="size-4 text-primary" aria-hidden />
                  <span className="flex-1">{q.label}</span>
                  <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden />
                </Link>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
