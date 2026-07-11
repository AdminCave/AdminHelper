// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { test, expect } from '@playwright/test';
import { api, mockApi } from './mocks';

// Every other suite runs as admin (mockApi serves is_admin: true), so nothing proved
// what a non-admin sees. The sidebar filter + the routeGuard (1.34) are the only
// authorization gates in the web UI; a regression in either would go unnoticed (6.87).
test.describe('Authorization', () => {
  test('Nicht-Admin: leere Admin-Nav + Deep-Link mountet den Placeholder statt der Admin-Seite', async ({
    page,
  }) => {
    await mockApi(page);
    const member = {
      id: 2,
      username: 'member',
      is_admin: false,
      created_at: '2025-01-01T00:00:00Z',
      server_ids: [],
    };
    await page.route(api('auth/me'), (r) =>
      r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(member) }),
    );
    await page.goto('/#/users');
    // Every route is adminOnly, so a non-admin sees no nav links at all.
    await expect(page.locator('.sidebar nav a')).toHaveCount(0);
    // The routeGuard falls a deep-linked admin path back to the catch-all Placeholder,
    // so the full Users page (with its "+ create" button and 403-prone data) never mounts.
    await expect(page.locator('.page-title')).toHaveText('Nicht verfuegbar');
  });
});
