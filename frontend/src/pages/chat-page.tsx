import { AlertCircle, Loader2, PanelRightClose, PanelRightOpen, Sparkles, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { useNavigate, useParams, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { EmptyState } from '@/components/common'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { Composer } from '@/features/chat/composer'
import { EvidencePanel, type OpenCitation } from '@/features/chat/evidence-panel'
import { AssistantAvatar, AssistantMessage, UserBubble } from '@/features/chat/message'
import { ScopePicker } from '@/features/chat/scope-picker'
import { UploadDropzone } from '@/features/documents/upload-dropzone'
import { useChatStream } from '@/hooks/use-chat-stream'
import { useMediaQuery } from '@/hooks/use-media-query'
import { useConversation, useDeleteConversation, useDocuments, useFeedback } from '@/services/queries'
import type { Citation, Message } from '@/types/api'

const PANEL_KEY = 'querydoc.evidence.open'

function suggestions(titles: string[]): string[] {
  const t = titles.slice(0, 2)
  const which = titles.length === 1 ? 'this document' : 'these documents'
  const base = [`Summarize the main purpose of ${which}.`, `What are the key requirements or recommendations in ${which}?`]
  return [...base, ...t.map((x) => `What does “${x.length > 48 ? `${x.slice(0, 45)}…` : x}” say about responsibilities?`)].slice(0, 4)
}

function StreamingMessage({ text, phase, scopeCount }: { text: string; phase: string; scopeCount: number }) {
  return (
    <div className="flex gap-3" data-testid="streaming-message" aria-live="polite" aria-busy>
      <AssistantAvatar pulsing={!text} />
      <div className="min-w-0 flex-1 text-sm leading-relaxed">
        {!text ? (
          <div className="flex items-center gap-2 py-1 text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
            {phase === 'retrieving' ? `Searching ${scopeCount} document${scopeCount === 1 ? '' : 's'}…` : 'Reading the evidence and writing an answer…'}
          </div>
        ) : (
          <div className="[&_p]:mb-2.5">
            <ReactMarkdown components={{ img: () => null }}>{text}</ReactMarkdown>
            <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-primary/70 align-middle" aria-hidden />
          </div>
        )}
      </div>
    </div>
  )
}

export default function ChatPage() {
  const { conversationId } = useParams()
  const [search] = useSearchParams()
  const navigate = useNavigate()
  const isDesktop = useMediaQuery('(min-width: 1024px)')
  const { data: docs } = useDocuments()
  const { data: conversation, isLoading: convLoading, isError: convError } = useConversation(conversationId)
  const feedback = useFeedback(conversationId ?? '')
  const delConversation = useDeleteConversation()
  const onConversation = useCallback((id: string) => navigate(`/chat/${id}`, { replace: true }), [navigate])
  const { state: stream, send, stop, clearError } = useChatStream(onConversation)

  const readyDocs = useMemo(() => (docs?.items ?? []).filter((d) => d.status === 'ready'), [docs])
  const [scope, setScope] = useState<string[]>(() => search.getAll('doc'))
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [openCitation, setOpenCitation] = useState<OpenCitation | null>(null)
  const [tab, setTab] = useState<'evidence' | 'document'>('evidence')
  const [panelOpen, setPanelOpen] = useState(() => {
    try {
      return localStorage.getItem(PANEL_KEY) !== '0'
    } catch {
      return true
    }
  })
  const [mobilePanel, setMobilePanel] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)

  useEffect(() => {
    try {
      localStorage.setItem(PANEL_KEY, panelOpen ? '1' : '0')
    } catch {
      /* ignore */
    }
  }, [panelOpen])

  // Conversation scope is restored when a saved conversation is opened.
  useEffect(() => {
    if (conversation) setScope(conversation.document_ids)
  }, [conversation?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // New chat: reset local UI state.
  useEffect(() => {
    if (!conversationId) {
      setSelectedId(null)
      setOpenCitation(null)
      setTab('evidence')
      setScope(search.getAll('doc'))
    }
  }, [conversationId]) // eslint-disable-line react-hooks/exhaustive-deps

  const messages: Message[] = useMemo(
    () => (conversation?.messages ?? []).filter((m) => m.id !== stream.regeneratingId || !stream.active),
    [conversation, stream.regeneratingId, stream.active],
  )
  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant')
  const selected = messages.find((m) => m.id === selectedId) ?? lastAssistant
  const showPendingUser = stream.active && !stream.regeneratingId && !messages.some((m) => m.id === stream.userMessage?.id)

  useEffect(() => {
    const el = scrollRef.current
    if (el && stickToBottom.current) el.scrollTo({ top: el.scrollHeight })
  }, [messages.length, stream.text, stream.active])

  const ask = (text: string) => {
    stickToBottom.current = true
    setSelectedId(null)
    void send({ message: text, conversation_id: conversationId ?? null, document_ids: scope })
  }

  const regenerate = (m: Message) => {
    const idx = messages.indexOf(m)
    const prior = [...messages.slice(0, idx)].reverse().find((x) => x.role === 'user')
    if (!prior || !conversationId) return
    void send({ message: prior.content, conversation_id: conversationId, document_ids: scope, regenerate_of: m.id })
  }

  const openCite = (c: Citation | OpenCitation) => {
    const oc: OpenCitation =
      'tag' in c ? { docId: c.doc_id, page: c.page_start, excerpt: c.excerpt, chunkId: c.chunk_id, source: c.source } : c
    if (!readyDocs.some((d) => d.id === oc.docId)) {
      toast.error('This document is no longer in the library.')
      return
    }
    setOpenCitation(oc)
    setTab('document')
    if (isDesktop) setPanelOpen(true)
    else setMobilePanel(true)
  }

  const deleteConversation = async () => {
    if (!conversationId) return
    await delConversation.mutateAsync(conversationId)
    toast.success('Conversation deleted')
    navigate('/chat')
  }

  const panel = (
    <EvidencePanel
      sources={stream.active ? stream.sources : (selected?.sources ?? [])}
      citations={stream.active ? [] : (selected?.citations ?? [])}
      open={openCitation}
      onOpenCitation={openCite}
      onCloseDocument={() => { setOpenCitation(null); setTab('evidence') }}
      onClose={isDesktop ? () => setPanelOpen(false) : undefined}
      tab={tab}
      onTabChange={setTab}
      loading={stream.active && stream.phase === 'retrieving'}
    />
  )

  const noDocs = docs && readyDocs.length === 0
  const empty = !conversationId && !stream.active

  const center = (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b px-3 sm:px-4">
        <h1 className="min-w-0 flex-1 truncate text-sm font-medium" title={conversation?.title}>
          {conversationId ? (conversation?.title ?? 'Conversation') : 'New conversation'}
        </h1>
        {conversationId && (
          <Button variant="ghost" size="icon" className="size-8" onClick={deleteConversation} aria-label="Delete conversation">
            <Trash2 className="size-4" />
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="size-8"
          onClick={() => (isDesktop ? setPanelOpen((o) => !o) : setMobilePanel(true))}
          aria-label={panelOpen && isDesktop ? 'Hide evidence panel' : 'Show evidence panel'}
        >
          {panelOpen && isDesktop ? <PanelRightClose className="size-4" /> : <PanelRightOpen className="size-4" />}
        </Button>
      </div>

      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget
          stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
        }}
        className="scrollbar-thin min-h-0 flex-1 overflow-y-auto"
      >
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6 sm:px-6">
          {empty && (
            <div className="flex flex-col items-center pt-[8vh] text-center">
              <div className="mb-4 grid size-12 place-items-center rounded-2xl bg-primary/12 text-primary"><Sparkles className="size-6" aria-hidden /></div>
              <h2 className="text-xl font-semibold tracking-tight">Ask your documents anything</h2>
              <p className="mt-1.5 max-w-md text-sm text-muted-foreground">
                Answers are generated on this machine from the selected PDFs. Every claim links to the page it came from.
              </p>
              {noDocs ? (
                <UploadDropzone compact className="mt-8 w-full max-w-md" />
              ) : (
                <div className="mt-8 grid w-full max-w-xl gap-2 sm:grid-cols-2">
                  {suggestions(readyDocs.filter((d) => scope.length === 0 || scope.includes(d.id)).map((d) => d.title || d.filename)).map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => ask(s)}
                      className="rounded-xl border bg-card px-3.5 py-3 text-left text-sm text-foreground/85 transition-colors hover:border-primary/40 hover:bg-accent"
                      data-testid="suggested-question"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {conversationId && convLoading && (
            <div className="space-y-4">{[0, 1].map((i) => <div key={i} className="h-16 animate-pulse rounded-xl bg-muted" />)}</div>
          )}
          {convError && (
            <EmptyState icon={AlertCircle} title="Conversation not found" description="It may have been deleted." action={<Button onClick={() => navigate('/chat')}>Start a new chat</Button>} />
          )}
          {messages.map((m) =>
            m.role === 'user' ? (
              <UserBubble key={m.id} content={m.content} />
            ) : (
              <AssistantMessage
                key={m.id}
                message={m}
                selected={selected?.id === m.id && messages.filter((x) => x.role === 'assistant').length > 1}
                onSelect={() => setSelectedId(m.id)}
                onOpenCitation={openCite}
                activeCitation={openCitation?.chunkId}
                canRegenerate={!stream.active && m.id === lastAssistant?.id}
                onRegenerate={() => regenerate(m)}
                onFeedback={(v) => feedback.mutate({ messageId: m.id, value: v })}
              />
            ),
          )}
          {showPendingUser && stream.question && <UserBubble content={stream.question} />}
          {stream.active && <StreamingMessage text={stream.text} phase={stream.phase} scopeCount={scope.length || readyDocs.length} />}
          {stream.error && (
            <Alert variant="destructive" role="alert">
              <AlertCircle className="size-4" />
              <AlertTitle>{stream.error.code === 'generation_queue_full' ? 'The model is busy' : 'Something went wrong'}</AlertTitle>
              <AlertDescription>
                <p>{stream.error.message}</p>
                <Button variant="outline" size="sm" className="mt-2" onClick={clearError}>Dismiss</Button>
              </AlertDescription>
            </Alert>
          )}
        </div>
      </div>

      <div className="shrink-0 px-3 pb-3 pt-1 sm:px-6 sm:pb-5">
        <div className="mx-auto w-full max-w-3xl">
          <Composer
            onSend={ask}
            onStop={stop}
            streaming={stream.active}
            disabled={!!noDocs}
            disabledReason="Upload and index a PDF to start asking questions"
            autoFocus={isDesktop}
            toolbar={<ScopePicker documents={docs?.items ?? []} value={scope} onChange={setScope} disabled={stream.active} />}
          />
          <p className="mt-2 text-center text-[11px] text-muted-foreground">
            Generated locally by a small open model. Verify important facts against the cited pages.
          </p>
        </div>
      </div>
    </div>
  )

  if (!isDesktop) {
    return (
      <>
        {center}
        <Sheet open={mobilePanel} onOpenChange={setMobilePanel}>
          <SheetContent side="right" className="w-full p-0 sm:max-w-lg">
            <SheetTitle className="sr-only">Evidence and documents</SheetTitle>
            {panel}
          </SheetContent>
        </Sheet>
      </>
    )
  }
  return (
    <ResizablePanelGroup orientation="horizontal" className="h-full">
      <ResizablePanel id="chat" minSize="420px" defaultSize="60%">{center}</ResizablePanel>
      {panelOpen && (
        <>
          <ResizableHandle withHandle />
          <ResizablePanel id="evidence" minSize="320px" defaultSize="40%" className="border-l">{panel}</ResizablePanel>
        </>
      )}
    </ResizablePanelGroup>
  )
}
