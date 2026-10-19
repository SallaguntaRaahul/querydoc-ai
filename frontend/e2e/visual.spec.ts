import fs from 'node:fs'
import path from 'node:path'

import { expect, type Page, test } from '@playwright/test'

/**
 * Visual QA: genuine screenshots of the running application at desktop, tablet
 * and mobile sizes in dark and light themes, plus empty / loading / error /
 * long-title / large-collection / long-answer states. Runs after app.spec.ts
 * (same server), so real documents and conversations exist.
 *
 * Screenshots in docs/images/ui/ come from real data. Screenshots in
 * docs/images/ui/states/ that need conditions hard to produce on demand
 * (server down, slow network, a very long multi-citation answer) intercept the
 * network and are labelled "layout fixture" in their filename.
 */

const ROOT = path.resolve(import.meta.dirname, '../..')
const OUT = path.join(ROOT, 'docs/images/ui')
const STATES = path.join(OUT, 'states')
const FIXTURES = path.join(import.meta.dirname, 'fixtures')
fs.mkdirSync(STATES, { recursive: true })

test.describe.configure({ mode: 'serial' })

const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  tablet: { width: 834, height: 1112 },
  mobile: { width: 390, height: 844 },
} as const

async function setTheme(page: Page, theme: 'dark' | 'light') {
  await page.addInitScript((t) => localStorage.setItem('querydoc.theme', t), theme)
}

async function shot(page: Page, name: string, dir = OUT) {
  await page.waitForLoadState('networkidle').catch(() => {})
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(dir, `${name}.png`) })
}

/** No horizontal overflow and no clipped text in the document scroll area. */
async function assertNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow, 'page should not scroll horizontally').toBeLessThanOrEqual(1)
}

test('seed a larger collection including a very long filename', async ({ request }) => {
  const files = fs.readdirSync(FIXTURES).filter((f) => f.endsWith('.pdf') && f !== 'not-a-pdf.pdf')
  const multipart: Record<string, { name: string; mimeType: string; buffer: Buffer }> = {}
  const res = await request.post('/api/v1/documents/upload', {
    multipart: Object.assign(multipart, {
      files: { name: files[0], mimeType: 'application/pdf', buffer: fs.readFileSync(path.join(FIXTURES, files[0])) },
    }),
  })
  expect(res.status()).toBe(202)
  for (const f of files.slice(1)) {
    const r = await request.post('/api/v1/documents/upload', {
      multipart: { files: { name: f, mimeType: 'application/pdf', buffer: fs.readFileSync(path.join(FIXTURES, f)) } },
    })
    expect([202, 409]).toContain(r.status())
  }
  await expect.poll(async () => {
    const d = await (await request.get('/api/v1/documents')).json()
    return d.items.every((x: { status: string }) => x.status === 'ready' || x.status === 'failed')
  }, { timeout: 180_000 }).toBe(true)
  // A real, cited answer about a document that is still in the library (for citation screenshots).
  const docs = await (await request.get('/api/v1/documents')).json()
  const big = docs.items.find((d: { page_count: number }) => d.page_count >= 100)
  const chat = await request.post('/api/v1/chat', { data: { message: 'How many steps are in the Risk Management Framework and what are they?', document_ids: [big.id] }, timeout: 180_000 })
  expect(chat.status()).toBe(200)
})

for (const theme of ['dark', 'light'] as const) {
  for (const [vpName, vp] of Object.entries(VIEWPORTS)) {
    test(`pages render cleanly — ${vpName} ${theme}`, async ({ page }) => {
      await setTheme(page, theme)
      await page.setViewportSize(vp)
      await page.goto('/')
      await expect(page.getByRole('heading', { name: /Good (morning|afternoon|evening)/ })).toBeVisible()
      await assertNoHorizontalOverflow(page)
      await shot(page, `${vpName}-${theme}-overview`)

      await page.goto('/library')
      await expect(page.getByTestId('document-card').first()).toBeVisible()
      await assertNoHorizontalOverflow(page)
      await shot(page, `${vpName}-${theme}-library`)

      const convs = await (await page.request.get('/api/v1/conversations')).json()
      let withAnswer: { id: string } | undefined
      const live = new Set((await (await page.request.get('/api/v1/documents')).json()).items.map((d: { id: string }) => d.id))
      for (const c of convs) {
        const detail = await (await page.request.get(`/api/v1/conversations/${c.id}`)).json()
        const cited = detail.messages.flatMap((m: { citations: { doc_id: string }[] }) => m.citations)
        if (cited.length && cited.every((x: { doc_id: string }) => live.has(x.doc_id))) { withAnswer = c; break }
      }
      await page.goto(withAnswer ? `/chat/${withAnswer.id}` : '/chat')
      await expect(page.getByTestId('chat-input')).toBeVisible()
      await assertNoHorizontalOverflow(page)
      await shot(page, `${vpName}-${theme}-chat`)

      if (vpName === 'desktop' && withAnswer) {
        const pill = page.getByTestId('source-pill').first()
        if (await pill.count()) {
          await pill.click()
          await expect(page.getByTestId('evidence-panel').locator('canvas').first()).toBeVisible({ timeout: 30_000 })
          await page.waitForTimeout(800)
          await shot(page, `${vpName}-${theme}-chat-citation`)
        }
      }

      await page.goto('/analytics')
      await expect(page.getByRole('heading', { name: 'Live telemetry' })).toBeVisible()
      await assertNoHorizontalOverflow(page)
      await shot(page, `${vpName}-${theme}-analytics`)

      await page.goto('/settings')
      await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
      await assertNoHorizontalOverflow(page)
      await shot(page, `${vpName}-${theme}-settings`)
    })
  }
}

test('viewer side by side with a search highlight (desktop dark)', async ({ page }) => {
  await setTheme(page, 'dark')
  const docs = await (await page.request.get('/api/v1/documents')).json()
  const big = docs.items.find((d: { page_count: number }) => d.page_count >= 100)
  await page.goto(`/documents/${big.id}?page=27`)
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
  await page.getByLabel('Search in PDF').fill('authorizing official')
  await page.getByLabel('Search in PDF').press('Enter')
  await expect(page.getByText(/on \d+ pages/)).toBeVisible({ timeout: 60_000 })
  await page.waitForTimeout(800)
  await shot(page, 'desktop-dark-viewer')
})

test('long titles truncate instead of overflowing', async ({ page }) => {
  await page.goto('/library')
  await page.getByLabel('Search documents').fill('Quarterly-operations')
  const longCard = page.getByTestId('document-card').first()
  await expect(longCard).toBeVisible()
  const box = await longCard.boundingBox()
  const heading = await longCard.getByRole('heading').boundingBox()
  expect(heading!.width).toBeLessThanOrEqual(box!.width)
  await assertNoHorizontalOverflow(page)
  await shot(page, 'long-title-library', STATES)
})

test('empty, loading and error states', async ({ page }) => {
  await page.route('**/api/v1/documents', (r) => r.fulfill({ json: { items: [], total: 0 } }))
  await page.goto('/library')
  await expect(page.getByText('Your library is empty')).toBeVisible()
  await shot(page, 'empty-library-layout-fixture', STATES)
  await page.unroute('**/api/v1/documents')

  await page.route('**/api/v1/documents', async (r) => {
    await new Promise((res) => setTimeout(res, 2500))
    await r.continue().catch(() => {})
  })
  await page.goto('/library')
  await page.waitForTimeout(500)
  await page.screenshot({ path: path.join(STATES, 'loading-library-layout-fixture.png') })
  await expect(page.getByTestId('document-card').first()).toBeVisible({ timeout: 10_000 })
  await page.unroute('**/api/v1/documents')

  await page.route('**/api/v1/**', (r) => r.abort())
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText(/Cannot reach/)
  await shot(page, 'backend-offline-layout-fixture', STATES)
  await page.unroute('**/api/v1/**')
})

test('long answer with many citations stays readable (layout fixture)', async ({ page }) => {
  const docs = await (await page.request.get('/api/v1/documents')).json()
  const doc = docs.items.find((d: { status: string }) => d.status === 'ready')
  const citations = Array.from({ length: 8 }, (_, i) => ({
    tag: `S${i + 1}`, chunk_id: `${doc.id}-${String(i).padStart(5, '0')}`, doc_id: doc.id, source: doc.filename,
    page_start: i + 1, page_end: i + 1, excerpt: 'Layout fixture excerpt used to check wrapping of long supporting passages in tooltips and pills.',
    retrieval_score: 9 - i, support: 0.9, method: i % 2 ? 'attributed' : 'model',
  }))
  const paragraph = (n: number) => `Paragraph ${n} of a deliberately long answer used only to check layout. ${'It wraps across several lines to test reading width and spacing. '.repeat(4)}[S${n}]`
  const conversation = {
    id: 'f'.repeat(32), title: 'Layout fixture: long answer with many citations', document_ids: [], created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    messages: [
      { id: 'u1', role: 'user', content: 'Layout fixture question', status: null, mode: null, document_ids: [], citations: [], sources: [], notes: [], timings_ms: {}, feedback: null, created_at: new Date().toISOString() },
      { id: 'a1', role: 'assistant', content: Array.from({ length: 8 }, (_, i) => paragraph(i + 1)).join('\n\n'), status: 'partially_verified', mode: 'generated', document_ids: [], citations, sources: [], notes: ['Layout fixture — not a real answer.'], timings_ms: { total: 1234, retrieval: 80 }, feedback: null, created_at: new Date().toISOString() },
    ],
  }
  await page.route(`**/api/v1/conversations/${conversation.id}`, (r) => r.fulfill({ json: conversation }))
  for (const [name, vp] of [['desktop', VIEWPORTS.desktop], ['mobile', VIEWPORTS.mobile]] as const) {
    await page.setViewportSize(vp)
    await page.goto(`/chat/${conversation.id}`)
    await expect(page.getByTestId('citation-chip')).toHaveCount(8)
    await assertNoHorizontalOverflow(page)
    await shot(page, `long-answer-${name}-layout-fixture`, STATES)
  }
})

test('keyboard focus is visible and reduced motion is respected', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  const outline = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement
    const s = getComputedStyle(el)
    return { tag: el.tagName, outline: s.outlineStyle, width: s.outlineWidth, shadow: s.boxShadow }
  })
  expect(outline.outline !== 'none' || outline.shadow !== 'none').toBe(true)
  const duration = await page.evaluate(() => getComputedStyle(document.body).transitionDuration)
  expect(['0s', '1e-05s', '0.00001s']).toContain(duration)
  await shot(page, 'focus-visible', STATES)
})
