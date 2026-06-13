// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { AuthSession } from '$lib/bridge/types';

vi.mock('$lib/bridge', () => ({ apiProxy: vi.fn(async () => ({ ok: true })) }));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { sessionStore: writable({ settings: { allowSelfSignedCerts: true } }) };
});

import * as bridge from '$lib/bridge';
import { apiRequest } from './request';

const session: AuthSession = {
  serverUrl: 'https://srv',
  token: 'tok',
  refreshToken: 'r',
  username: 'admin',
  isAdmin: true,
};
const proxy = vi.mocked(bridge.apiProxy);

describe('apiRequest', () => {
  beforeEach(() => proxy.mockClear());

  it('forwards method + path and pins server URL and token', async () => {
    await apiRequest(session, 'GET', '/api/x');
    expect(proxy).toHaveBeenCalledWith('https://srv', 'tok', 'GET', '/api/x', undefined, true);
  });

  it('serializes a body to JSON', async () => {
    await apiRequest(session, 'POST', '/api/x', { a: 1 });
    expect(proxy).toHaveBeenCalledWith('https://srv', 'tok', 'POST', '/api/x', '{"a":1}', true);
  });

  it('passes undefined (not the string "undefined") when there is no body', async () => {
    await apiRequest(session, 'DELETE', '/api/x/1');
    expect(proxy).toHaveBeenCalledWith('https://srv', 'tok', 'DELETE', '/api/x/1', undefined, true);
  });

  it('reads allowSelfSigned from the session store', async () => {
    await apiRequest(session, 'GET', '/api/y');
    expect(proxy.mock.calls.at(-1)?.[5]).toBe(true);
  });

  it('returns the proxy payload unchanged', async () => {
    const r = await apiRequest<{ ok: boolean }>(session, 'GET', '/api/z');
    expect(r).toEqual({ ok: true });
  });
});
