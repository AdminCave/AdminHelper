// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { test, expect, type Page } from '@playwright/test';

// Against the real stack (scripts/tests/web_live.sh), no mocks: the seed admin is
// the one lib_e2e_stack.sh creates through ADMIN_PASSWORD, every request reaches
// the server behind the gateway. What tests/e2e promises through mockApi is
// checked here against the API itself.
const ADMIN_PW = process.env.ITEST_ADMIN_PW ?? '';

const ADMIN_PAGES = ['#/users', '#/apikeys', '#/hooks', '#/frp', '#/audit'];

// Uncaught exceptions only: a real API answers 401 before the login and 404 for
// what is not configured yet, and the browser logs each as a console error.
function trackPageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  return errors;
}

async function login(page: Page): Promise<void> {
  await page.goto('/');
  await expect(page.locator('.login-card')).toBeVisible();
  await page.fill('#loginUser', 'admin');
  await page.fill('#loginPass', ADMIN_PW);
  await page.getByRole('button', { name: /Anmelden|Sign in/ }).click();
  await expect(page).toHaveURL(/#\/users/);
  await expect(page.locator('.page-title')).toBeVisible();
}

test.beforeAll(() => {
  expect(ADMIN_PW, 'ITEST_ADMIN_PW is unset — run this project through web_live.sh').not.toBe('');
});

test('Login mit dem Seed-Admin fuehrt zu /users', async ({ page }) => {
  const errors = trackPageErrors(page);
  await login(page);
  expect(errors, 'page errors during the login').toEqual([]);
});

test('Smoke: jede Admin-Seite laedt gegen die echte API', async ({ page }) => {
  const errors = trackPageErrors(page);
  await login(page);
  for (const hash of ADMIN_PAGES) {
    // A full navigation, so the session also has to survive hydrate() and its
    // refresh-cookie round trip, not only the in-app router.
    await page.goto(`/${hash}`);
    await expect(page.locator('.page-title'), `page title on ${hash}`).toBeVisible();
  }
  expect(errors, 'page errors on the admin pages').toEqual([]);
});

test('Benutzer anlegen -> erscheint in der Liste -> loeschen -> verschwindet', async ({ page }) => {
  // Unique per run: the stack is throwaway, but a retry must not collide with
  // the user the first attempt created.
  const name = `live-${Date.now()}`;
  await login(page);

  await page.getByRole('button', { name: '+ Benutzer' }).click();
  const modal = page.getByRole('dialog');
  await modal.locator('#ufUsername').fill(name);
  await modal.locator('#ufPassword').fill('live-secret-123');
  await modal.getByRole('button', { name: 'Speichern' }).click();
  await expect(modal).toBeHidden();
  await expect(page.locator('.toast-stack .toast.success')).toHaveText('Benutzer erstellt');

  const row = page.locator('tbody tr', { hasText: name });
  await expect(row).toBeVisible();
  // Read back from the server, not from the page's own state.
  await page.reload();
  await expect(page.locator('tbody tr', { hasText: name })).toBeVisible();

  await page
    .locator('tbody tr', { hasText: name })
    .getByRole('button', { name: 'Löschen' })
    .click();
  const confirm = page.getByRole('dialog');
  await expect(confirm).toContainText('Benutzer wirklich löschen?');
  await confirm.getByRole('button', { name: 'Löschen' }).click();

  await expect(page.locator('tbody tr', { hasText: name })).toHaveCount(0);
  await page.reload();
  await expect(page.locator('tbody tr', { hasText: name })).toHaveCount(0);
  await expect(page.locator('tbody tr', { hasText: 'admin' })).toBeVisible();
});
