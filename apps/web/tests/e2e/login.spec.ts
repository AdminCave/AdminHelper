// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { test, expect, type Page } from '@playwright/test';
import { api, mockApi } from './mocks';

// The login tests must start WITHOUT a session: hydrate() now restores a session
// on load via POST /api/auth/refresh, so override it to 401 here. (The default
// mockApi makes refresh succeed = authenticated, which the other suites rely on.)
async function mockLoggedOut(page: Page): Promise<void> {
  await mockApi(page);
  await page.route(api('auth/refresh'), (route) =>
    route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'no session' }),
    }),
  );
}

test.describe('Login', () => {
  test('happy path: Formular ausfuellen und abschicken -> weiter zu /users', async ({ page }) => {
    await mockLoggedOut(page);
    await page.goto('/');
    // We are logged out -> the login card is shown. (The old getByRole('heading')
    // .toBeHidden() was trivially green: the page has no role=heading, so the locator
    // matched zero elements and toBeHidden() passed without asserting anything.) (6.156)
    await expect(page.locator('.login-card')).toBeVisible();
    await page.fill('#loginUser', 'admin');
    await page.fill('#loginPass', 'secret123');
    await page.getByRole('button', { name: /Anmelden|Sign in/ }).click();

    await expect(page).toHaveURL(/#\/users/);
  });

  test('falsche Credentials zeigen die Server-Fehlermeldung', async ({ page }) => {
    await mockLoggedOut(page);
    await page.route(api('auth/login'), (route) =>
      route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Invalid credentials' }),
      }),
    );
    await page.goto('/');
    await page.fill('#loginUser', 'admin');
    await page.fill('#loginPass', 'falsch');
    await page.getByRole('button', { name: /Anmelden|Sign in/ }).click();
    // The dedicated error banner (the most common real failure) must render, and we
    // must stay on the login page — a refactor dropping err.message would leave the
    // user with no feedback while the happy-path test still passed (6.92).
    await expect(page.locator('.login-error')).toHaveText('Invalid credentials');
    await expect(page).not.toHaveURL(/#\/users/);
  });

  test('visuelles Login-Layout stabil', async ({ page }) => {
    await mockLoggedOut(page);
    await page.goto('/');
    await expect(page.locator('.login-card')).toBeVisible();
    await expect(page).toHaveScreenshot('login.png', { fullPage: true });
  });
});
