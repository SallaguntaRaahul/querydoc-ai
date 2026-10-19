import { ExternalLink, FileText, Layers, X } from 'lucide-react'
import { Link } from 'react-router'

import { EmptyState } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PdfViewer } from '@/features/viewer/pdf-viewer'
import { pagesLabel } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Citation, Source } from '@/types/api'

export interface OpenCitation {
  docId: string
  page: number
  excerpt: string
  chunkId: string
  source: string
}

function ScoreBar({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = Math.max(0, Math.min(1, value / max)) * 100
  return (
    <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
      <span className="w-12 shrink-0">{label}</span>
      <div className="h-1 flex-1 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary/70" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-12 shrink-0 text-right tabular-nums">{value.toFixed(3)}</span>
    </div>
  )
}

export function EvidencePanel({
  sources,
  citations,
  open,
  onOpenCitation,
  onCloseDocument,
  onClose,
  tab,
  onTabChange,
  loading,
}: {
  sources: Source[]
  citations: Citation[]
  open: OpenCitation | null
  onOpenCitation: (c: OpenCitation) => void
  onCloseDocument: () => void
  onClose?: () => void
  tab: 'evidence' | 'document'
  onTabChange: (t: 'evidence' | 'document') => void
  loading?: boolean
}) {
  const citedChunks = new Map(citations.map((c) => [c.chunk_id, c]))
  const maxRerank = Math.max(1, ...sources.map((s) => Math.abs(s.scores.rerank ?? 0)))

  return (
    <div className="flex h-full min-h-0 flex-col bg-card/40" data-testid="evidence-panel">
      <Tabs value={tab} onValueChange={(v) => onTabChange(v as 'evidence' | 'document')} className="flex min-h-0 flex-1 flex-col gap-0">
        <div className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
          <TabsList className="h-8">
            <TabsTrigger value="evidence" className="text-xs"><Layers className="size-3.5" /> Evidence {sources.length > 0 && `(${sources.length})`}</TabsTrigger>
            <TabsTrigger value="document" className="text-xs" disabled={!open}><FileText className="size-3.5" /> Document</TabsTrigger>
          </TabsList>
          {onClose && (
            <Button variant="ghost" size="icon" className="ml-auto size-7" onClick={onClose} aria-label="Close evidence panel">
              <X className="size-4" />
            </Button>
          )}
        </div>
        <TabsContent value="evidence" className="mt-0 min-h-0 min-w-0 flex-1">
          <div className="scrollbar-thin h-full overflow-y-auto overflow-x-hidden">
            <div className="space-y-2.5 p-3">
              {loading && sources.length === 0 &&
                Array.from({ length: 3 }).map((_, i) => <div key={i} className="h-28 animate-pulse rounded-lg bg-muted" />)}
              {!loading && sources.length === 0 && (
                <EmptyState icon={Layers} title="No evidence yet" description="Retrieved passages, scores and page references appear here when you ask a question." className="border-none" />
              )}
              {sources.map((s) => {
                const cite = citedChunks.get(s.chunk_id)
                const isOpen = open?.chunkId === s.chunk_id
                return (
                  <article
                    key={s.chunk_id}
                    className={cn('rounded-lg border bg-card p-3 transition-colors', cite && 'border-primary/30', isOpen && 'ring-1 ring-primary')}
                    data-testid="evidence-item"
                  >
                    <div className="mb-1.5 flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="grid size-5 shrink-0 place-items-center rounded bg-muted text-[10px] font-semibold tabular-nums">{s.rank}</span>
                          <span className="truncate text-xs font-medium" title={s.source}>{s.source}</span>
                        </div>
                        <div className="mt-0.5 text-[11px] text-muted-foreground">
                          {pagesLabel(s.page_start, s.page_end)}
                          {cite && <span className="ml-1.5 font-medium text-primary">· cited as {cite.tag}{cite.method === 'attributed' ? ' (attributed)' : ''}</span>}
                        </div>
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 shrink-0 px-2 text-xs"
                        onClick={() => onOpenCitation({ docId: s.doc_id, page: s.page_start, excerpt: cite?.excerpt ?? s.text.slice(0, 200), chunkId: s.chunk_id, source: s.source })}
                        aria-label={`Open ${s.source} at ${pagesLabel(s.page_start, s.page_end)}`}
                      >
                        Open page
                      </Button>
                    </div>
                    <p className="line-clamp-5 text-xs leading-relaxed text-foreground/85">{s.text}</p>
                    <div className="mt-2 space-y-1">
                      {s.scores.rerank != null && <ScoreBar label="rerank" value={s.scores.rerank} max={maxRerank} />}
                      {s.scores.dense != null && <ScoreBar label="cosine" value={s.scores.dense} max={1} />}
                      {s.scores.bm25 != null && <div className="text-[11px] text-muted-foreground">BM25 {s.scores.bm25.toFixed(2)}</div>}
                    </div>
                  </article>
                )
              })}
            </div>
          </div>
        </TabsContent>
        <TabsContent value="document" className="mt-0 min-h-0 flex-1">
          {open ? (
            <PdfViewer
              documentId={open.docId}
              page={open.page}
              highlight={open.excerpt}
              toolbarExtra={
                <>
                  <Button asChild variant="ghost" size="icon" className="size-8">
                    <Link to={`/documents/${open.docId}?page=${open.page}`} aria-label="Open in full viewer"><ExternalLink className="size-3.5" /></Link>
                  </Button>
                  <Button variant="ghost" size="icon" className="size-8" onClick={onCloseDocument} aria-label="Close document"><X className="size-3.5" /></Button>
                </>
              }
            />
          ) : (
            <EmptyState icon={FileText} title="No document open" description="Click a citation to open the cited page." className="m-3 border-none" />
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
