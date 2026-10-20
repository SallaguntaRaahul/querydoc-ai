import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { vi } from 'vitest'

import { makeQueryClient, Providers } from '@/app/providers'

type Handler = (url: string, init?: RequestInit) => unknown | Promise<unknown>

/** Route-based fetch mock. Handlers return a JSON body, or a Response for full control. */
export function mockFetch(routes: Record<string, Handler>) {
  const calls: { url: string; init?: RequestInit }[] = []
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    calls.push({ url, init })
    const method = (init?.method ?? 'GET').toUpperCase()
    const key = Object.keys(routes).find((k) => {
      const [m, path] = k.includes(' ') ? k.split(' ') : ['GET', k]
      return m === method && url.split('?')[0].endsWith(path)
    })
    if (!key) return new Response(JSON.stringify({ error: { code: 'not_found', message: `no mock for ${method} ${url}` } }), { status: 404 })
    const body = await routes[key](url, init)
    if (body instanceof Response) return body
    if (body === undefined) return new Response(null, { status: 204 })
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fn)
  return { fn, calls }
}

export function renderWithProviders(ui: ReactElement, { route = '/' }: { route?: string } = {}) {
  const client = makeQueryClient()
  client.setDefaultOptions({ queries: { retry: false, staleTime: 0 } })
  const router = createMemoryRouter([{ path: '*', element: ui }], { initialEntries: [route] })
  return { client, ...render(<Providers client={client}><RouterProvider router={router} /></Providers>) }
}

export const sampleDoc = {
  id: '0123456789abcdef', filename: 'NIST.SP.800-63b.pdf', title: 'Digital Identity Guidelines', size_bytes: 1_480_377,
  page_count: 80, chunk_count: 260, status: 'ready' as const, stage: 'ready', progress: 1, error: null, chunking: {},
  timings_ms: {}, embedding_stats: {}, scanned_pages: [], created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
}

export const sampleSettings = {
  settings: {
    embedding_model: 'sentence-transformers/all-MiniLM-L6-v2', llm_model: 'Qwen/Qwen2.5-1.5B-Instruct', llm_device: 'auto',
    reranker_device: 'auto', chunk_size: 1000, chunk_overlap: 200, top_k: 5, fetch_k: 30, use_hybrid: true, use_rerank: true,
    rerank_k: 20, max_new_tokens: 256, temperature: 0, theme: 'dark', performance_mode: 'balanced', enable_ocr: false,
  },
  options: {
    embedding_models: ['sentence-transformers/all-MiniLM-L6-v2'],
    llm_models: [{ id: 'Qwen/Qwen2.5-1.5B-Instruct', label: 'Qwen2.5 1.5B Instruct', params: '1.5B', approx_memory_gb: 3.1, license: 'Apache-2.0', note: 'Default' }],
    devices: ['auto', 'cpu', 'mps'], embedding_model_locked: true, embedding_model_locked_reason: 'Delete all documents first.', ocr_available: true,
  },
  restart_required: [],
}
