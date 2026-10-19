import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'

import { pdfjs } from 'react-pdf'

// PDF.js parses and renders in a Web Worker so large PDFs never block the UI thread.
pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()

export const fileUrl = (documentId: string) => `/api/v1/documents/${documentId}/file`

/** Lower-case, collapse whitespace, unify quotes/dashes, drop soft hyphens. */
export function normalizeText(s: string): string {
  return s
    .normalize('NFKC')
    .replace(/[­​]/g, '')
    .replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/[–—]/g, '-')
    .replace(/…/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()
}

export function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** Wrap case-insensitive occurrences of ``query`` in highlight marks. */
export function markOccurrences(str: string, query: string): string {
  if (!query) return escapeHtml(str)
  const q = query.toLowerCase()
  const lower = str.toLowerCase()
  let out = ''
  let i = 0
  for (;;) {
    const j = lower.indexOf(q, i)
    if (j === -1) break
    out += escapeHtml(str.slice(i, j)) + `<mark class="pdf-highlight">${escapeHtml(str.slice(j, j + q.length))}</mark>`
    i = j + q.length
  }
  return out + escapeHtml(str.slice(i))
}

/**
 * Decide which text-layer items belong to a verified passage. A line is
 * highlighted only if its normalised text (≥ 8 chars) occurs inside the
 * normalised passage AND the page as a whole contains a long prefix of the
 * passage — so highlights always sit on real text, never guessed positions.
 */
export function passageItemMatcher(pageItems: string[], passage: string): { found: boolean; matches: (s: string) => boolean } {
  const p = normalizeText(passage)
  if (p.length < 12) return { found: false, matches: () => false }
  const page = normalizeText(pageItems.join(' '))
  const probe = p.slice(0, Math.min(48, p.length))
  const found = page.includes(probe) || page.includes(p.slice(-Math.min(48, p.length)))
  return {
    found,
    matches: (s: string) => {
      if (!found) return false
      const t = normalizeText(s)
      if (t.length < 8) return false
      if (p.includes(t)) return true
      // Lines that start or end inside the passage (the passage begins/ends mid-line).
      return t.length >= 24 && (p.includes(t.slice(0, 20)) || p.includes(t.slice(-20)))
    },
  }
}
