import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { axe } from 'vitest-axe'

import { TooltipProvider } from '@/components/ui/tooltip'
import { AssistantMessage, linkifyCitations } from '@/features/chat/message'
import { validateFiles } from '@/features/documents/upload-dropzone'
import { settingsSchema } from '@/features/settings/schema'
import { sampleSettings } from '@/test/utils'
import type { Message } from '@/types/api'

const pdf = (name: string, size: number, type = 'application/pdf') => new File([new Uint8Array(size)], name, { type })

describe('validateFiles', () => {
  it('accepts PDFs and rejects wrong type, empty and oversized files', () => {
    const { ok, rejected } = validateFiles([
      pdf('a.pdf', 10),
      pdf('notes.txt', 10, 'text/plain'),
      pdf('empty.pdf', 0),
      pdf('huge.pdf', 2 * 1024 * 1024),
    ], 1)
    expect(ok.map((f) => f.name)).toEqual(['a.pdf'])
    expect(rejected.map((r) => r.reason)).toEqual(['Not a PDF file', 'File is empty', expect.stringContaining('Larger than 1 MB')])
  })

  it('caps the number of files per upload', () => {
    const files = Array.from({ length: 22 }, (_, i) => pdf(`f${i}.pdf`, 5))
    const { ok, rejected } = validateFiles(files)
    expect(ok).toHaveLength(20)
    expect(rejected.at(-1)?.reason).toMatch(/At most 20/)
  })
})

describe('settingsSchema', () => {
  const base = sampleSettings.settings
  it('accepts the defaults', () => {
    expect(settingsSchema.safeParse(base).success).toBe(true)
  })
  it('rejects overlap above half the chunk size', () => {
    const r = settingsSchema.safeParse({ ...base, chunk_size: 400, chunk_overlap: 300 })
    expect(r.success).toBe(false)
    expect(r.error?.issues[0].path).toEqual(['chunk_overlap'])
  })
  it('rejects inconsistent retrieval sizes and out-of-range values', () => {
    expect(settingsSchema.safeParse({ ...base, top_k: 8, rerank_k: 5 }).success).toBe(false)
    expect(settingsSchema.safeParse({ ...base, top_k: 8, fetch_k: 5 }).success).toBe(false)
    expect(settingsSchema.safeParse({ ...base, max_new_tokens: 5 }).success).toBe(false)
    expect(settingsSchema.safeParse({ ...base, temperature: 2 }).success).toBe(false)
    expect(settingsSchema.safeParse({ ...base, llm_device: 'tpu' }).success).toBe(false)
  })
})

describe('citations in answers', () => {
  it('turns valid citation markers into links and drops unknown ones', () => {
    const valid = new Set(['S1', 'S2'])
    expect(linkifyCitations('Eight characters [S1]. Salt [S2, S9]. Bad [S7]. [Source S2]', valid)).toBe(
      'Eight characters [S1](#cite-S1). Salt [S2](#cite-S2). Bad . [S2](#cite-S2)',
    )
  })

  const message: Message = {
    id: 'm1', role: 'assistant', content: 'Passwords need at least 8 characters [S1].', status: 'verified', mode: 'generated',
    document_ids: [], feedback: null, created_at: new Date().toISOString(), notes: [], sources: [], timings_ms: { total: 1900, retrieval: 80 },
    citations: [{ tag: 'S1', chunk_id: 'abc-00001', doc_id: '0123456789abcdef', source: 'NIST.SP.800-63b.pdf', page_start: 25, page_end: 25,
      excerpt: 'Memorized secrets SHALL be at least 8 characters in length.', retrieval_score: 9.1, support: 1, method: 'model' }],
  }

  it('renders the status, inline chip and source pill; clicking opens the cited page', async () => {
    const onOpen = vi.fn()
    const { container } = render(<TooltipProvider><AssistantMessage message={message} onOpenCitation={onOpen} /></TooltipProvider>)
    expect(screen.getByText('Verified citations')).toBeInTheDocument()
    const chip = screen.getByTestId('citation-chip')
    expect(chip).toHaveAccessibleName(/Citation S1: NIST.SP.800-63b.pdf, p. 25/)
    await userEvent.click(chip)
    expect(onOpen).toHaveBeenCalledWith(message.citations[0])
    fireEvent.click(screen.getByTestId('source-pill'))
    expect(onOpen).toHaveBeenCalledTimes(2)
    expect(await axe(container)).toHaveNoViolations()
  })

  it('copies the answer with its sources', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<TooltipProvider><AssistantMessage message={message} onOpenCitation={() => {}} /></TooltipProvider>)
    await userEvent.click(screen.getByRole('button', { name: 'Copy answer' }))
    const copied = writeText.mock.calls[0][0] as string
    expect(copied.split('\n')[0]).not.toContain('[S1]') // markers stripped from the prose
    expect(copied).toContain('Sources:\n[S1] NIST.SP.800-63b.pdf, p. 25')
  })
})
