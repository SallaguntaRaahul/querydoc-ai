import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useRef, useState } from 'react'

import { ApiError } from '@/lib/api'
import { postSse } from '@/lib/sse'
import { keys } from '@/services/queries'
import type { ChatRequest, ConversationDetail, Message, Source } from '@/types/api'

export interface StreamState {
  active: boolean
  phase: 'idle' | 'retrieving' | 'generating' | 'finishing'
  question: string | null
  userMessage: Message | null
  text: string
  sources: Source[]
  retrievalMs: number | null
  error: ApiError | null
  regeneratingId: string | null
}

const IDLE: StreamState = {
  active: false, phase: 'idle', question: null, userMessage: null, text: '', sources: [],
  retrievalMs: null, error: null, regeneratingId: null,
}

/**
 * Streams an answer from POST /api/v1/chat/stream and keeps the TanStack Query
 * cache in sync. Returns the live stream state plus send / stop.
 */
export function useChatStream(onConversation?: (id: string) => void) {
  const qc = useQueryClient()
  const [state, setState] = useState<StreamState>(IDLE)
  const abortRef = useRef<AbortController | null>(null)

  const stop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const send = useCallback(
    async (req: ChatRequest) => {
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      setState({ ...IDLE, active: true, phase: 'retrieving', question: req.message, regeneratingId: req.regenerate_of ?? null })
      let conversationId = req.conversation_id ?? null
      let userMessage: Message | null = null
      try {
        await postSse(
          '/chat/stream',
          req,
          ({ event, data }) => {
            const d = data as Record<string, unknown>
            if (event === 'meta') {
              conversationId = d.conversation_id as string
              userMessage = d.user_message as Message
              setState((s) => ({ ...s, userMessage }))
              if (!req.conversation_id) onConversation?.(conversationId)
            } else if (event === 'retrieval') {
              setState((s) => ({ ...s, phase: 'generating', sources: d.sources as Source[], retrievalMs: d.latency_ms as number }))
            } else if (event === 'token') {
              setState((s) => ({ ...s, text: s.text + (d.text as string) }))
            } else if (event === 'done') {
              const message = d.message as Message
              if (conversationId) {
                // Write the final, verified message into the cached conversation, then refresh.
                qc.setQueryData<ConversationDetail>(keys.conversation(conversationId), (old) => {
                  if (!old) return old
                  const msgs = old.messages.filter((m) => m.id !== req.regenerate_of && m.id !== message.id)
                  const needsUser = userMessage && !msgs.some((m) => m.id === userMessage?.id)
                  return { ...old, messages: [...msgs, ...(needsUser && userMessage ? [userMessage] : []), message] }
                })
              }
              setState((s) => ({ ...s, phase: 'finishing' }))
            } else if (event === 'error') {
              setState((s) => ({ ...s, error: new ApiError(Number(d.status ?? 500), String(d.code), String(d.message)) }))
            }
          },
          controller.signal,
        )
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          setState((s) => ({ ...s, error: e instanceof ApiError ? e : new ApiError(0, 'stream_error', String(e)) }))
        }
      } finally {
        if (conversationId) {
          await qc.invalidateQueries({ queryKey: keys.conversation(conversationId) })
        }
        qc.invalidateQueries({ queryKey: keys.conversations })
        qc.invalidateQueries({ queryKey: keys.overview })
        if (abortRef.current === controller) abortRef.current = null
        setState((s) => (s.error ? { ...s, active: false, phase: 'idle' } : IDLE))
      }
    },
    [qc, onConversation],
  )

  const clearError = useCallback(() => setState(IDLE), [])
  return { state, send, stop, clearError }
}
