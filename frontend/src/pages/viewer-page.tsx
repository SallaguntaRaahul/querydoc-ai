import { ArrowLeft, ExternalLink, FileText, MessageSquare, PanelRightClose, PanelRightOpen } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { DocumentStatusBadge, EmptyState } from '@/components/common'
import { Button } from '@/components/ui/button'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { Composer } from '@/features/chat/composer'
import { AssistantMessage, UserBubble } from '@/features/chat/message'
import { PdfViewer } from '@/features/viewer/pdf-viewer'
import { useChatStream } from '@/hooks/use-chat-stream'
import { useMediaQuery } from '@/hooks/use-media-query'
import { formatBytes } from '@/lib/format'
import { useConversation, useDocument } from '@/services/queries'
import type { Citation } from '@/types/api'

/** Side-by-side: the PDF on the left, a chat scoped to this document on the right. */
function DocumentChat({ documentId, onCite }: { documentId: string; onCite: (c: Citation) => void }) {
  const [conversationId, setConversationId] = useState<string | null>(null)
  const onConversation = useCallback((id: string) => setConversationId(id), [])
  const { state, send, stop } = useChatStream(onConversation)
  const { data: conversation } = useConversation(conversationId ?? undefined)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [conversation?.messages.length, state.text])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
        <MessageSquare className="size-4 text-primary" aria-hidden />
        <span className="text-sm font-medium">Ask this document</span>
        {conversationId && (
          <Button asChild variant="ghost" size="sm" className="ml-auto h-7 text-xs">
            <Link to={`/chat/${conversationId}`}>Open in chat <ExternalLink className="size-3" /></Link>
          </Button>
        )}
      </div>
      <div ref={scrollRef} className="scrollbar-thin min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
        {!conversation?.messages.length && !state.active && (
          <p className="pt-6 text-center text-sm text-muted-foreground">Questions here are answered only from this PDF. Citations jump to the page on the left.</p>
        )}
        {conversation?.messages.map((m) =>
          m.role === 'user' ? <UserBubble key={m.id} content={m.content} /> : <AssistantMessage key={m.id} message={m} onOpenCitation={onCite} />,
        )}
        {state.active && !conversation?.messages.some((m) => m.id === state.userMessage?.id) && state.question && <UserBubble content={state.question} />}
        {state.active && (
          <div className="text-sm text-muted-foreground" aria-live="polite">{state.text || (state.phase === 'retrieving' ? 'Searching…' : 'Writing…')}</div>
        )}
        {state.error && <p role="alert" className="text-sm text-destructive">{state.error.message}</p>}
      </div>
      <div className="p-3">
        <Composer
          streaming={state.active}
          onStop={stop}
          onSend={(text) => void send({ message: text, conversation_id: conversationId, document_ids: [documentId] })}
        />
      </div>
    </div>
  )
}

export default function ViewerPage() {
  const { documentId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const isDesktop = useMediaQuery('(min-width: 1024px)')
  const { data: doc, isLoading, isError } = useDocument(documentId)
  const [page, setPage] = useState(() => Number(params.get('page')) || 1)
  const [highlight, setHighlight] = useState<string | null>(params.get('q'))
  const [chatOpen, setChatOpen] = useState(isDesktop)

  const onPageChange = useCallback(
    (p: number) => {
      setPage(p)
      setParams((prev) => { prev.set('page', String(p)); prev.delete('q'); return prev }, { replace: true })
    },
    [setParams],
  )
  const onCite = (c: Citation) => {
    if (c.doc_id !== documentId) return
    setHighlight(c.excerpt)
    setPage(c.page_start)
  }

  if (isError) {
    return <div className="p-8"><EmptyState icon={FileText} title="Document not found" description="It may have been deleted." action={<Button asChild><Link to="/library">Back to library</Link></Button>} /></div>
  }

  const viewer = doc?.status === 'ready' ? (
    <PdfViewer
      documentId={documentId}
      page={page}
      highlight={highlight}
      onPageChange={onPageChange}
      toolbarExtra={
        <Button variant="ghost" size="icon" className="size-8" onClick={() => setChatOpen((o) => !o)} aria-label={chatOpen ? 'Hide chat' : 'Show chat'}>
          {chatOpen ? <PanelRightClose className="size-4" /> : <PanelRightOpen className="size-4" />}
        </Button>
      }
    />
  ) : (
    <div className="grid h-full place-items-center text-sm text-muted-foreground">
      {isLoading ? 'Loading…' : doc ? `This document is ${doc.status}.` : null}
    </div>
  )

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-12 shrink-0 items-center gap-3 border-b px-3">
        <Button asChild variant="ghost" size="icon" className="size-8"><Link to="/library" aria-label="Back to library"><ArrowLeft className="size-4" /></Link></Button>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-medium" title={doc?.filename}>{doc?.filename ?? 'Loading…'}</h1>
          {doc && <p className="truncate text-[11px] text-muted-foreground">{doc.page_count} pages · {doc.chunk_count} chunks · {formatBytes(doc.size_bytes)}</p>}
        </div>
        {doc && <DocumentStatusBadge status={doc.status} />}
      </div>
      <div className="min-h-0 flex-1">
        {isDesktop && chatOpen ? (
          <ResizablePanelGroup orientation="horizontal">
            <ResizablePanel id="pdf" minSize="360px" defaultSize="62%">{viewer}</ResizablePanel>
            <ResizableHandle withHandle />
            <ResizablePanel id="doc-chat" minSize="320px" defaultSize="38%" className="border-l">
              <DocumentChat documentId={documentId} onCite={onCite} />
            </ResizablePanel>
          </ResizablePanelGroup>
        ) : (
          <div className="flex h-full min-h-0 flex-col">
            <div className={chatOpen ? 'h-1/2 min-h-0' : 'h-full min-h-0'}>{viewer}</div>
            {chatOpen && <div className="h-1/2 min-h-0 border-t"><DocumentChat documentId={documentId} onCite={onCite} /></div>}
          </div>
        )}
      </div>
    </div>
  )
}
