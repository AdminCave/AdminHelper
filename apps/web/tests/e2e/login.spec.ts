// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { test, expect } from '@playwright/test';
import { mockApi } from './mocks';

test.describe('Login', () => {
  test('happy path: Formular ausfuellen und abschicken -> weiter zu /connections', async ({
    page,
  }) => {
    await mockApi(page);
    await page.goto('/');
    await expect(page.getByRole('heading')).toBeHidden();
    await page.fill('#loginUser', 'admin');
    await page.fill('#loginPass', 'secret123');
    await page.getByRole('button', { name: /Anmelden|Sign in/ }).click();

    await expect(page).toHaveURL(/#\/connections/);
  });

  test('visuelles Login-Layout stabil', async ({ page }) => {
    await mockApi(page);
    await page.goto('/');
    await expect(page.locator('.login-card')).toBeVisible();
    await expect(page).toHaveScreenshot('login.png', { fullPage: true });
  });
});
