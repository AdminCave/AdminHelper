// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { AuthSession } from '$lib/bridge/types';

vi.mock('$lib/bridge', () => ({ apiProxy: vi.fn(async () => ({})) }));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { sessionStore: writable({ settings: { allowSelfSignedCerts: false } }) };
});

import * as bridge from '$lib/bridge';
import { provisioningApi } from './provisioning';

const session: AuthSession = {
  serverUrl: 'https://srv',
  token: 'tok',
  refreshToken: 'r',
  username: 'admin',
  isAdmin: true,
};
const proxy = vi.mocked(bridge.apiProxy);

describe('provisioningApi', () => {
  beforeEach(() => proxy.mockClear());

  it('listTokens → GET /api/servers/:id/provision/tokens', async () => {
    await provisioningApi.listTokens(session, 's1');
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'GET',
      '/api/servers/s1/provision/tokens',
      undefined,
      false,
    );
  });

  it('createToken → POST /api/servers/:id/provision/token', async () => {
    await provisioningApi.createToken(session, 's1');
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'POST',
      '/api/servers/s1/provision/token',
      undefined,
      false,
    );
  });
});
