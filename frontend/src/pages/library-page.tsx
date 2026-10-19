import { FileText, MessageSquare, Search, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'

import { EmptyState, PageHeader } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { DocumentCard } from '@/features/documents/document-card'
import { UploadDropzone } from '@/features/documents/upload-dropzone'
import { useDocuments } from '@/services/queries'
import type { DocumentStatus } from '@/types/api'

type Filter = 'all' | DocumentStatus
type Sort = 'newest' | 'name' | 'pages'

export default function LibraryPage() {
  const navigate = useNavigate()
  const { data, isLoading, isError, refetch } = useDocuments()
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [sort, setSort] = useState<Sort>('newest')
  const [selected, setSelected] = useState<string[]>([])

  const items = useMemo(() => {
    const q = query.trim().toLowerCase()
    let list = (data?.items ?? []).filter(
      (d) => (filter === 'all' || d.status === filter || (filter === 'processing' && d.status === 'queued')) &&
        (!q || d.filename.toLowerCase().includes(q) || d.title.toLowerCase().includes(q)),
    )
    list = [...list].sort((a, b) =>
      sort === 'name' ? a.filename.localeCompare(b.filename) : sort === 'pages' ? b.page_count - a.page_count : b.created_at.localeCompare(a.created_at),
    )
    return list
  }, [data, query, filter, sort])

  const counts = useMemo(() => {
    const all = data?.items ?? []
    return {
      all: all.length,
      ready: all.filter((d) => d.status === 'ready').length,
      processing: all.filter((d) => d.status === 'processing' || d.status === 'queued').length,
      failed: all.filter((d) => d.status === 'failed').length,
    }
  }, [data])

  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-8 sm:py-8">
        <PageHeader
          title="Document library"
          description="Upload PDFs, watch them index, and choose which ones to ask about."
          actions={
            selected.length > 0 && (
              <>
                <Button variant="ghost" size="sm" onClick={() => setSelected([])}><X className="size-4" /> Clear</Button>
                <Button size="sm" onClick={() => navigate(`/chat?${selected.map((s) => `doc=${s}`).join('&')}`)}>
                  <MessageSquare className="size-4" /> Ask about {selected.length} selected
                </Button>
              </>
            )
          }
        />
        <UploadDropzone className="mb-6" />

        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1 sm:max-w-xs">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by name or title" className="pl-8" aria-label="Search documents" />
          </div>
          <ToggleGroup type="single" value={filter} onValueChange={(v) => v && setFilter(v as Filter)} variant="outline" size="sm" aria-label="Filter by status" className="flex-wrap">
            <ToggleGroupItem value="all">All {counts.all}</ToggleGroupItem>
            <ToggleGroupItem value="ready">Ready {counts.ready}</ToggleGroupItem>
            <ToggleGroupItem value="processing">Processing {counts.processing}</ToggleGroupItem>
            <ToggleGroupItem value="failed">Failed {counts.failed}</ToggleGroupItem>
          </ToggleGroup>
          <Select value={sort} onValueChange={(v) => setSort(v as Sort)}>
            <SelectTrigger size="sm" className="w-40 sm:ml-auto" aria-label="Sort documents"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="newest">Newest first</SelectItem>
              <SelectItem value="name">Name A–Z</SelectItem>
              <SelectItem value="pages">Most pages</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {isError ? (
          <EmptyState icon={FileText} title="Could not load documents" description="The backend did not respond." action={<Button onClick={() => refetch()}>Retry</Button>} />
        ) : isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="aspect-[3/4] rounded-xl" />)}
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={FileText}
            title={data?.items.length ? 'No documents match' : 'Your library is empty'}
            description={data?.items.length ? 'Try a different search or filter.' : 'Upload a PDF above to make it searchable.'}
          />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" data-testid="document-grid">
            {items.map((d) => (
              <DocumentCard
                key={d.id}
                doc={d}
                selected={selected.includes(d.id)}
                onSelectedChange={(v) => setSelected((s) => (v ? [...s, d.id] : s.filter((x) => x !== d.id)))}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
