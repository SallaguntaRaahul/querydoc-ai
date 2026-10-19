import { AlertCircle, ChevronLeft, ChevronRight, Loader2, Maximize2, Minus, Plus, Search, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Document, Page } from 'react-pdf'
import type { PDFDocumentProxy } from 'pdfjs-dist'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { fileUrl, markOccurrences, passageItemMatcher, escapeHtml } from '@/features/viewer/pdf-setup'

export interface PdfViewerProps {
  documentId: string
  page?: number
  /** Verified passage to locate on the current page (citation excerpt). */
  highlight?: string | null
  onPageChange?: (page: number) => void
  className?: string
  toolbarExtra?: React.ReactNode
}

const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2, 2.5]

interface SearchHit {
  page: number
  count: number
}

export function PdfViewer({ documentId, page = 1, highlight, onPageChange, className, toolbarExtra }: PdfViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const pdfRef = useRef<PDFDocumentProxy | null>(null)
  const [numPages, setNumPages] = useState(0)
  const [current, setCurrent] = useState(page)
  const [pageInput, setPageInput] = useState(String(page))
  const [zoom, setZoom] = useState(1)
  const [width, setWidth] = useState(600)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [activeQuery, setActiveQuery] = useState('')
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [pageItems, setPageItems] = useState<string[]>([])

  // External navigation (citation click) wins over local state.
  useEffect(() => {
    setCurrent(page)
    setPageInput(String(page))
  }, [page, documentId])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(240, Math.floor(e.contentRect.width) - 32)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const go = useCallback(
    (p: number) => {
      if (!numPages) return
      const next = Math.min(Math.max(1, p), numPages)
      setCurrent(next)
      setPageInput(String(next))
      onPageChange?.(next)
    },
    [numPages, onPageChange],
  )

  const runSearch = useCallback(async () => {
    const q = query.trim()
    setActiveQuery(q)
    if (!q || !pdfRef.current) {
      setHits(null)
      return
    }
    setSearching(true)
    const found: SearchHit[] = []
    const needle = q.toLowerCase()
    const pdf = pdfRef.current
    for (let i = 1; i <= pdf.numPages; i++) {
      const content = await (await pdf.getPage(i)).getTextContent()
      const text = content.items.map((it) => ('str' in it ? it.str : '')).join(' ').toLowerCase()
      let count = 0
      let idx = text.indexOf(needle)
      while (idx !== -1) {
        count++
        idx = text.indexOf(needle, idx + needle.length)
      }
      if (count) found.push({ page: i, count })
    }
    setHits(found)
    setSearching(false)
    if (found.length && !found.some((h) => h.page === current)) go(found[0].page)
  }, [query, current, go])

  const passage = useMemo(() => (highlight ? passageItemMatcher(pageItems, highlight) : null), [pageItems, highlight])

  const textRenderer = useCallback(
    ({ str }: { str: string }) => {
      if (activeQuery) return markOccurrences(str, activeQuery)
      if (passage?.matches(str)) return `<mark class="pdf-highlight">${escapeHtml(str)}</mark>`
      return escapeHtml(str)
    },
    [activeQuery, passage],
  )

  const hitIndex = hits ? hits.findIndex((h) => h.page === current) : -1
  const totalHits = hits?.reduce((a, h) => a + h.count, 0) ?? 0

  return (
    <div className={cn('flex h-full min-h-0 flex-col bg-muted/30', className)}>
      <div className="flex flex-wrap items-center gap-1 border-b bg-background/80 px-2 py-1.5 backdrop-blur" role="toolbar" aria-label="PDF controls">
        <Button variant="ghost" size="icon" className="size-8" onClick={() => go(current - 1)} disabled={current <= 1} aria-label="Previous page">
          <ChevronLeft className="size-4" />
        </Button>
        <form
          onSubmit={(e) => { e.preventDefault(); go(Number(pageInput) || current) }}
          className="flex items-center gap-1 text-xs text-muted-foreground"
        >
          <Input
            value={pageInput}
            onChange={(e) => setPageInput(e.target.value.replace(/\D/g, ''))}
            className="h-7 w-11 px-1 text-center text-xs"
            aria-label="Current page"
            inputMode="numeric"
          />
          <span aria-live="polite">/ {numPages || '…'}</span>
        </form>
        <Button variant="ghost" size="icon" className="size-8" onClick={() => go(current + 1)} disabled={!numPages || current >= numPages} aria-label="Next page">
          <ChevronRight className="size-4" />
        </Button>
        <div className="mx-1 h-5 w-px bg-border" />
        <Button variant="ghost" size="icon" className="size-8" aria-label="Zoom out"
          onClick={() => setZoom((z) => ZOOM_STEPS[Math.max(0, ZOOM_STEPS.indexOf(z) - 1)] ?? z)} disabled={zoom <= ZOOM_STEPS[0]}>
          <Minus className="size-4" />
        </Button>
        <span className="w-10 text-center text-xs tabular-nums text-muted-foreground">{Math.round(zoom * 100)}%</span>
        <Button variant="ghost" size="icon" className="size-8" aria-label="Zoom in"
          onClick={() => setZoom((z) => ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, ZOOM_STEPS.indexOf(z) + 1)] ?? z)} disabled={zoom >= ZOOM_STEPS.at(-1)!}>
          <Plus className="size-4" />
        </Button>
        <Button variant="ghost" size="icon" className="size-8" aria-label="Fit to width" onClick={() => setZoom(1)}>
          <Maximize2 className="size-3.5" />
        </Button>
        <form className="ml-auto flex items-center gap-1" onSubmit={(e) => { e.preventDefault(); void runSearch() }} role="search">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search in PDF"
              className="h-7 w-36 pl-7 text-xs sm:w-44"
              aria-label="Search in PDF"
            />
          </div>
          {searching && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label="Searching" />}
          {hits && !searching && (
            <>
              <span className="text-xs tabular-nums text-muted-foreground" aria-live="polite">
                {totalHits ? `${totalHits} on ${hits.length} pages` : 'No matches'}
              </span>
              {hits.length > 0 && (
                <>
                  <Button type="button" variant="ghost" size="icon" className="size-7" aria-label="Previous match page"
                    onClick={() => go(hits[(hitIndex <= 0 ? hits.length : hitIndex) - 1].page)}>
                    <ChevronLeft className="size-3.5" />
                  </Button>
                  <Button type="button" variant="ghost" size="icon" className="size-7" aria-label="Next match page"
                    onClick={() => go(hits[(hitIndex + 1) % hits.length].page)}>
                    <ChevronRight className="size-3.5" />
                  </Button>
                </>
              )}
              <Button type="button" variant="ghost" size="icon" className="size-7" aria-label="Clear search"
                onClick={() => { setQuery(''); setActiveQuery(''); setHits(null) }}>
                <X className="size-3.5" />
              </Button>
            </>
          )}
        </form>
        {toolbarExtra}
      </div>
      {highlight && !activeQuery && passage && pageItems.length > 0 && (
        <div className={cn('flex items-center gap-2 border-b px-3 py-1.5 text-xs', passage.found ? 'bg-highlight/30 text-foreground' : 'bg-muted text-muted-foreground')} role="status">
          {passage.found ? (
            <><span className="inline-block size-2.5 rounded-sm bg-highlight" aria-hidden /> Supporting passage highlighted on page {current}</>
          ) : (
            <><AlertCircle className="size-3.5" aria-hidden /> Showing the cited page {current}. The exact passage could not be located in this page’s text layer, so nothing is highlighted.</>
          )}
        </div>
      )}
      <div ref={containerRef} className="scrollbar-thin min-h-0 flex-1 overflow-auto p-4">
        {error ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
            <AlertCircle className="size-6 text-destructive" aria-hidden />
            <p>{error}</p>
          </div>
        ) : (
          <Document
            file={fileUrl(documentId)}
            onLoadSuccess={(pdf) => {
              pdfRef.current = pdf as unknown as PDFDocumentProxy
              setNumPages(pdf.numPages)
              setError(null)
              if (current > pdf.numPages) go(pdf.numPages)
            }}
            onLoadError={() => setError('This PDF could not be loaded. It may have been deleted.')}
            loading={<div className="flex h-64 items-center justify-center"><Loader2 className="size-6 animate-spin text-muted-foreground" aria-label="Loading PDF" /></div>}
            className="flex justify-center"
          >
            <Page
              key={`${documentId}-${current}`}
              pageNumber={current}
              width={Math.round(width * zoom)}
              className="overflow-hidden rounded-md shadow-lg shadow-black/10 ring-1 ring-black/5"
              customTextRenderer={textRenderer}
              onGetTextSuccess={(tc) => setPageItems(tc.items.map((it) => ('str' in it ? it.str : '')))}
              loading={<div className="h-[70vh] animate-pulse rounded-md bg-muted" style={{ width: Math.round(width * zoom) }} />}
            />
          </Document>
        )}
      </div>
    </div>
  )
}
