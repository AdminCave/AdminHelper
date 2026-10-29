// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The catch-all page is where a non-admin always lands: every route is admin-only (R-0721).

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/svelte';

// A session without a server, as in ConfirmDialog.test.ts; each test picks the role /me answers.
vi.mock('$lib/api/client', () => ({
  restoreSession: vi.fn(async () => true),
  registerAuthFailureHandler: vi.fn(),
}));
vi.mock('$lib/api/auth', () => ({
  me: vi.fn(),
  logout: vi.fn(async () => {}),
  login: vi.fn(),
}));

import Placeholder from './Placeholder.svelte';
import * as authApi from '$lib/api/auth';
import { auth } from '$lib/stores/auth';
import { language, type Language } from '$lib/i18n';
import { translations } from '$lib/i18n/dictionaries';

async function signIn(isAdmin: boolean): Promise<void> {
  vi.mocked(authApi.me).mockResolvedValue({ id: 2, username: 'member', is_admin: isAdmin });
  await auth.hydrate();
}

function renderPage(lang: Language) {
  language.set(lang);
  const { container } = render(Placeholder);
  return {
    title: container.querySelector('.page-title')?.textContent?.trim(),
    text: container.textContent ?? '',
    links: [...container.querySelectorAll('a')].map((a) => ({
      href: a.getAttribute('href'),
      label: a.textContent?.trim(),
    })),
  };
}

beforeEach(() => {
  language.set('de');
});

afterEach(async () => {
  cleanup();
  await auth.logout();
});

describe('Placeholder for a non-admin', () => {
  beforeEach(() => signIn(false));

  it.each([
    ['de', 'Web-Panel nur für Admins', 'Bitte den Desktop-Client nutzen.'],
    ['en', 'Web panel for admins only', 'Please use the desktop client.'],
  ] as const)('points to the desktop client (%s)', (lang, title, hint) => {
    const page = renderPage(lang);

    expect(page.title).toBe(title);
    expect(page.text).toContain(hint);
    // The old page talked about a migration the user has nothing to do with.
    expect(page.text).not.toContain('portiert');
    expect(page.text).not.toContain('spaeteren');
  });
});

describe('Placeholder for an admin', () => {
  beforeEach(() => signIn(true));

  it.each(['de', 'en'] as const)('shows no admins-only hint (%s)', (lang) => {
    const page = renderPage(lang);

    // The page is there, just not the hint meant for non-admins.
    expect(page.title).toBeTruthy();
    for (const dict of [translations.de, translations.en]) {
      expect(page.text).not.toContain(dict['page.adminOnly.title']);
      expect(page.text).not.toContain(dict['page.adminOnly.text']);
    }
  });

  it.each([
    ['de', 'Seite nicht gefunden', 'Zur Benutzerverwaltung'],
    ['en', 'Page not found', 'Go to user management'],
  ] as const)(
    'says the page was not found and links to the users page (%s)',
    (lang, title, back) => {
      const page = renderPage(lang);

      expect(page.title).toBe(title);
      expect(page.links).toEqual([{ href: '#/users', label: back }]);
      // An admin only lands here on an unknown path; the old migration notice is gone.
      expect(page.text).not.toContain('Nicht verfuegbar');
      expect(page.text).not.toContain('portiert');
      expect(page.text).not.toContain('spaeteren');
    },
  );
});
