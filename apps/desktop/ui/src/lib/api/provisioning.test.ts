// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { AuthSession } from '$lib/bridge/types';

vi.mock('$lib/bridge', () => ({ apiProxy: vi.fn(async () => ({})) }));

import * as bridge from '$lib/bridge';
import { provisioningApi } from './provisioning';

const session: AuthSession = {
  serverUrl: 'https://srv',
  username: 'admin',
  isAdmin: true,
};
const proxy = vi.mocked(bridge.apiProxy);

describe('provisioningApi', () => {
  beforeEach(() => proxy.mockClear());

  it('listTokens → GET /api/servers/:id/provision/tokens', async () => {
    await provisioningApi.listTokens(session, 's1');
    expect(proxy).toHaveBeenCalledWith('GET', '/api/servers/s1/provision/tokens', undefined);
  });

  it('createToken → POST /api/servers/:id/provision/token', async () => {
    await provisioningApi.createToken(session, 's1');
    expect(proxy).toHaveBeenCalledWith('POST', '/api/servers/s1/provision/token', undefined);
  });
});
