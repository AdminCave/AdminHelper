// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { test, expect } from '@playwright/test';
import { mockApi } from './mocks';

// Theme toggle journey: from the authenticated app the sidebar toggle flips dark<->light
// (data-theme attribute + True-Black vs pure-white background), and the choice survives a
// reload because public/theme-init.js, loaded as a file from the <head>, re-applies the
// persisted theme before the first paint. The project chromium-build runs this against the
// build with the CSP as a header, as the server sends it. Toggle *store* logic is unit-tested
// in src/lib/stores/theme.test.ts; this covers the real button + browser reload.
test('sidebar toggle switches theme and it survives a reload', async ({ page }) => {
  const violations: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && msg.text().includes('Content Security Policy')) {
      violations.push(msg.text());
    }
  });
  await mockApi(page);
  await page.goto('/#/users');
  await page.waitForSelector('.page-title', { state: 'visible' });

  // default: dark (True-Black background, no explicit light attribute)
  const initial = await page.evaluate(() => document.documentElement.dataset.theme ?? null);
  expect(initial === null || initial === 'dark').toBeTruthy();
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe(
    'rgb(0, 0, 0)',
  );

  await page.getByRole('button', { name: /Design umschalten|Toggle theme/ }).click();

  await expect
    .poll(() => page.evaluate(() => document.documentElement.getAttribute('data-theme')))
    .toBe('light');
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe(
    'rgb(255, 255, 255)',
  );

  // reload: public/theme-init.js must re-apply the persisted light theme before paint
  await page.reload();
  await page.waitForSelector('.page-title', { state: 'visible' });
  expect(await page.evaluate(() => document.documentElement.getAttribute('data-theme'))).toBe(
    'light',
  );
  expect(violations).toEqual([]);
});
