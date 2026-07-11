// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { test, expect, type Page } from '@playwright/test';
import { mockApi } from './mocks';

interface RouteCase {
  hash: string;
  name: string;
  expectSelector: string;
}

const ROUTES: RouteCase[] = [
  { hash: '#/users', name: 'users', expectSelector: '.page-title' },
  { hash: '#/apikeys', name: 'apikeys', expectSelector: '.page-title' },
  { hash: '#/hooks', name: 'hooks', expectSelector: '.page-title' },
  { hash: '#/frp', name: 'frp', expectSelector: '.page-title' },
  { hash: '#/audit', name: 'audit', expectSelector: '.page-title' },
];

async function gotoAuthenticated(page: Page, hash: string): Promise<void> {
  await mockApi(page);
  await page.goto(`/${hash}`);
  // The visible .page-title is the deterministic ready signal (the router has swapped
  // the component and it rendered); networkidle is fragile — it breaks under any polling
  // and doesn't guarantee the UI is rendered anyway (Playwright advises against it) (6.155).
  await page.waitForSelector('.page-title', { state: 'visible' });
}

test.describe('Navigation smoke tests (alle migrierten Seiten)', () => {
  for (const r of ROUTES) {
    test(`Route ${r.hash} laedt ohne Fehler`, async ({ page }) => {
      const errors: string[] = [];
      page.on('pageerror', (e) => errors.push(e.message));
      page.on('console', (msg) => {
        if (msg.type() === 'error') errors.push(msg.text());
      });

      await gotoAuthenticated(page, r.hash);
      await expect(page.locator(r.expectSelector)).toBeVisible();

      expect(
        errors.filter((e) => !e.includes('favicon') && !e.includes('Source map')),
        `Console/Page-Errors auf ${r.hash}`,
      ).toEqual([]);
    });
  }
});

test.describe('Visual-Diff pro Seite', () => {
  for (const r of ROUTES) {
    test(`Screenshot ${r.name}`, async ({ page }) => {
      await gotoAuthenticated(page, r.hash);
      // No manual settle pause: toHaveScreenshot already retries until two consecutive
      // screenshots match, so a fixed 200ms sleep was both redundant and flaky (6.157).
      await expect(page).toHaveScreenshot(`${r.name}.png`, { fullPage: true });
    });
  }
});
