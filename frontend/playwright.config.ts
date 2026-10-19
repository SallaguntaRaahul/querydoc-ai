import { defineConfig, devices } from '@playwright/test'

// End-to-end tests against a real, freshly started stack (FastAPI + built React app,
// real PyMuPDF/embeddings/FAISS/local LLM). Author: Raahul Sallagunta
export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 240_000,
  expect: { timeout: 20_000 },
  reporter: [['list'], ['junit', { outputFile: '../results/tests/playwright-junit.xml' }], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: 'http://127.0.0.1:8300',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    viewport: { width: 1440, height: 900 },
    colorScheme: 'dark',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
  webServer: {
    command: './e2e/start-server.sh',
    url: 'http://127.0.0.1:8300/api/v1/health',
    timeout: 240_000,
    reuseExistingServer: false,
    stdout: 'ignore',
  },
})
