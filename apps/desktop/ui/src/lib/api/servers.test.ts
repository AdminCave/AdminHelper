// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { AuthSession } from '$lib/bridge/types';
import type { ServerInput } from '$lib/api/types';

vi.mock('$lib/bridge', () => ({ apiProxy: vi.fn(async () => ({})) }));

import * as bridge from '$lib/bridge';
import { serversApi } from './servers';

const session: AuthSession = {
  serverUrl: 'https://srv',
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
    expect(proxy).toHaveBeenCalledWith('GET', '/api/servers', undefined);
  });

  it('create → POST /api/servers with serialized body', async () => {
    await serversApi.create(session, input);
    expect(proxy).toHaveBeenCalledWith('POST', '/api/servers', JSON.stringify(input));
  });

  it('update → PUT /api/servers/:id', async () => {
    await serversApi.update(session, 'id1', input);
    expect(proxy).toHaveBeenCalledWith('PUT', '/api/servers/id1', JSON.stringify(input));
  });

  it('remove → DELETE /api/servers/:id', async () => {
    await serversApi.remove(session, 'id1');
    expect(proxy).toHaveBeenCalledWith('DELETE', '/api/servers/id1', undefined);
  });

  it('encodes the id so a slash-bearing value cannot rewrite the path (3.66)', async () => {
    await serversApi.remove(session, '../users/1');
    expect(proxy).toHaveBeenCalledWith('DELETE', '/api/servers/..%2Fusers%2F1', undefined);
  });
});
