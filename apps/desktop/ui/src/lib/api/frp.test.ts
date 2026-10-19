// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { AuthSession } from '$lib/bridge/types';
import type { FrpTunnelInput } from '$lib/api/types';

vi.mock('$lib/bridge', () => ({ apiProxy: vi.fn(async () => ({})) }));

import * as bridge from '$lib/bridge';
import { frpApi } from './frp';

const session: AuthSession = {
  serverUrl: 'https://srv',
  username: 'admin',
  isAdmin: true,
};
const proxy = vi.mocked(bridge.apiProxy);
const tunnel: FrpTunnelInput = {
  server_id: 's1',
  frp_config_id: 'f1',
  name: 'ssh',
  tunnel_type: 'stcp',
  protocol: 'ssh',
  local_ip: '127.0.0.1',
  local_port: 22,
  auto_create_connection: true,
  tags: [],
};

describe('frpApi', () => {
  beforeEach(() => proxy.mockClear());

  it('listConfigs → GET /api/frp/server-config', async () => {
    await frpApi.listConfigs(session);
    expect(proxy).toHaveBeenCalledWith('GET', '/api/frp/server-config', undefined);
  });

  it('listTunnels → GET /api/frp/tunnels', async () => {
    await frpApi.listTunnels(session);
    expect(proxy).toHaveBeenCalledWith('GET', '/api/frp/tunnels', undefined);
  });

  it('createTunnel → POST /api/frp/tunnels with serialized body', async () => {
    await frpApi.createTunnel(session, tunnel);
    expect(proxy).toHaveBeenCalledWith('POST', '/api/frp/tunnels', JSON.stringify(tunnel));
  });

  it('updateTunnel → PUT /api/frp/tunnels/:id', async () => {
    await frpApi.updateTunnel(session, 't1', tunnel);
    expect(proxy).toHaveBeenCalledWith('PUT', '/api/frp/tunnels/t1', JSON.stringify(tunnel));
  });

  it('removeTunnel → DELETE /api/frp/tunnels/:id', async () => {
    await frpApi.removeTunnel(session, 't1');
    expect(proxy).toHaveBeenCalledWith('DELETE', '/api/frp/tunnels/t1', undefined);
  });

  it('status → GET /api/frp/status', async () => {
    await frpApi.status(session);
    expect(proxy).toHaveBeenCalledWith('GET', '/api/frp/status', undefined);
  });
});
