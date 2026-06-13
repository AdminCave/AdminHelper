// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { AuthSession } from '$lib/bridge/types';
import type { FrpTunnelInput } from '$lib/api/types';

vi.mock('$lib/bridge', () => ({ apiProxy: vi.fn(async () => ({})) }));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { sessionStore: writable({ settings: { allowSelfSignedCerts: false } }) };
});

import * as bridge from '$lib/bridge';
import { frpApi } from './frp';

const session: AuthSession = {
  serverUrl: 'https://srv',
  token: 'tok',
  refreshToken: 'r',
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
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'GET',
      '/api/frp/server-config',
      undefined,
      false,
    );
  });

  it('listTunnels → GET /api/frp/tunnels', async () => {
    await frpApi.listTunnels(session);
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'GET',
      '/api/frp/tunnels',
      undefined,
      false,
    );
  });

  it('createTunnel → POST /api/frp/tunnels with serialized body', async () => {
    await frpApi.createTunnel(session, tunnel);
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'POST',
      '/api/frp/tunnels',
      JSON.stringify(tunnel),
      false,
    );
  });

  it('updateTunnel → PUT /api/frp/tunnels/:id', async () => {
    await frpApi.updateTunnel(session, 't1', tunnel);
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'PUT',
      '/api/frp/tunnels/t1',
      JSON.stringify(tunnel),
      false,
    );
  });

  it('removeTunnel → DELETE /api/frp/tunnels/:id', async () => {
    await frpApi.removeTunnel(session, 't1');
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'DELETE',
      '/api/frp/tunnels/t1',
      undefined,
      false,
    );
  });

  it('status → GET /api/frp/status', async () => {
    await frpApi.status(session);
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'GET',
      '/api/frp/status',
      undefined,
      false,
    );
  });
});
