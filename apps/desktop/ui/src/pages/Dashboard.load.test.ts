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

vi.mock('$lib/stores/monitoring', async () => {
  const { writable } = await import('svelte/store');
  return {
    loadServers: vi.fn(async () => {}),
    loadMonitoring: vi.fn(async () => {}),
    setSelectedServer: vi.fn(),
    setOverviewView: vi.fn(),
    monitoringChecks: writable([]),
    monitoringServers: writable([]),
    // Loaded: the monitoring panel shows no loading text of its own here.
    monitoringHasLoaded: writable(true),
    monitoringServersLoaded: writable(true),
    monitoringError: writable(null),
  };
});
vi.mock('$lib/stores/tunnel', async () => {
  const { writable } = await import('svelte/store');
  return { tunnel: writable({ ui: 'idle' }), tunnelMappings: writable([]) };
});

import { setLanguage, tNow } from '$lib/i18n';
import { clearInMemory, loadForCurrentMode } from '$lib/stores/connections';
import Dashboard from './Dashboard.svelte';

const OFFLINE = new Error('offline');

function cardHint(card: string): string {
  return document.querySelector(`[data-card="${card}"] .dash-card-hint`)?.textContent?.trim() ?? '';
}

function cardValue(card: string): string {
  return (
    document.querySelector(`[data-card="${card}"] .dash-card-value`)?.textContent?.trim() ?? ''
  );
}

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
    // Nothing came back: neither "no connections used" nor a count of zero (R-0781).
    expect(screen.queryByText(tNow('dashboard.empty'))).toBeNull();
    expect(cardValue('connections')).toBe('-');
    expect(cardHint('connections')).toBe('');
  });

  it('keeps counting the list a failed reload of the same source kept', async () => {
    h.fetchJwt.mockResolvedValueOnce([
      { id: 'c1', name: 'nas', kind: 'ssh', host: 'nas.example' },
      { id: 'c2', name: 'wiki', kind: 'web', url: 'https://wiki.example' },
    ]);
    render(Dashboard);
    await waitFor(() => expect(cardValue('connections')).toBe('2'));

    h.fetchJwt.mockRejectedValueOnce(OFFLINE);
    await loadForCurrentMode();

    expect(await screen.findByRole('alert')).not.toBeNull();
    expect(cardValue('connections')).toBe('2');
    expect(cardHint('connections')).toBe(tNow('dashboard.kindHint', { ssh: 1, rdp: 0, web: 1 }));
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
    expect(cardValue('connections')).toBe('-');
    expect(cardHint('connections')).toBe('');

    finish([]);
    await waitFor(() => expect(screen.queryByText(tNow('loading.generic'))).toBeNull());
  });

  it('still says no connections were used when the fetch returns none', async () => {
    h.fetchJwt.mockResolvedValueOnce([]);
    render(Dashboard);

    expect(await screen.findByText(tNow('dashboard.empty'))).not.toBeNull();
    expect(cardValue('connections')).toBe('0');
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText(tNow('loading.generic'))).toBeNull();
  });
});
