// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// "Connections" with the real connections store: a failed fetch shows its error with a retry,
// a pending fetch shows that it loads, and neither claims there are no connections (R-0658).

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { render, cleanup, screen, fireEvent, waitFor } from '@testing-library/svelte';
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
import Connections from './Connections.svelte';

const A: Connection = {
  id: 'a',
  name: 'web01',
  kind: 'ssh',
  host: 'web01.example',
  port: null,
  username: null,
  domain: null,
  keyPath: null,
  url: null,
  notes: null,
  tags: [],
  trustCert: false,
  lastUsed: null,
  serverId: null,
};

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

describe('Connections page while loading and after a failed fetch', () => {
  it('shows the error in an alert instead of "no connections" when the fetch fails', async () => {
    h.fetchJwt.mockRejectedValueOnce(OFFLINE);
    render(Connections);

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(tNow('connections.loadFailed', { error: 'offline' }));
    expect(alert.textContent).not.toContain(tNow('connections.loadFailed.kept'));
    expect(screen.queryByText(tNow('connections.empty'))).toBeNull();
  });

  it('shows that it loads instead of "no connections" while the fetch is pending', async () => {
    let finish: (items: Connection[]) => void = () => {};
    h.fetchJwt.mockImplementationOnce(
      () =>
        new Promise<Connection[]>((resolve) => {
          finish = resolve;
        }),
    );
    render(Connections);

    expect(await screen.findByText(tNow('loading.generic'))).not.toBeNull();
    expect(screen.queryByText(tNow('connections.empty'))).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();

    finish([]);
    await waitFor(() => expect(screen.queryByText(tNow('loading.generic'))).toBeNull());
  });

  it('loads again on "Retry" and shows the list without the alert', async () => {
    h.fetchJwt.mockRejectedValueOnce(OFFLINE);
    render(Connections);
    await screen.findByRole('alert');

    h.fetchJwt.mockResolvedValueOnce([A]);
    await fireEvent.click(screen.getByRole('button', { name: tNow('action.retry') }));

    expect(await screen.findByText('web01')).not.toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(h.fetchJwt).toHaveBeenCalledTimes(2);
  });

  it('keeps the list loaded last and says so when a later fetch fails', async () => {
    h.fetchJwt.mockResolvedValueOnce([A]);
    render(Connections);
    expect(await screen.findByText('web01')).not.toBeNull();

    // A page switch mounts the page again, and the mount fetches.
    cleanup();
    h.fetchJwt.mockRejectedValueOnce(OFFLINE);
    render(Connections);

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(tNow('connections.loadFailed', { error: 'offline' }));
    expect(alert.textContent).toContain(tNow('connections.loadFailed.kept'));
    expect(screen.getByText('web01')).not.toBeNull();
  });

  it('still says there are no connections when the fetch returns none', async () => {
    h.fetchJwt.mockResolvedValueOnce([]);
    render(Connections);

    expect(await screen.findByText(tNow('connections.empty'))).not.toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText(tNow('loading.generic'))).toBeNull();
  });
});
