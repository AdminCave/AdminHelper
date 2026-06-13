// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { AuthSession } from '$lib/bridge/types';
import type { ServerInput } from '$lib/api/types';

vi.mock('$lib/bridge', () => ({ apiProxy: vi.fn(async () => ({})) }));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { sessionStore: writable({ settings: { allowSelfSignedCerts: false } }) };
});

import * as bridge from '$lib/bridge';
import { serversApi } from './servers';

const session: AuthSession = {
  serverUrl: 'https://srv',
  token: 'tok',
  refreshToken: 'r',
  username: 'admin',
  isAdmin: true,
};
const proxy = vi.mocked(bridge.apiProxy);
const input: ServerInput = {
  name: 'web',
  hostname: 'web.lan',
  os_type: 'linux',
  tags: ['prod'],
  notes: '',
};

describe('serversApi', () => {
  beforeEach(() => proxy.mockClear());

  it('list → GET /api/servers', async () => {
    await serversApi.list(session);
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'GET',
      '/api/servers',
      undefined,
      false,
    );
  });

  it('create → POST /api/servers with serialized body', async () => {
    await serversApi.create(session, input);
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'POST',
      '/api/servers',
      JSON.stringify(input),
      false,
    );
  });

  it('update → PUT /api/servers/:id', async () => {
    await serversApi.update(session, 'id1', input);
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'PUT',
      '/api/servers/id1',
      JSON.stringify(input),
      false,
    );
  });

  it('remove → DELETE /api/servers/:id', async () => {
    await serversApi.remove(session, 'id1');
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'DELETE',
      '/api/servers/id1',
      undefined,
      false,
    );
  });
});
