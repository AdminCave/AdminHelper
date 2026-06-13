// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { AuthSession } from '$lib/bridge/types';
import type { Connection } from '$lib/api/types';

vi.mock('$lib/bridge', () => ({ apiProxy: vi.fn(async () => ({})) }));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { sessionStore: writable({ settings: { allowSelfSignedCerts: false } }) };
});

import * as bridge from '$lib/bridge';
import { connectionsApi } from './connections';

const session: AuthSession = {
  serverUrl: 'https://srv',
  token: 'tok',
  refreshToken: 'r',
  username: 'admin',
  isAdmin: true,
};
const proxy = vi.mocked(bridge.apiProxy);
const data: Partial<Connection> = { name: 'box', kind: 'ssh', host: 'box.lan', port: 22 };

describe('connectionsApi', () => {
  beforeEach(() => proxy.mockClear());

  it('list → GET /api/connections', async () => {
    await connectionsApi.list(session);
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'GET',
      '/api/connections',
      undefined,
      false,
    );
  });

  it('create → POST /api/connections with serialized body', async () => {
    await connectionsApi.create(session, data);
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'POST',
      '/api/connections',
      JSON.stringify(data),
      false,
    );
  });

  it('update → PUT /api/connections/:id', async () => {
    await connectionsApi.update(session, 'c1', data);
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'PUT',
      '/api/connections/c1',
      JSON.stringify(data),
      false,
    );
  });

  it('remove → DELETE /api/connections/:id', async () => {
    await connectionsApi.remove(session, 'c1');
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'DELETE',
      '/api/connections/c1',
      undefined,
      false,
    );
  });
});
