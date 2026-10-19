import { describe, expect, it } from 'vitest'

import { escapeHtml, markOccurrences, normalizeText, passageItemMatcher } from '@/features/viewer/pdf-setup'
import { formatBytes, formatMs, formatPct, pagesLabel, relativeTime } from '@/lib/format'
import { parseSseChunk } from '@/lib/sse'

describe('parseSseChunk', () => {
  it('parses complete events and keeps the partial tail', () => {
    const buf = 'event: meta\ndata: {"a":1}\n\nevent: token\ndata: {"text":"Hel"}\n\nevent: tok'
    const { events, rest } = parseSseChunk(buf)
    expect(events).toEqual([
      { event: 'meta', data: { a: 1 } },
      { event: 'token', data: { text: 'Hel' } },
    ])
    expect(rest).toBe('event: tok')
  })

  it('ignores keep-alive comments and handles CRLF and multi-line data', () => {
    const { events } = parseSseChunk(': keep-alive\r\n\r\nevent: done\r\ndata: line1\r\ndata: line2\r\n\r\n')
    expect(events).toEqual([{ event: 'done', data: 'line1\nline2' }])
  })

  it('defaults to the message event type', () => {
    expect(parseSseChunk('data: 42\n\n').events).toEqual([{ event: 'message', data: 42 }])
  })
})

describe('format helpers', () => {
  it('formats bytes, durations and percentages', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(1536)).toBe('1.5 KB')
    expect(formatBytes(1_480_377)).toBe('1.4 MB')
    expect(formatMs(0.5)).toBe('0.50 ms')
    expect(formatMs(128.4)).toBe('128 ms')
    expect(formatMs(1911)).toBe('1.91 s')
    expect(formatMs(null)).toBe('—')
    expect(formatPct(43.84)).toBe('+43.8%')
    expect(formatPct(-0.8)).toBe('-0.8%')
    expect(pagesLabel(3, 3)).toBe('p. 3')
    expect(pagesLabel(3, 4)).toBe('pp. 3–4')
  })

  it('renders relative times', () => {
    const now = Date.parse('2026-10-19T12:00:00Z')
    expect(relativeTime('2026-10-19T11:59:50Z', now)).toBe('just now')
    expect(relativeTime('2026-10-19T11:30:00Z', now)).toBe('30m ago')
    expect(relativeTime('2026-10-19T09:00:00Z', now)).toBe('3h ago')
  })
})

describe('PDF text helpers', () => {
  it('escapes HTML so PDF text cannot inject markup into the text layer', () => {
    expect(escapeHtml('<img src=x onerror=alert(1)>')).toBe('&lt;img src=x onerror=alert(1)&gt;')
    expect(markOccurrences('<b>salt</b> and Salt', 'salt')).toBe(
      '&lt;b&gt;<mark class="pdf-highlight">salt</mark>&lt;/b&gt; and <mark class="pdf-highlight">Salt</mark>',
    )
  })

  it('normalizes typography differences', () => {
    expect(normalizeText('  Users’  “pass”—\nword  ')).toBe(`users' "pass"- word`)
  })

  it('only highlights when the passage is really on the page', () => {
    const page = ['The salt SHALL be at least 32 bits in length and be chosen', 'arbitrarily so as to minimize salt value collisions.', 'Unrelated footer text 25']
    const passage = 'The salt SHALL be at least 32 bits in length and be chosen arbitrarily so as to minimize salt value collisions.'
    const m = passageItemMatcher(page, passage)
    expect(m.found).toBe(true)
    expect(m.matches(page[0])).toBe(true)
    expect(m.matches(page[1])).toBe(true)
    expect(m.matches(page[2])).toBe(false)

    const missing = passageItemMatcher(page, 'Look-up secrets SHALL have at least 20 bits of entropy across all pages here.')
    expect(missing.found).toBe(false)
    expect(missing.matches(page[0])).toBe(false)
  })
})
