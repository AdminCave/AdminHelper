// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// A failed fetch keeps the list in memory only if the last successful fetch had the same
// source (server and user, or sync URL); any other source must never leave its list showing.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import type { AuthSession, Connection, Settings } from '$lib/bridge/types';

const h = vi.hoisted(() => ({
  fetchJwt: vi.fn(async (..._a: unknown[]) => [] as unknown[]),
  sync: vi.fn(async (..._a: unknown[]) => [] as unknown[]),
  loadConnections: vi.fn(async (..._a: unknown[]) => [] as unknown[]),
  saveConnections: vi.fn(async (..._a: unknown[]) => {}),
}));

vi.mock('$lib/bridge', () => ({
  saveConnections: h.saveConnections,
  loadConnections: h.loadConnections,
  fetchConnectionsJwt: h.fetchJwt,
  syncConnections: h.sync,
}));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { sessionStore: writable({ settings: null, session: null }) };
});

import {
  connections,
  connectionsStore,
  reloadForMode,
  clearInMemory,
  saveAll,
  load,
} from './connections';

const conn = (over: Partial<Connection>): Connection => ({
  id: 'id',
  name: 'n',
  kind: 'ssh',
  host: null,
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
  ...over,
});

const A = conn({ id: 'a', name: 'A' });

const settings = (over: Partial<Settings>): Settings =>
  ({ mode: 'server', url: null, allowSelfSignedCerts: false, ...over }) as Settings;

const sess = (username: string): AuthSession => ({
  serverUrl: 'https://srv.example',
  username,
  isAdmin: false,
});

const ids = (): string[] => get(connections).map((c) => c.id);

describe('connections store — reloadForMode after a failed fetch', () => {
  beforeEach(() => {
    h.fetchJwt.mockReset();
    h.sync.mockReset();
    h.loadConnections.mockReset();
    h.saveConnections.mockReset();
    clearInMemory();
  });

  it('keeps the list of the same server and user when the fetch fails', async () => {
    h.fetchJwt.mockResolvedValueOnce([A]);
    await reloadForMode(settings({ mode: 'server' }), sess('alice'));
    h.fetchJwt.mockRejectedValueOnce(new Error('offline'));
    await reloadForMode(settings({ mode: 'server' }), sess('alice'));
    expect(ids()).toEqual(['a']);
    expect(get(connectionsStore).error).toBe('offline');
    expect(get(connectionsStore).loading).toBe(false);
  });

  it('keeps the list of the same sync URL when the sync fails', async () => {
    const s = settings({ mode: 'sync', url: 'https://sync.example/c.json' });
    h.sync.mockResolvedValueOnce([A]);
    await reloadForMode(s, null);
    h.sync.mockRejectedValueOnce(new Error('offline'));
    await reloadForMode(s, null);
    expect(h.sync).toHaveBeenLastCalledWith('https://sync.example/c.json');
    expect(ids()).toEqual(['a']);
    expect(get(connectionsStore).error).toBe('offline');
    expect(get(connectionsStore).loading).toBe(false);
  });

  it('empties the list when the failed fetch is for another user on the same server', async () => {
    h.fetchJwt.mockResolvedValueOnce([A]);
    await reloadForMode(settings({ mode: 'server' }), sess('alice'));
    h.fetchJwt.mockRejectedValueOnce(new Error('offline'));
    await reloadForMode(settings({ mode: 'server' }), sess('bob'));
    expect(ids()).toEqual([]);
    expect(get(connectionsStore).error).toBe('offline');
  });

  it('empties the list after clearInMemory even for the same source', async () => {
    h.fetchJwt.mockResolvedValueOnce([A]);
    await reloadForMode(settings({ mode: 'server' }), sess('alice'));
    clearInMemory();
    // clearInMemory leaves an empty list, which a failed fetch could not tell from a kept one;
    // a write that is no fetch puts an item back, so the test sees whether the source was forgotten.
    await saveAll([conn({ id: 'b' })]);
    h.fetchJwt.mockRejectedValueOnce(new Error('offline'));
    await reloadForMode(settings({ mode: 'server' }), sess('alice'));
    expect(ids()).toEqual([]);
    expect(get(connectionsStore).error).toBe('offline');
  });

  it('empties the list when the fetch fails after a cache load', async () => {
    h.fetchJwt.mockResolvedValueOnce([A]);
    await reloadForMode(settings({ mode: 'server' }), sess('alice'));
    h.loadConnections.mockResolvedValueOnce([conn({ id: 'cached' })]);
    await load();
    expect(ids()).toEqual(['cached']);
    h.fetchJwt.mockRejectedValueOnce(new Error('offline'));
    await reloadForMode(settings({ mode: 'server' }), sess('alice'));
    expect(ids()).toEqual([]);
  });

  it('keeps the list and reports loading while a fetch is pending', async () => {
    h.fetchJwt.mockResolvedValueOnce([A]);
    await reloadForMode(settings({ mode: 'server' }), sess('alice'));
    let fail: (e: Error) => void = () => {};
    h.fetchJwt.mockImplementationOnce(
      () =>
        new Promise<unknown[]>((_resolve, reject) => {
          fail = reject;
        }),
    );
    const pending = reloadForMode(settings({ mode: 'server' }), sess('alice'));
    expect(ids()).toEqual(['a']);
    expect(get(connectionsStore).loading).toBe(true);
    expect(get(connectionsStore).error).toBeNull();
    fail(new Error('offline'));
    await pending;
    expect(ids()).toEqual(['a']);
    expect(get(connectionsStore).loading).toBe(false);
  });
});
