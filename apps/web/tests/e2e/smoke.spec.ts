// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { test, expect, type Page } from '@playwright/test';
import { mockApi, seedAuth } from './mocks';

interface RouteCase {
  hash: string;
  name: string;
  expectSelector: string;
}

const ROUTES: RouteCase[] = [
  { hash: '#/connections', name: 'connections', expectSelector: '.page-title' },
  { hash: '#/servers', name: 'servers', expectSelector: '.page-title' },
  { hash: '#/users', name: 'users', expectSelector: '.page-title' },
  { hash: '#/apikeys', name: 'apikeys', expectSelector: '.page-title' },
  { hash: '#/hooks', name: 'hooks', expectSelector: '.page-title' },
  { hash: '#/frp', name: 'frp', expectSelector: '.page-title' },
  { hash: '#/ansible', name: 'ansible', expectSelector: '.page-title' },
  { hash: '#/monitoring', name: 'monitoring', expectSelector: '.page-title' },
];

async function gotoAuthenticated(page: Page, hash: string): Promise<void> {
  await mockApi(page);
  await seedAuth(page);
  await page.goto(`/${hash}`);
  await page.waitForSelector('.page-title', { state: 'visible' });
  // Warte auf vollstaendiges Hydration-Render (Router tauscht Komponente).
  await page.waitForLoadState('networkidle');
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
      // Layout-Settling: kleine Stabilisierungs-Pause fuer gerenderte Listen.
      await page.waitForTimeout(200);
      await expect(page).toHaveScreenshot(`${r.name}.png`, { fullPage: true });
    });
  }
});
