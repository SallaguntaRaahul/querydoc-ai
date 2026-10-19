import { FileText, MessageSquare, MoreHorizontal, RefreshCw, Trash2 } from 'lucide-react'
import { lazy, Suspense, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'

import { DocumentStatusBadge } from '@/components/common'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Progress } from '@/components/ui/progress'
import { ApiError } from '@/lib/api'
import { formatBytes, formatNumber, relativeTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useDeleteDocument, useReindexDocument } from '@/services/queries'
import type { DocumentItem } from '@/types/api'

const PdfThumbnail = lazy(() => import('@/features/viewer/pdf-thumbnail'))

const STAGE_LABEL: Record<string, string> = {
  queued: 'Waiting in queue', starting: 'Starting', extract: 'Extracting text', embed: 'Embedding chunks', done: 'Finalizing',
}

export function DocumentCard({
  doc,
  selected,
  onSelectedChange,
}: {
  doc: DocumentItem
  selected?: boolean
  onSelectedChange?: (v: boolean) => void
}) {
  const navigate = useNavigate()
  const del = useDeleteDocument()
  const reindex = useReindexDocument()
  const [confirm, setConfirm] = useState(false)
  const busy = doc.status === 'queued' || doc.status === 'processing'

  const onDelete = async () => {
    try {
      await del.mutateAsync(doc.id)
      toast.success(`Deleted ${doc.filename} and its index entries`)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'Delete failed')
    }
  }
  const onReindex = async () => {
    try {
      await reindex.mutateAsync(doc.id)
      toast.success('Re-indexing started')
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'Re-index failed')
    }
  }

  return (
    <article
      className={cn(
        'group relative flex flex-col overflow-hidden rounded-xl border bg-card transition-shadow hover:shadow-md hover:shadow-black/5',
        selected && 'ring-2 ring-primary',
      )}
      data-testid="document-card"
      aria-label={doc.filename}
    >
      <Link
        to={doc.status === 'ready' ? `/documents/${doc.id}` : '#'}
        aria-disabled={doc.status !== 'ready'}
        tabIndex={doc.status === 'ready' ? 0 : -1}
        className="relative block aspect-[4/3] overflow-hidden border-b bg-muted/50"
      >
        {doc.status === 'ready' ? (
          <Suspense fallback={<div className="size-full animate-pulse bg-muted" />}>
            <PdfThumbnail documentId={doc.id} />
          </Suspense>
        ) : (
          <div className="grid size-full place-items-center text-muted-foreground">
            <FileText className="size-10 opacity-40" aria-hidden />
          </div>
        )}
      </Link>
      {onSelectedChange && doc.status === 'ready' && (
        <div className="absolute left-2.5 top-2.5">
          <Checkbox
            checked={selected}
            onCheckedChange={(v) => onSelectedChange(v === true)}
            aria-label={`Select ${doc.filename}`}
            className="bg-background/90 shadow-sm backdrop-blur"
          />
        </div>
      )}
      <div className="flex flex-1 flex-col gap-2 p-3.5">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-medium" title={doc.filename}>{doc.filename}</h3>
            <p className="truncate text-xs text-muted-foreground" title={doc.title}>{doc.title}</p>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="-mr-1.5 -mt-1 size-7 shrink-0" aria-label={`Actions for ${doc.filename}`}>
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem disabled={doc.status !== 'ready'} onSelect={() => navigate(`/chat?doc=${doc.id}`)}>
                <MessageSquare className="size-4" /> Ask about this document
              </DropdownMenuItem>
              <DropdownMenuItem disabled={doc.status !== 'ready'} onSelect={() => navigate(`/documents/${doc.id}`)}>
                <FileText className="size-4" /> Open viewer
              </DropdownMenuItem>
              <DropdownMenuItem disabled={busy} onSelect={onReindex}>
                <RefreshCw className="size-4" /> Re-index
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" disabled={busy} onSelect={() => setConfirm(true)}>
                <Trash2 className="size-4" /> Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <DocumentStatusBadge status={doc.status} />
          {doc.page_count > 0 && <span>{formatNumber(doc.page_count)} pages</span>}
          {doc.chunk_count > 0 && <span>· {formatNumber(doc.chunk_count)} chunks</span>}
          <span>· {formatBytes(doc.size_bytes)}</span>
        </div>
        {busy && (
          <div aria-live="polite">
            <Progress value={doc.progress * 100} aria-label={`Indexing progress for ${doc.filename}`} className="h-1.5" />
            <p className="mt-1 text-[11px] text-muted-foreground">{STAGE_LABEL[doc.stage] ?? doc.stage} · {Math.round(doc.progress * 100)}%</p>
          </div>
        )}
        {doc.status === 'failed' && doc.error && <p className="line-clamp-2 text-xs text-destructive" title={doc.error}>{doc.error}</p>}
        {doc.scanned_pages.length > 0 && (
          <p className="text-[11px] text-warning">{doc.scanned_pages.length} scanned page(s) not indexed (OCR disabled)</p>
        )}
        <p className="mt-auto pt-1 text-[11px] text-muted-foreground">Added {relativeTime(doc.created_at)}</p>
      </div>
      <AlertDialog open={confirm} onOpenChange={setConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete “{doc.filename}”?</AlertDialogTitle>
            <AlertDialogDescription>
              The PDF, its {formatNumber(doc.chunk_count)} indexed chunks and its vectors will be removed. Past answers keep their text, but their citations to this document will no longer open.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={onDelete}>Delete document</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </article>
  )
}
