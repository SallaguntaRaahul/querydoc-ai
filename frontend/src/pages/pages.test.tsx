import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { axe } from 'vitest-axe'

import { ThemeToggle } from '@/components/common'
import DashboardPage from '@/pages/dashboard-page'
import LibraryPage from '@/pages/library-page'
import SettingsPage from '@/pages/settings-page'
import { mockFetch, renderWithProviders, sampleDoc, sampleSettings } from '@/test/utils'

vi.mock('@/features/viewer/pdf-thumbnail', () => ({ default: () => <div data-testid="thumb" /> }))

const health = {
  status: 'ok', version: '1.0.0', documents: 1, index_vectors: 260, ingestion_queue: 0,
  models: {
    embedder: { model: 'all-MiniLM-L6-v2', device: 'cpu', loaded: true },
    reranker: { model: 'ms-marco', device: 'auto', loaded: false },
    llm: { model: 'Qwen/Qwen2.5-1.5B-Instruct', device: 'auto', loaded: true, error: null },
  },
}

beforeEach(() => {
  localStorage.clear()
  document.documentElement.className = ''
})

describe('Dashboard', () => {
  it('shows real counts from the API and model readiness, with no a11y violations', async () => {
    mockFetch({
      '/documents': () => ({ items: [sampleDoc, { ...sampleDoc, id: 'fedcba9876543210', filename: 'b.pdf', status: 'processing', progress: 0.4, page_count: 0, chunk_count: 0 }], total: 2 }),
      '/conversations': () => [],
      '/health': () => health,
    })
    const { container } = renderWithProviders(<DashboardPage />)
    expect(await screen.findByText('NIST.SP.800-63b.pdf')).toBeInTheDocument()
    expect(screen.getByText('80')).toBeInTheDocument() // indexed pages come from ready docs only
    expect(screen.getByText('1 processing')).toBeInTheDocument()
    expect(screen.getByText('Loads on first use')).toBeInTheDocument() // reranker not loaded yet
    expect(await axe(container)).toHaveNoViolations()
  })

  it('reports an unreachable backend', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('fetch failed')))
    renderWithProviders(<DashboardPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/Cannot reach the QueryDoc AI backend/)
  })
})

describe('Library', () => {
  it('filters documents and deletes one through the API after confirmation', async () => {
    let docs = [sampleDoc, { ...sampleDoc, id: 'fedcba9876543210', filename: 'other-report.pdf', title: 'Other' }]
    const { calls } = mockFetch({
      '/documents': () => ({ items: docs, total: docs.length }),
      'DELETE /documents/0123456789abcdef': () => { docs = docs.filter((d) => d.id !== sampleDoc.id); return undefined },
    })
    renderWithProviders(<LibraryPage />)
    expect(await screen.findAllByTestId('document-card')).toHaveLength(2)

    await userEvent.type(screen.getByLabelText('Search documents'), 'other')
    expect(screen.getAllByTestId('document-card')).toHaveLength(1)
    await userEvent.clear(screen.getByLabelText('Search documents'))

    const card = screen.getAllByTestId('document-card').find((c) => within(c).queryByText(sampleDoc.filename))!
    await userEvent.click(within(card).getByRole('button', { name: `Actions for ${sampleDoc.filename}` }))
    await userEvent.click(await screen.findByRole('menuitem', { name: /Delete/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Delete document' }))
    await waitFor(() => expect(calls.some((c) => c.init?.method === 'DELETE' && c.url.endsWith(`/documents/${sampleDoc.id}`))).toBe(true))
    await waitFor(() => expect(screen.getAllByTestId('document-card')).toHaveLength(1))
  })

  it('shows the empty state', async () => {
    mockFetch({ '/documents': () => ({ items: [], total: 0 }) })
    renderWithProviders(<LibraryPage />)
    expect(await screen.findByText('Your library is empty')).toBeInTheDocument()
  })
})

describe('Settings', () => {
  it('blocks invalid values client-side and saves a valid change via PUT', async () => {
    const { calls } = mockFetch({
      '/settings': () => sampleSettings,
      'PUT /settings': (_u, init) => ({ ...sampleSettings, settings: { ...sampleSettings.settings, ...JSON.parse(String(init?.body)) } }),
    })
    renderWithProviders(<SettingsPage />)
    const overlap = await screen.findByLabelText('Chunk overlap (characters)')
    const save = screen.getByTestId('save-settings')
    expect(save).toBeDisabled()
    expect(screen.getByText(/Delete all documents first/)).toBeInTheDocument() // embedding model locked

    await userEvent.clear(overlap)
    await userEvent.type(overlap, '900')
    expect(await screen.findByText('Overlap must be at most half the chunk size')).toBeInTheDocument()
    expect(save).toBeDisabled()

    await userEvent.clear(overlap)
    await userEvent.type(overlap, '150')
    await waitFor(() => expect(save).toBeEnabled())
    await userEvent.click(save)
    await waitFor(() => expect(calls.some((c) => c.init?.method === 'PUT')).toBe(true))
    const body = JSON.parse(String(calls.find((c) => c.init?.method === 'PUT')!.init!.body))
    expect(body.chunk_overlap).toBe(150)
  })
})

describe('Theme', () => {
  it('defaults to dark and switches to light, persisting the choice', async () => {
    renderWithProviders(<ThemeToggle />)
    await waitFor(() => expect(document.documentElement).toHaveClass('dark'))
    await userEvent.click(screen.getByRole('button', { name: 'Change theme' }))
    await userEvent.click(await screen.findByRole('menuitemradio', { name: /Light/ }))
    expect(document.documentElement).not.toHaveClass('dark')
    expect(localStorage.getItem('querydoc.theme')).toBe('light')
  })
})
