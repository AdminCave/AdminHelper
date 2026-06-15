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
    await expect(page.getByRole('heading')).toBeHidden();
    await page.fill('#loginUser', 'admin');
    await page.fill('#loginPass', 'secret123');
    await page.getByRole('button', { name: /Anmelden|Sign in/ }).click();

    await expect(page).toHaveURL(/#\/users/);
  });

  test('visuelles Login-Layout stabil', async ({ page }) => {
    await mockLoggedOut(page);
    await page.goto('/');
    await expect(page.locator('.login-card')).toBeVisible();
    await expect(page).toHaveScreenshot('login.png', { fullPage: true });
  });
});
