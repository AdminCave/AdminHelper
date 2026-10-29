// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The dashboard with the real connections store: a failed fetch shows its error with a retry,
// and a pending fetch shows that it loads instead of "no connections used yet" (R-0658).

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { render, cleanup, screen, waitFor } from '@testing-library/svelte';
import type { Connection } from '$lib/bridge/types';

const h = vi.hoisted(() => ({
  fetchJwt: vi.fn(async (..._a: unknown[]) => [] as unknown[]),
}));

vi.mock('$lib/bridge', () => ({
  fetchConnectionsJwt: h.fetchJwt,
  syncConnections: vi.fn(async () => []),
  loadConnections: vi.fn(async () => []),
  saveConnections: vi.fn(async () => {}),
}));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return {
    sessionStore: writable({
      settings: { mode: 'server', url: null, allowSelfSignedCerts: false },
      session: { serverUrl: 'https://srv.example', username: 'alice', isAdmin: false },
    }),
  };
});

import { setLanguage, tNow } from '$lib/i18n';
import { clearInMemory } from '$lib/stores/connections';
import Dashboard from './Dashboard.svelte';

const OFFLINE = new Error('offline');

beforeAll(() => {
  setLanguage('en');
});

beforeEach(() => {
  h.fetchJwt.mockReset();
  clearInMemory();
});

afterEach(() => {
  cleanup();
});

describe('Dashboard while loading and after a failed fetch', () => {
  it('shows the error in an alert when the fetch fails', async () => {
    h.fetchJwt.mockRejectedValueOnce(OFFLINE);
    render(Dashboard);

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(tNow('connections.loadFailed', { error: 'offline' }));
    expect(screen.getByRole('button', { name: tNow('action.retry') })).not.toBeNull();
  });

  it('shows that it loads instead of "no connections used" while the fetch is pending', async () => {
    let finish: (items: Connection[]) => void = () => {};
    h.fetchJwt.mockImplementationOnce(
      () =>
        new Promise<Connection[]>((resolve) => {
          finish = resolve;
        }),
    );
    render(Dashboard);

    expect(await screen.findByText(tNow('loading.generic'))).not.toBeNull();
    expect(screen.queryByText(tNow('dashboard.empty'))).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();

    finish([]);
    await waitFor(() => expect(screen.queryByText(tNow('loading.generic'))).toBeNull());
  });

  it('still says no connections were used when the fetch returns none', async () => {
    h.fetchJwt.mockResolvedValueOnce([]);
    render(Dashboard);

    expect(await screen.findByText(tNow('dashboard.empty'))).not.toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText(tNow('loading.generic'))).toBeNull();
  });
});
