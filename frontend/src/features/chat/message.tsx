import { Check, Copy, RotateCcw, ThumbsDown, ThumbsUp, User } from 'lucide-react'
import { motion } from 'motion/react'
import { useMemo, useState, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'

import { AnswerStatusBadge } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { formatMs, pagesLabel } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Citation, Message } from '@/types/api'

const CITE_RE = /\[(?:sources?\s*:?\s*)?(S\s*\d+(?:\s*(?:[,;]|and)\s*S?\s*\d+)*)\]/gi

/** Turn [S1] / [S1, S3] / [Source S2] markers into markdown links the renderer turns into chips. */
export function linkifyCitations(text: string, valid: Set<string>): string {
  return text.replace(CITE_RE, (_m, group: string) => {
    const tags = (group.match(/\d+/g) ?? []).map((n) => `S${Number(n)}`).filter((t) => valid.has(t))
    return tags.map((t) => `[${t}](#cite-${t})`).join('')
  })
}

export function CitationChip({ citation, onOpen, active }: { citation: Citation; onOpen: (c: Citation) => void; active?: boolean }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={() => onOpen(citation)}
          className={cn(
            'mx-0.5 inline-flex h-[18px] items-center rounded-[5px] border px-1 align-[1px] text-[10.5px] font-semibold tabular-nums leading-none transition-colors',
            'border-primary/30 bg-primary/10 text-primary hover:bg-primary/20 focus-visible:outline-2',
            active && 'bg-primary text-primary-foreground',
          )}
          aria-label={`Citation ${citation.tag}: ${citation.source}, ${pagesLabel(citation.page_start, citation.page_end)}`}
          data-testid="citation-chip"
        >
          {citation.tag.replace('S', '')}
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">
        <div className="font-medium">{citation.source} · {pagesLabel(citation.page_start, citation.page_end)}</div>
        <div className="mt-1 line-clamp-4 opacity-90">“{citation.excerpt}”</div>
      </TooltipContent>
    </Tooltip>
  )
}

function Action({ label, onClick, children, pressed }: { label: string; onClick: () => void; children: ReactNode; pressed?: boolean }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon" className={cn('size-7 text-muted-foreground', pressed && 'text-primary')} onClick={onClick} aria-label={label} aria-pressed={pressed}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

export function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end gap-3" data-testid="user-message">
      <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-tr-sm bg-secondary px-4 py-2.5 text-sm text-secondary-foreground">
        {content}
      </div>
      <div className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground" aria-hidden>
        <User className="size-3.5" />
      </div>
    </div>
  )
}

export function AssistantAvatar({ pulsing = false }: { pulsing?: boolean }) {
  return (
    <div
      aria-hidden
      className={cn(
        'mt-0.5 grid size-7 shrink-0 place-items-center rounded-full bg-gradient-to-br from-primary to-[oklch(0.55_0.2_300)] text-[11px] font-bold text-primary-foreground',
        pulsing && 'animate-pulse',
      )}
    >
      Q
    </div>
  )
}

export function AssistantMessage({
  message,
  onOpenCitation,
  activeCitation,
  onRegenerate,
  onFeedback,
  onSelect,
  selected,
  canRegenerate,
}: {
  message: Message
  onOpenCitation: (c: Citation) => void
  activeCitation?: string | null
  onRegenerate?: () => void
  onFeedback?: (v: 1 | -1 | null) => void
  onSelect?: () => void
  selected?: boolean
  canRegenerate?: boolean
}) {
  const [copied, setCopied] = useState(false)
  const byTag = useMemo(() => new Map(message.citations.map((c) => [c.tag, c])), [message.citations])
  const md = useMemo(() => linkifyCitations(message.content, new Set(byTag.keys())), [message.content, byTag])
  const attributed = message.citations.filter((c) => c.method === 'attributed')

  const copy = async () => {
    const plain = message.content.replace(CITE_RE, '').replace(/\s{2,}/g, ' ').trim()
    const refs = message.citations.map((c) => `[${c.tag}] ${c.source}, ${pagesLabel(c.page_start, c.page_end)}`).join('\n')
    try {
      await navigator.clipboard.writeText(refs ? `${plain}\n\nSources:\n${refs}` : plain)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
      className={cn('group flex gap-3 rounded-xl', selected && 'bg-accent/30 -mx-2 px-2 py-1')}
      data-testid="assistant-message"
      onClick={onSelect}
    >
      <AssistantAvatar />
      <div className="min-w-0 flex-1">
        <div className="mb-1.5 flex flex-wrap items-center gap-2">
          <AnswerStatusBadge status={message.status} />
          {message.timings_ms.total != null && (
            <span className="text-[11px] tabular-nums text-muted-foreground">
              {formatMs(message.timings_ms.total)}
              {message.timings_ms.retrieval != null && ` · retrieval ${formatMs(message.timings_ms.retrieval)}`}
            </span>
          )}
        </div>
        <div className="prose-answer text-sm leading-relaxed">
          <ReactMarkdown
            components={{
              a: ({ href, children }) => {
                if (href?.startsWith('#cite-')) {
                  const c = byTag.get(href.slice(6))
                  return c ? <CitationChip citation={c} onOpen={onOpenCitation} active={activeCitation === c.chunk_id} /> : <>{children}</>
                }
                return <a href={href} target="_blank" rel="noreferrer noopener" className="text-primary underline underline-offset-2">{children}</a>
              },
              p: ({ children }) => <p className="mb-2.5 last:mb-0">{children}</p>,
              ul: ({ children }) => <ul className="mb-2.5 ml-5 list-disc space-y-1">{children}</ul>,
              ol: ({ children }) => <ol className="mb-2.5 ml-5 list-decimal space-y-1">{children}</ol>,
              strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
              code: ({ children }) => <code className="rounded bg-muted px-1 py-0.5 font-mono text-[12px]">{children}</code>,
              img: () => null,
            }}
          >
            {md}
          </ReactMarkdown>
        </div>
        {message.citations.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5" aria-label="Sources">
            {message.citations.map((c) => (
              <button
                key={c.tag}
                type="button"
                onClick={(e) => { e.stopPropagation(); onOpenCitation(c) }}
                className={cn(
                  'inline-flex max-w-full items-center gap-1.5 rounded-md border bg-card px-2 py-1 text-left text-xs transition-colors hover:border-primary/40 hover:bg-accent',
                  activeCitation === c.chunk_id && 'border-primary/60 bg-accent',
                )}
                data-testid="source-pill"
              >
                <span className="font-semibold text-primary">{c.tag.replace('S', '')}</span>
                <span className="truncate">{c.source}</span>
                <span className="shrink-0 text-muted-foreground">{pagesLabel(c.page_start, c.page_end)}</span>
              </button>
            ))}
          </div>
        )}
        {message.notes.length > 0 && (
          <ul className="mt-2.5 space-y-0.5 text-[11px] text-muted-foreground">
            {message.notes.map((n) => <li key={n}>• {n}</li>)}
          </ul>
        )}
        {attributed.length > 0 && <span className="sr-only">{attributed.length} citations attached by post-hoc alignment</span>}
        <div className="mt-1.5 flex items-center gap-0.5 opacity-70 transition-opacity group-hover:opacity-100">
          <Action label={copied ? 'Copied' : 'Copy answer'} onClick={copy}>{copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}</Action>
          {canRegenerate && onRegenerate && <Action label="Regenerate response" onClick={onRegenerate}><RotateCcw className="size-3.5" /></Action>}
          {onFeedback && (
            <>
              <Action label="Helpful" pressed={message.feedback === 1} onClick={() => onFeedback(message.feedback === 1 ? null : 1)}><ThumbsUp className="size-3.5" /></Action>
              <Action label="Not helpful" pressed={message.feedback === -1} onClick={() => onFeedback(message.feedback === -1 ? null : -1)}><ThumbsDown className="size-3.5" /></Action>
            </>
          )}
        </div>
      </div>
    </motion.div>
  )
}
