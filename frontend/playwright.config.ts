import { defineConfig } from '@playwright/test';

/**
 * E2E de navegador contra a stack de homologação já em execução
 * (`docker compose up -d`). Usa o Chrome instalado na máquina, sem baixar
 * binários do Playwright.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8082',
    // Localmente usa o Chrome instalado; no CI cai para o Chromium do Playwright.
    channel: (process.env.PLAYWRIGHT_CHANNEL as 'chrome' | 'chromium' | undefined) || 'chrome',
    launchOptions: { args: ['--no-sandbox'] },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
});
