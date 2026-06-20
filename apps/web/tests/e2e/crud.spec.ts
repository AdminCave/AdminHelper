// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { test, expect, type Page } from '@playwright/test';
import { api, mockApi } from './mocks';

// Bewusst ohne Screenshot-Assertions (Flaky-Risiko) — nur DOM-Assertions.
// Authentifizierung: mockApi() beantwortet POST /api/auth/refresh mit Tokens, die
// hydrate() beim Laden in eine Session zurückführt (kein localStorage mehr).

async function gotoAuthenticated(page: Page, hash: string): Promise<void> {
  await page.goto(`/${hash}`);
  await page.waitForSelector('.page-title', { state: 'visible' });
  await page.waitForLoadState('networkidle');
}

test.describe('CRUD-Roundtrips gegen stateful Mocks', () => {
  test('Benutzer anlegen -> erscheint in Liste -> loeschen -> verschwindet', async ({ page }) => {
    await mockApi(page);
    await gotoAuthenticated(page, '#/users');

    // Anlegen
    await page.getByRole('button', { name: '+ Benutzer' }).click();
    const modal = page.getByRole('dialog');
    await modal.locator('#ufUsername').fill('e2e-user');
    await modal.locator('#ufPassword').fill('secret123');
    await modal.getByRole('button', { name: 'Speichern' }).click();
    await expect(modal).toBeHidden();
    await expect(page.locator('.toast-stack .toast.success')).toHaveText('Benutzer erstellt');

    // Erscheint in der Liste (kommt nach dem Modal-Close per frischem GET)
    const row = page.locator('tbody tr', { hasText: 'e2e-user' });
    await expect(row).toBeVisible();

    // Loeschen (mit Bestaetigungs-Dialog)
    await row.getByRole('button', { name: 'Löschen' }).click();
    const confirm = page.getByRole('dialog');
    await expect(confirm).toContainText('Benutzer wirklich löschen?');
    await confirm.getByRole('button', { name: 'Löschen' }).click();

    // Verschwindet, Admin-Eintrag bleibt
    await expect(page.locator('tbody tr', { hasText: 'e2e-user' })).toHaveCount(0);
    await expect(page.locator('tbody tr', { hasText: 'admin' })).toBeVisible();
  });

  test('API-Key anlegen -> Secret einmalig sichtbar -> in Liste -> loeschen', async ({ page }) => {
    await mockApi(page);
    await gotoAuthenticated(page, '#/apikeys');

    // Anlegen
    await page.getByRole('button', { name: '+ API-Key' }).click();
    const modal = page.getByRole('dialog');
    await modal.locator('#akName').fill('e2e-key');
    await modal.locator('#akPermission').selectOption('read');
    await modal.getByRole('button', { name: 'Erstellen' }).click();

    // Der Secret wird genau EINMAL angezeigt (Reveal-Dialog), per .key-reveal
    // adressiert, weil waehrend des Modal-Wechsels kurz zwei dialogs existieren.
    await expect(page.locator('.key-reveal')).toContainText('ah_e2e_');
    await expect(page.getByText('nur einmal angezeigt')).toBeVisible();
    await page.getByRole('button', { name: 'Schließen' }).click();

    // Erscheint in der Liste
    await expect(page.locator('tbody tr', { hasText: 'e2e-key' })).toBeVisible();

    // Loeschen (mit Bestaetigung)
    await page
      .locator('tbody tr', { hasText: 'e2e-key' })
      .getByRole('button', { name: 'Löschen' })
      .click();
    const confirm = page.getByRole('dialog');
    await expect(confirm).toContainText('API-Key wirklich löschen?');
    await confirm.getByRole('button', { name: 'Löschen' }).click();

    await expect(page.locator('tbody tr', { hasText: 'e2e-key' })).toHaveCount(0);
  });
});

test.describe('Fehler-Flows', () => {
  test('500 beim Anlegen eines Benutzers zeigt Fehler-Toast, Modal bleibt offen', async ({
    page,
  }) => {
    await mockApi(page);
    // Override NACH mockApi registriert -> gewinnt (LIFO); GET faellt per
    // fallback() an den stateful Handler durch.
    await page.route(api('users'), async (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Interner Serverfehler (E2E)' }),
        });
      }
      return route.fallback();
    });
    await gotoAuthenticated(page, '#/users');

    await page.getByRole('button', { name: '+ Benutzer' }).click();
    const modal = page.getByRole('dialog');
    await modal.locator('#ufUsername').fill('kaputt');
    await modal.locator('#ufPassword').fill('secret123');
    await modal.getByRole('button', { name: 'Speichern' }).click();

    const errorToast = page.locator('.toast-stack .toast.error');
    await expect(errorToast).toBeVisible();
    await expect(errorToast).toHaveText('Interner Serverfehler (E2E)');

    // Kein Eintrag entstanden, Modal bleibt offen
    await expect(modal).toBeVisible();
    await expect(page.locator('tbody tr', { hasText: 'kaputt' })).toHaveCount(0);
  });
});
