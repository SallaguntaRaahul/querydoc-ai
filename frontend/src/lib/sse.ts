import { API_BASE, ApiError } from '@/lib/api'

export interface SseEvent {
  event: string
  data: unknown
}

/** Parse a text/event-stream body into events. Exported for unit tests. */
export function parseSseChunk(buffer: string): { events: SseEvent[]; rest: string } {
  const events: SseEvent[] = []
  const blocks = buffer.split(/\r?\n\r?\n/)
  const rest = blocks.pop() ?? ''
  for (const block of blocks) {
    let event = 'message'
    const data: string[] = []
    for (const line of block.split(/\r?\n/)) {
      if (!line || line.startsWith(':')) continue // comment / keep-alive
      const idx = line.indexOf(':')
      const field = idx === -1 ? line : line.slice(0, idx)
      const value = idx === -1 ? '' : line.slice(idx + 1).replace(/^ /, '')
      if (field === 'event') event = value
      else if (field === 'data') data.push(value)
    }
    if (data.length) {
      const raw = data.join('\n')
      let parsed: unknown = raw
      try {
        parsed = JSON.parse(raw)
      } catch {
        /* plain-text data */
      }
      events.push({ event, data: parsed })
    }
  }
  return { events, rest }
}

/**
 * POST a JSON body and consume a Server-Sent-Events response
 * (EventSource cannot POST). Aborting the signal closes the connection,
 * which the backend detects and uses to stop generation.
 */
export async function postSse(path: string, body: unknown, onEvent: (e: SseEvent) => void, signal?: AbortSignal) {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(0, 'network_error', 'Cannot reach the QueryDoc AI server.')
  }
  if (!res.ok || !res.body) {
    let code = 'http_error'
    let message = `Request failed (${res.status})`
    try {
      const j = await res.json()
      code = j.error?.code ?? code
      message = j.error?.message ?? message
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, code, message)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const { events, rest } = parseSseChunk(buffer)
    buffer = rest
    events.forEach(onEvent)
  }
  if (buffer.trim()) parseSseChunk(buffer + '\n\n').events.forEach(onEvent)
}
