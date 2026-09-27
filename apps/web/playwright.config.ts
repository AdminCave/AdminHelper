// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import path from 'node:path';
import { defineConfig, devices, type ReporterDescription } from '@playwright/test';

// JUnit only where a run collects it: run.sh exports AH_OUT_DIR, heavy.sh picks up
// its junit/ directory. Without an outputFile the junit reporter prints its XML to
// stdout (playwright.dev/docs/test-reporters), so the PR CI and a local run get none.
const junit: ReporterDescription[] = process.env.AH_OUT_DIR
  ? [['junit', { outputFile: path.join(process.env.AH_OUT_DIR, 'junit', 'web-playwright.xml') }]]
  : [];

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['html', { open: 'never' }], ['list'], ...junit],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
    viewport: { width: 1280, height: 800 },
    locale: 'de-DE',
    timezoneId: 'Europe/Berlin',
  },
  expect: {
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.02,
      animations: 'disabled',
      caret: 'hide',
    },
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], channel: undefined },
    },
  ],
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5173',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
