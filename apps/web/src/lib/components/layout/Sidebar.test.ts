// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The sidebar marks the current page (bold with a bar, aria-current), hides admin pages from a
// non-admin, signs out and flips the theme. The session comes from the refresh cookie as in
// App.idle.test.ts; the router reads location.hash.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';

import Sidebar from './Sidebar.svelte';
import { auth, isAuthenticated } from '$lib/stores/auth';
import { theme } from '$lib/stores/theme';
import { language } from '$lib/i18n';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

let admin: boolean;
let fetchMock: ReturnType<typeof vi.fn>;

function fetchStub(input: RequestInfo | URL): Promise<Response> {
  const path = String(input).split('?')[0];
  if (path === '/api/auth/refresh') return Promise.resolve(json({ access_token: 'a1' }));
  if (path === '/api/auth/me') {
    return Promise.resolve(json({ id: 1, username: 'alice', is_admin: admin }));
  }
  if (path === '/api/auth/logout') return Promise.resolve(json({ detail: 'ok' }));
  return Promise.resolve(json([]));
}

async function signIn(isAdminUser: boolean) {
  admin = isAdminUser;
  await auth.hydrate();
  expect(get(isAuthenticated)).toBe(true);
}

function goTo(hash: string) {
  location.hash = hash;
  window.dispatchEvent(new HashChangeEvent('hashchange'));
}

describe('Sidebar', () => {
  beforeEach(() => {
    localStorage.clear();
    language.set('de');
    fetchMock = vi.fn(fetchStub);
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(async () => {
    cleanup();
    await auth.logout();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('marks exactly the current page as active', async () => {
    await signIn(true);
    goTo('#/frp');
    const { container, findByText } = render(Sidebar);
    await findByText('alice');

    const active = container.querySelectorAll('nav a.active');
    expect(active).toHaveLength(1);
    expect(active[0].getAttribute('href')).toBe('#/frp');
    expect(active[0].getAttribute('aria-current')).toBe('page');
    // Every entry carries a Lucide icon instead of the old inline paths.
    for (const a of container.querySelectorAll('nav a')) {
      expect(a.querySelector('svg.lucide')).not.toBeNull();
    }

    goTo('#/audit');
    await vi.waitFor(() =>
      expect(container.querySelector('nav a.active')?.getAttribute('href')).toBe('#/audit'),
    );
    expect(container.querySelectorAll('nav a[aria-current="page"]')).toHaveLength(1);
  });

  it('shows the admin pages only to an admin', async () => {
    // Every page of the panel is adminOnly in routes.ts, so a plain user sees no entry.
    await signIn(false);
    const { container, findByText } = render(Sidebar);
    await findByText('alice');
    expect(container.querySelectorAll('nav a')).toHaveLength(0);
    cleanup();
    await auth.logout();

    await signIn(true);
    const view = render(Sidebar);
    await view.findByText('alice');
    expect(view.container.querySelectorAll('nav a')).toHaveLength(6);
  });

  it('signs out from the user row', async () => {
    await signIn(true);
    const { getByRole, findByText } = render(Sidebar);
    await findByText('alice');
    await fireEvent.click(getByRole('button', { name: 'Abmelden' }));
    await vi.waitFor(() => expect(get(isAuthenticated)).toBe(false));
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) =>
          String(input) === '/api/auth/logout' &&
          (init as RequestInit | undefined)?.method === 'POST',
      ),
    ).toBe(true);
  });

  it('flips the theme with its button', async () => {
    await signIn(true);
    const { getByRole, findByText } = render(Sidebar);
    await findByText('alice');
    const before = get(theme);
    await fireEvent.click(getByRole('button', { name: 'Design umschalten' }));
    expect(get(theme)).toBe(before === 'dark' ? 'light' : 'dark');
    expect(document.documentElement.dataset.theme).toBe(get(theme));
    await fireEvent.click(getByRole('button', { name: 'Design umschalten' }));
    expect(get(theme)).toBe(before);
  });
});
