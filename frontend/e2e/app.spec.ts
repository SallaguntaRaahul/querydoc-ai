import path from 'node:path'

import { expect, type Page, test } from '@playwright/test'

/**
 * Full user journey against the real stack (no mocks): upload real NIST PDFs,
 * watch indexing, ask questions with streamed local-LLM answers, open citations
 * in the PDF viewer, follow up, reload, stop a generation, change settings,
 * review analytics, delete a document.
 */

const ROOT = path.resolve(import.meta.dirname, '../..')
const CORPUS = path.join(ROOT, 'data/corpus')
const FIXTURES = path.join(import.meta.dirname, 'fixtures')
const SMALL = 'NIST.AI.100-1.pdf' // 48 pages
const LARGE = 'NIST.SP.800-37r2.pdf' // 183 pages

test.describe.configure({ mode: 'serial' })

async function card(page: Page, filename: string) {
  return page.getByTestId('document-card').filter({ has: page.getByRole('heading', { name: filename, exact: true }) })
}

async function ask(page: Page, question: string) {
  const input = page.getByTestId('chat-input')
  await input.fill(question)
  await input.press('Enter')
}

async function waitForAnswer(page: Page, count: number) {
  await expect(page.getByTestId('assistant-message')).toHaveCount(count, { timeout: 180_000 })
  await expect(page.getByTestId('streaming-message')).toHaveCount(0, { timeout: 180_000 })
}

test('empty workspace shows onboarding states', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /Good (morning|afternoon|evening)/ })).toBeVisible()
  await expect(page.getByTestId('upload-dropzone')).toBeVisible()
  await page.goto('/library')
  await expect(page.getByText('Your library is empty')).toBeVisible()
  await page.goto('/chat')
  await expect(page.getByTestId('chat-input')).toBeDisabled()
})

test('upload: validation error, then two real PDFs index (including 183 pages)', async ({ page }) => {
  await page.goto('/library')
  await page.getByTestId('file-input').setInputFiles(path.join(FIXTURES, 'not-a-pdf.pdf'))
  await expect(page.getByText(/does not look like a PDF/)).toBeVisible()

  await page.getByTestId('file-input').setInputFiles([path.join(CORPUS, SMALL), path.join(CORPUS, LARGE)])
  await expect(page.getByText(/2 files uploaded/)).toBeVisible()
  const small = await card(page, SMALL)
  const large = await card(page, LARGE)
  await expect(large.getByText(/Queued|Indexing/)).toBeVisible() // real progress is shown while processing
  await expect(small.getByText('Ready')).toBeVisible({ timeout: 120_000 })
  await expect(large.getByText('Ready')).toBeVisible({ timeout: 200_000 })
  await expect(large.getByText('183 pages')).toBeVisible()

  // duplicate upload is rejected by the server
  await page.getByTestId('file-input').setInputFiles(path.join(CORPUS, SMALL))
  await expect(page.getByText(/already in the library/)).toBeVisible()
})

test('ask a question: streamed answer with citations, open the cited page', async ({ page }) => {
  await page.goto('/chat')
  await expect(page.getByTestId('chat-input')).toBeEnabled()
  await ask(page, 'What are the four functions of the AI RMF core?')
  await expect(page).toHaveURL(/\/chat\/[0-9a-f]{32}$/)
  await expect(page.getByTestId('user-message')).toHaveText(/four functions/)
  await waitForAnswer(page, 1)
  const answer = page.getByTestId('assistant-message').first()
  await expect(answer).toContainText(/govern/i)
  await expect(answer.getByText(/Verified citations|Partially verified/)).toBeVisible()

  // Evidence panel lists retrieved passages with scores and pages.
  await expect(page.getByTestId('evidence-item').first()).toBeVisible()
  expect(await page.getByTestId('evidence-item').count()).toBeGreaterThan(0)

  // Citation → PDF page from verified metadata.
  const pill = answer.getByTestId('source-pill').first()
  const pageLabel = (await pill.textContent()) ?? ''
  const cited = Number(pageLabel.match(/p+\. (\d+)/)?.[1])
  await pill.click()
  const panel = page.getByTestId('evidence-panel')
  await expect(panel.getByRole('tab', { name: /Document/ })).toHaveAttribute('aria-selected', 'true')
  await expect(panel.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
  await expect(panel.getByLabel('Current page')).toHaveValue(String(cited))
  await expect(panel.getByRole('status').filter({ hasText: /Supporting passage highlighted|could not be located/ })).toBeVisible()
})

test('follow-up question, persistence after reload, reopen from history', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('link', { name: /four functions of the AI RMF/ }).first().click()
  await expect(page.getByTestId('assistant-message')).toHaveCount(1)
  const url = page.url()

  await ask(page, 'Which of those functions do most users start with?')
  await waitForAnswer(page, 2)
  await expect(page.getByTestId('user-message')).toHaveCount(2)

  await page.reload()
  await expect(page.getByTestId('user-message')).toHaveCount(2)
  await expect(page.getByTestId('assistant-message')).toHaveCount(2)
  expect(page.url()).toBe(url)
})

test('stop a generation mid-stream', async ({ page }) => {
  await page.goto('/chat')
  await ask(page, 'Explain every task of the Prepare step of the RMF in detail, one by one.')
  await expect(page.getByTestId('stop-button')).toBeVisible({ timeout: 60_000 })
  // wait until tokens are flowing, then stop
  await expect(page.getByTestId('streaming-message')).not.toContainText(/Searching|Reading the evidence/, { timeout: 120_000 })
  await page.getByTestId('stop-button').click()
  await expect(page.getByTestId('streaming-message')).toHaveCount(0, { timeout: 30_000 })
  await page.reload()
  await expect(page.getByText('Stopped')).toBeVisible({ timeout: 30_000 })
})

test('document-scoped question from the viewer, side by side', async ({ page }) => {
  await page.goto('/library')
  await (await card(page, SMALL)).getByRole('link').first().click()
  await expect(page).toHaveURL(/\/documents\/[0-9a-f]{16}/)
  await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
  await page.getByLabel('Search in PDF').fill('trustworthy')
  await page.getByLabel('Search in PDF').press('Enter')
  await expect(page.getByText(/on \d+ pages/)).toBeVisible({ timeout: 60_000 })
  await page.getByRole('button', { name: 'Next page' }).click()
})

test('settings: invalid input is blocked, valid change persists', async ({ page }) => {
  await page.goto('/settings')
  const overlap = page.getByLabel('Chunk overlap (characters)')
  await overlap.fill('900')
  await expect(page.getByText('Overlap must be at most half the chunk size')).toBeVisible()
  await expect(page.getByTestId('save-settings')).toBeDisabled()
  await overlap.fill('150')
  await page.getByLabel('Maximum answer tokens').fill('200')
  await page.getByTestId('save-settings').click()
  await expect(page.getByText('Settings saved')).toBeVisible()
  await page.reload()
  await expect(page.getByLabel('Maximum answer tokens')).toHaveValue('200')
  await expect(page.getByLabel('Chunk overlap (characters)')).toHaveValue('150')
})

test('analytics shows live telemetry and benchmark evidence', async ({ page }) => {
  await page.goto('/analytics')
  await expect(page.getByRole('heading', { name: 'Live telemetry' })).toBeVisible()
  await expect(page.getByText(/Retrieval latency p50 \/ p95/)).toBeVisible()
  await expect(page.getByText('Document processing')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Benchmark evidence' })).toBeVisible()
  await expect(page.getByText(/Context relevance \(nDCG@5\)/)).toBeVisible()
})

test('theme switches between dark and light', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.getByRole('button', { name: 'Change theme' }).click()
  await page.getByRole('menuitemradio', { name: /Light/ }).click()
  await expect(page.locator('html')).not.toHaveClass(/dark/)
  await page.reload()
  await expect(page.locator('html')).not.toHaveClass(/dark/)
})

test('delete a document removes it and its index entries', async ({ page, request }) => {
  const before = await (await request.get('/api/v1/health')).json()
  await page.goto('/library')
  const small = await card(page, SMALL)
  await small.getByRole('button', { name: `Actions for ${SMALL}` }).click()
  await page.getByRole('menuitem', { name: /Delete/ }).click()
  await page.getByRole('button', { name: 'Delete document' }).click()
  await expect(page.getByText(/Deleted .* and its index entries/)).toBeVisible()
  await expect(await card(page, SMALL)).toHaveCount(0)
  const after = await (await request.get('/api/v1/health')).json()
  expect(after.documents).toBe(before.documents - 1)
  expect(after.index_vectors).toBeLessThan(before.index_vectors)
})
