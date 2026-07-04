// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Tests for the token-refresh / 401-retry logic in client.ts.
// client.ts touches localStorage at module load and keeps module-level state
// (accessToken, refreshInFlight), so every test re-imports a fresh module
// instance after stubbing localStorage and fetch.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { ApiError } from './types';

type ClientModule = typeof import('./client');

const TOKEN_KEY = 'adminhelper_token';

function createLocalStorageStub(initial: Record<string, string> = {}): Storage {
  const store = new Map<string, string>(Object.entries(initial));
  return {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key: string) => store.get(key) ?? null,
    key: (index: number) => [...store.keys()][index] ?? null,
    removeItem: (key: string) => {
      store.delete(key);
    },
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

interface FetchCall {
  path: string;
  method: string;
  authorization: string | null;
}

function recordCall(calls: FetchCall[], input: RequestInfo | URL, init?: RequestInit): void {
  const headers = (init?.headers ?? {}) as Record<string, string>;
  calls.push({
    path: String(input),
    method: init?.method ?? 'GET',
    authorization: headers.Authorization ?? null,
  });
}

async function importClient(): Promise<ClientModule> {
  vi.resetModules();
  return import('./client');
}

describe('http client token refresh', () => {
  let calls: FetchCall[];

  beforeEach(() => {
    calls = [];
    vi.stubGlobal('localStorage', createLocalStorageStub({ [TOKEN_KEY]: 'old-token' }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('retries the original request with the new token after a successful refresh', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        recordCall(calls, input, init);
        const path = String(input);
        if (path === '/api/auth/refresh') {
          return Promise.resolve(jsonResponse({ access_token: 'new-token' }));
        }
        // First data request: 401; retry after refresh: 200.
        const isRetry = calls.filter((c) => c.path === path).length > 1;
        return Promise.resolve(
          isRetry ? jsonResponse({ ok: true }) : jsonResponse({ detail: 'expired' }, 401),
        );
      }),
    );

    const { http, getAccessToken, setAccessToken } = await importClient();
    // The access token lives only in memory now (never localStorage); seed it
    // the way a real login/restoreSession would.
    setAccessToken('old-token');
    const result = await http.get<{ ok: boolean }>('/api/servers');

    expect(result).toEqual({ ok: true });
    expect(calls.map((c) => c.path)).toEqual(['/api/servers', '/api/auth/refresh', '/api/servers']);
    expect(calls[0].authorization).toBe('Bearer old-token');
    expect(calls[2].authorization).toBe('Bearer new-token');
    expect(getAccessToken()).toBe('new-token');
    // The token must NOT be persisted (XSS-exfiltration hardening).
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it('calls the auth-failure handler and throws when the refresh fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        recordCall(calls, input, init);
        return Promise.resolve(jsonResponse({ detail: 'nope' }, 401));
      }),
    );

    const { http, registerAuthFailureHandler } = await importClient();
    const onAuthFailure = vi.fn();
    registerAuthFailureHandler(onAuthFailure);

    const err = await http.get('/api/servers').catch((e: unknown) => e);

    // vi.resetModules() gives client.ts its own types.ts instance, so an
    // instanceof check against the statically imported ApiError would fail.
    expect(err).toBeInstanceOf(Error);
    const apiErr = err as ApiError;
    expect(apiErr.name).toBe('ApiError');
    expect(apiErr.status).toBe(401);
    expect(apiErr.message).toBe('Session expired');
    expect(onAuthFailure).toHaveBeenCalledTimes(1);
    // No retry of the original request after a failed refresh.
    expect(calls.map((c) => c.path)).toEqual(['/api/servers', '/api/auth/refresh']);
  });

  it('deduplicates concurrent 401s into a single refresh call', async () => {
    let resolveRefresh: (res: Response) => void = () => {};
    const refreshGate = new Promise<Response>((resolve) => {
      resolveRefresh = resolve;
    });
    let refreshCalls = 0;

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        recordCall(calls, input, init);
        const path = String(input);
        if (path === '/api/auth/refresh') {
          refreshCalls += 1;
          return refreshGate;
        }
        const isRetry = calls.filter((c) => c.path === path).length > 1;
        return Promise.resolve(
          isRetry ? jsonResponse({ path }) : jsonResponse({ detail: 'expired' }, 401),
        );
      }),
    );

    const { http } = await importClient();
    const reqA = http.get<{ path: string }>('/api/a');
    const reqB = http.get<{ path: string }>('/api/b');

    // Wait until both 401 responses have been processed and the (single)
    // refresh request is pending, then let it succeed.
    await vi.waitFor(() => {
      expect(refreshCalls).toBe(1);
      expect(calls.filter((c) => c.path !== '/api/auth/refresh')).toHaveLength(2);
    });
    resolveRefresh(jsonResponse({ access_token: 'new-token' }));

    const [a, b] = await Promise.all([reqA, reqB]);
    expect(a).toEqual({ path: '/api/a' });
    expect(b).toEqual({ path: '/api/b' });
    expect(refreshCalls).toBe(1);
    expect(calls.filter((c) => c.path === '/api/a')).toHaveLength(2);
    expect(calls.filter((c) => c.path === '/api/b')).toHaveLength(2);
    for (const retry of calls.slice(-2)) {
      expect(retry.authorization).toBe('Bearer new-token');
    }
  });

  it('returns null for 204 responses', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        recordCall(calls, input, init);
        return Promise.resolve(new Response(null, { status: 204 }));
      }),
    );

    const { http, setAccessToken } = await importClient();
    setAccessToken('old-token');
    const result = await http.del<null>('/api/servers/123');

    expect(result).toBeNull();
    expect(calls).toEqual([
      { path: '/api/servers/123', method: 'DELETE', authorization: 'Bearer old-token' },
    ]);
  });

  it('requestRaw retries a text endpoint with the new token after refresh (1.32)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        recordCall(calls, input, init);
        const path = String(input);
        if (path === '/api/auth/refresh') {
          return Promise.resolve(jsonResponse({ access_token: 'new-token' }));
        }
        // First: 401; retry after refresh returns a TEXT body (frps.toml preview).
        const isRetry = calls.filter((c) => c.path === path).length > 1;
        return Promise.resolve(
          isRetry
            ? new Response('bindPort = 7000', { status: 200 })
            : jsonResponse({ detail: 'expired' }, 401),
        );
      }),
    );

    const { requestRaw, setAccessToken } = await importClient();
    setAccessToken('old-token');
    const res = await requestRaw('/api/frp/generate/frps-toml');

    expect(res.ok).toBe(true);
    expect(await res.text()).toBe('bindPort = 7000');
    expect(calls.map((c) => c.path)).toEqual([
      '/api/frp/generate/frps-toml',
      '/api/auth/refresh',
      '/api/frp/generate/frps-toml',
    ]);
    expect(calls[2].authorization).toBe('Bearer new-token');
  });
});
