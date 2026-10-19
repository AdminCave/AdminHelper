// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { AuthSession } from '$lib/bridge/types';
import type { Connection } from '$lib/api/types';

vi.mock('$lib/bridge', () => ({ apiProxy: vi.fn(async () => ({})) }));

import * as bridge from '$lib/bridge';
import { connectionsApi } from './connections';

const session: AuthSession = {
  serverUrl: 'https://srv',
  username: 'admin',
  isAdmin: true,
};
const proxy = vi.mocked(bridge.apiProxy);
const data: Partial<Connection> = { name: 'box', kind: 'ssh', host: 'box.lan', port: 22 };

describe('connectionsApi', () => {
  beforeEach(() => proxy.mockClear());

  it('list → GET /api/connections', async () => {
    await connectionsApi.list(session);
    expect(proxy).toHaveBeenCalledWith('GET', '/api/connections', undefined);
  });

  it('create → POST /api/connections with serialized body', async () => {
    await connectionsApi.create(session, data);
    expect(proxy).toHaveBeenCalledWith('POST', '/api/connections', JSON.stringify(data));
  });

  it('update → PUT /api/connections/:id', async () => {
    await connectionsApi.update(session, 'c1', data);
    expect(proxy).toHaveBeenCalledWith('PUT', '/api/connections/c1', JSON.stringify(data));
  });

  it('remove → DELETE /api/connections/:id', async () => {
    await connectionsApi.remove(session, 'c1');
    expect(proxy).toHaveBeenCalledWith('DELETE', '/api/connections/c1', undefined);
  });
});
