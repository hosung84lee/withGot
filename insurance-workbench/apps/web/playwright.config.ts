import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  workers: 1,
  timeout: 30_000,
  use: {
    baseURL: process.env.BOJANGIT_URL ?? 'http://127.0.0.1:5173',
    browserName: 'chromium',
    channel: process.env.BOJANGIT_BROWSER_CHANNEL ?? (process.platform === 'win32' ? 'chrome' : undefined),
    viewport: { width: 1440, height: 1100 },
    trace: 'off',
  },
})
