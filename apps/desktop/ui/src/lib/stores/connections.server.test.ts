// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Server-mode write path of the connections store: upsert/remove must go through
// the server API (connectionsApi) and re-pull from the server, never the file.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Connection } from '$lib/bridge/types';

// vi.mock is hoisted above the module body, so the mock fns must be created in a
// vi.hoisted block to be referenceable from the factories.
const h = vi.hoisted(() => ({
  create: vi.fn(async (..._a: unknown[]) => ({})),
  update: vi.fn(async (..._a: unknown[]) => ({})),
  remove: vi.fn(async (..._a: unknown[]) => {}),
  fetchJwt: vi.fn(async (..._a: unknown[]) => [] as unknown[]),
  saveConnections: vi.fn(async (..._a: unknown[]) => {}),
}));

vi.mock('$lib/bridge', () => ({
  saveConnections: h.saveConnections,
  loadConnections: vi.fn(async () => []),
  fetchConnectionsJwt: h.fetchJwt,
  syncConnections: vi.fn(async () => []),
}));
vi.mock('$lib/api/connections', () => ({
  connectionsApi: { create: h.create, update: h.update, remove: h.remove },
}));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return {
    sessionStore: writable({
      settings: { mode: 'server', allowSelfSignedCerts: false },
      session: {
        serverUrl: 'https://srv',
        username: 'admin',
        isAdmin: true,
      },
    }),
  };
});

import { upsert, remove, saveAll } from './connections';

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

describe('connections store — server mode', () => {
  beforeEach(() => {
    h.create.mockClear();
    h.update.mockClear();
    h.remove.mockClear();
    h.fetchJwt.mockClear();
    h.saveConnections.mockClear();
  });

  it('creates a brand-new connection server-side without sending the client id', async () => {
    await saveAll([]); // empty list -> id not found -> create
    h.saveConnections.mockClear();
    await upsert(conn({ id: 'client-tmp', name: 'web', host: 'h', serverId: 's1' }));
    expect(h.create).toHaveBeenCalledOnce();
    expect(h.update).not.toHaveBeenCalled();
    const payload = h.create.mock.calls[0][1] as Record<string, unknown>;
    expect(payload).not.toHaveProperty('id');
    expect(payload.serverId).toBe('s1');
    expect(h.fetchJwt).toHaveBeenCalledWith(); // re-pulled from server
  });

  it('updates an existing connection server-side by id', async () => {
    await saveAll([conn({ id: 'srv-1', name: 'old' })]);
    await upsert(conn({ id: 'srv-1', name: 'new' }));
    expect(h.update).toHaveBeenCalledOnce();
    expect(h.update.mock.calls[0][1]).toBe('srv-1');
    expect((h.update.mock.calls[0][2] as Record<string, unknown>).name).toBe('new');
    expect(h.create).not.toHaveBeenCalled();
  });

  it('removes a connection server-side', async () => {
    await saveAll([conn({ id: 'srv-1' })]);
    await remove('srv-1');
    expect(h.remove).toHaveBeenCalledOnce();
    expect(h.remove.mock.calls[0][1]).toBe('srv-1');
  });

  it('does not write the local file on a server-mode write', async () => {
    await saveAll([conn({ id: 'srv-1' })]);
    h.saveConnections.mockClear();
    await remove('srv-1');
    expect(h.saveConnections).not.toHaveBeenCalled();
  });
});
