// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Tests for the token-refresh / 401-retry logic in client.ts.
// client.ts touches localStorage at module load and keeps module-level state
// (accessToken, refreshInFlight), so every test re-imports a fresh module
// instance after stubbing localStorage and fetch.

import { describe, it, expect, beforeEach, afterEach, vi, type MockInstance } from 'vitest';
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

  // A 2xx promises a T. A body that cannot be read is not one: returning null here
  // reached the list pages as a list, and `.length` on it became the pageerror the
  // live smoke found when it reloaded mid-request (R-0107).
  it('rejects a 200 whose body stream aborts with an ApiError, not null (R-0107)', async () => {
    const aborted = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.error(new DOMException('The operation was aborted.', 'AbortError'));
      },
    });
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response(aborted, { status: 200 }))),
    );

    const { http } = await importClient();
    const err = await http.get('/api/users').catch((e: unknown) => e);

    expect(err).toBeInstanceOf(Error);
    const apiErr = err as ApiError;
    expect(apiErr.name).toBe('ApiError');
    expect(apiErr.status).toBe(200);
    expect(apiErr.message).toBe('Invalid response body');
  });

  it('rejects a 200 with an empty body with an ApiError, not null (R-0107)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response('', { status: 200 }))),
    );

    const { http } = await importClient();
    const err = await http.get('/api/users').catch((e: unknown) => e);

    expect(err).toBeInstanceOf(Error);
    const apiErr = err as ApiError;
    expect(apiErr.name).toBe('ApiError');
    expect(apiErr.status).toBe(200);
    expect(apiErr.message).toBe('Invalid response body');
  });

  it('still returns a JSON null body as null', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(jsonResponse(null))),
    );

    const { http } = await importClient();
    await expect(http.get<null>('/api/something')).resolves.toBeNull();
  });

  it('translates a request timeout into an ApiError with status 0 (4.74)', async () => {
    // A hung server (dead upstream, no response) makes AbortSignal.timeout fire a TimeoutError;
    // it must surface as an ApiError so the UI can unstick, not propagate as a raw DOMException.
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new DOMException('timed out', 'TimeoutError'))),
    );

    const { http } = await importClient();
    // The i18n instance client.ts loaded with it (vi.resetModules gave both a fresh one).
    const { tNow } = await import('$lib/i18n');
    const err = await http.get('/api/servers').catch((e: unknown) => e);

    expect(err).toBeInstanceOf(Error);
    const apiErr = err as ApiError;
    expect(apiErr.name).toBe('ApiError');
    expect(apiErr.status).toBe(0);
    // Translated (R-0648): the login form and showError show the message as it is.
    expect(apiErr.message).toBe(tNow('error.timeout'));
    expect(apiErr.message).not.toBe('Request timed out');
    expect(apiErr.message).not.toBe('error.timeout');
  });

  it('does not refresh-retry a 401 from an /auth/ path, preserving the server message (6.85)', async () => {
    // Login.svelte relies on the server's own message ('Invalid credentials') reaching the caller
    // instead of 'Session expired'. The `!path.includes('/auth/')` guard is what makes that hold —
    // a 401 on an /auth/ path must NOT trigger a refresh.
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        recordCall(calls, input, init);
        return Promise.resolve(jsonResponse({ detail: 'Invalid credentials' }, 401));
      }),
    );

    const { http, setAccessToken } = await importClient();
    setAccessToken('old-token');
    const err = await http
      .post('/api/auth/login', { username: 'x', password: 'y' })
      .catch((e: unknown) => e);

    const apiErr = err as ApiError;
    expect(apiErr.status).toBe(401);
    expect(apiErr.message).toBe('Invalid credentials'); // NOT 'Session expired'
    expect(calls.map((c) => c.path)).toEqual(['/api/auth/login']); // no /api/auth/refresh
  });

  it('treats a network error during refresh as a failed refresh (6.85)', async () => {
    // The catch in tryRefresh (fetch throws, not just a non-ok response) must map to a failed
    // refresh -> auth-failure handler + 'Session expired', not an unhandled rejection.
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        recordCall(calls, input, init);
        if (String(input) === '/api/auth/refresh') {
          return Promise.reject(new TypeError('network down'));
        }
        return Promise.resolve(jsonResponse({ detail: 'expired' }, 401));
      }),
    );

    const { http, registerAuthFailureHandler, setAccessToken } = await importClient();
    setAccessToken('old-token');
    const onAuthFailure = vi.fn();
    registerAuthFailureHandler(onAuthFailure);

    const err = await http.get('/api/servers').catch((e: unknown) => e);

    const apiErr = err as ApiError;
    expect(apiErr.status).toBe(401);
    expect(apiErr.message).toBe('Session expired');
    expect(onAuthFailure).toHaveBeenCalledTimes(1);
    expect(calls.map((c) => c.path)).toEqual(['/api/servers', '/api/auth/refresh']); // no retry
  });
});

// The server runs a manual hook synchronously, longer than the 15 s that unstick a hung
// upstream; hooks.run gets its own deadline, every other request keeps 15 s (R-0648).
describe('http client request deadline', () => {
  let calls: FetchCall[];
  let timeoutSpy: MockInstance<typeof AbortSignal.timeout>;

  beforeEach(() => {
    calls = [];
    timeoutSpy = vi.spyOn(AbortSignal, 'timeout');
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        recordCall(calls, input, init);
        return Promise.resolve(jsonResponse({}));
      }),
    );
  });

  afterEach(() => {
    timeoutSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  it('gives a post the deadline it asks for and any other request 15 s', async () => {
    const { http } = await importClient();

    await http.post('/api/x', {}, { timeoutMs: 75_000 });
    expect(timeoutSpy).toHaveBeenCalledTimes(1);
    expect(timeoutSpy).toHaveBeenLastCalledWith(75_000);

    await http.get('/api/x');
    expect(timeoutSpy).toHaveBeenCalledTimes(2);
    expect(timeoutSpy).toHaveBeenLastCalledWith(15_000);
  });

  it('runs a hook with a 75 s deadline', async () => {
    vi.resetModules();
    const { run } = await import('./hooks');

    await run('h/1');

    expect(calls.map((c) => [c.method, c.path])).toEqual([['POST', '/api/hooks/h%2F1/run']]);
    expect(timeoutSpy).toHaveBeenCalledTimes(1);
    expect(timeoutSpy).toHaveBeenCalledWith(75_000);
  });
});

describe('http client error messages', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function errorOf(body: unknown, status = 422): Promise<ApiError> {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(jsonResponse(body, status))),
    );
    const { http } = await importClient();
    const err = await http.get('/api/hooks').catch((e: unknown) => e);
    expect((err as ApiError).name).toBe('ApiError');
    return err as ApiError;
  }

  async function messageOf(body: unknown, status = 422): Promise<string> {
    return (await errorOf(body, status)).message;
  }

  // The OpenAPI promises HTTPValidationError for a 422 (R-0207): a list of
  // {loc, msg, type}. Its msg texts are the message, not "HTTP 422".
  it('shows the msg of a 422 detail list', async () => {
    const body = {
      detail: [
        { loc: ['body', 'schedule_interval'], msg: 'Ungültiges Intervall', type: 'value_error' },
      ],
    };
    expect(await messageOf(body)).toBe('Ungültiges Intervall');
  });

  it('joins several msg texts', async () => {
    const body = {
      detail: [
        { loc: ['body', 'a'], msg: 'first', type: 'value_error' },
        { loc: ['body', 'b'], msg: 'second', type: 'missing' },
      ],
    };
    expect(await messageOf(body)).toBe('first; second');
  });

  it('keeps a string detail as it is', async () => {
    expect(await messageOf({ detail: 'Hook nicht gefunden' }, 404)).toBe('Hook nicht gefunden');
  });

  it('falls back to the status when the list carries no msg', async () => {
    expect(await messageOf({ detail: [{ loc: ['body'] }] })).toBe('HTTP 422');
  });

  // R-0664: an error a client reacts to carries a stable code next to the text; the
  // detail keeps the code as prefix for older clients, the message drops it.
  const REVOKED_TEXT = 'This device certificate is no longer valid.';

  it('takes the code and shows the detail without its prefix', async () => {
    const err = await errorOf(
      { detail: `ERR_CERT_REVOKED: ${REVOKED_TEXT}`, code: 'ERR_CERT_REVOKED' },
      403,
    );
    expect(err.message).toBe(REVOKED_TEXT);
    expect(err.code).toBe('ERR_CERT_REVOKED');
    expect(err.status).toBe(403);
  });

  it('keeps the prefix when the server sends no code', async () => {
    const err = await errorOf({ detail: `ERR_CERT_REVOKED: ${REVOKED_TEXT}` }, 403);
    expect(err.message).toBe(`ERR_CERT_REVOKED: ${REVOKED_TEXT}`);
    expect(err.code).toBeUndefined();
  });

  it.each([['err_x'], [42], [`ERR_${'A'.repeat(65)}`]])(
    'ignores a code that is not of the form ERR_… (%s)',
    async (code) => {
      const detail = `${String(code)}: ${REVOKED_TEXT}`;
      const err = await errorOf({ detail, code }, 403);
      expect(err.code).toBeUndefined();
      expect(err.message).toBe(detail);
    },
  );

  it('leaves a detail without the prefix as it is', async () => {
    const err = await errorOf({ detail: REVOKED_TEXT, code: 'ERR_CERT_REVOKED' }, 403);
    expect(err.message).toBe(REVOKED_TEXT);
    expect(err.code).toBe('ERR_CERT_REVOKED');
  });

  it('shows the msg texts of a 422 list that carries a code', async () => {
    const body = {
      detail: [
        { loc: ['body', 'a'], msg: 'first', type: 'value_error' },
        { loc: ['body', 'b'], msg: 'second', type: 'missing' },
      ],
      code: 'ERR_PROBE',
    };
    expect(await messageOf(body)).toBe('first; second');
  });
});

// R-0779: a request started in a session that ended (logout, then a new login) and that answers
// 401 only afterwards belongs to the old session: it must neither refresh, retry with the new
// session's token nor run the auth-failure handler, which would end the new session.
describe('http client: a 401 of a request from an ended session', () => {
  let calls: FetchCall[];

  beforeEach(() => {
    calls = [];
    vi.stubGlobal('localStorage', createLocalStorageStub());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function deferredResponse(): { promise: Promise<Response>; resolve: (r: Response) => void } {
    let resolve!: (r: Response) => void;
    const promise = new Promise<Response>((r) => (resolve = r));
    return { promise, resolve };
  }

  // fetch: the first /api/servers waits for `first`, the refresh answers `refresh` (or waits for it).
  function stubFetch(first: Promise<Response>, refresh: () => Promise<Response>): void {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        recordCall(calls, input, init);
        const path = String(input);
        if (path === '/api/auth/refresh') return refresh();
        if (calls.filter((c) => c.path === path).length === 1) return first;
        return Promise.resolve(jsonResponse({ ok: true }));
      }),
    );
  }

  function expectSessionExpired(err: unknown): void {
    expect(err).toBeInstanceOf(Error);
    expect((err as ApiError).status).toBe(401);
    expect((err as ApiError).message).toBe('Session expired');
  }

  it('does not refresh and leaves the new session alone', async () => {
    const first = deferredResponse();
    stubFetch(first.promise, () => Promise.resolve(jsonResponse({ detail: 'no' }, 401)));
    const { http, setAccessToken, clearTokens, registerAuthFailureHandler } = await importClient();
    const onAuthFailure = vi.fn();
    registerAuthFailureHandler(onAuthFailure);
    setAccessToken('old-token');

    const pending = http.get('/api/servers').catch((e: unknown) => e);
    clearTokens();
    setAccessToken('new-token');
    first.resolve(jsonResponse({ detail: 'expired' }, 401));

    expectSessionExpired(await pending);
    expect(onAuthFailure).not.toHaveBeenCalled();
    expect(calls.map((c) => c.path)).toEqual(['/api/servers']);
  });

  it('is not retried with the new token, even where a refresh would succeed', async () => {
    const first = deferredResponse();
    stubFetch(first.promise, () => Promise.resolve(jsonResponse({ access_token: 'newer' })));
    const { http, setAccessToken, clearTokens, registerAuthFailureHandler } = await importClient();
    const onAuthFailure = vi.fn();
    registerAuthFailureHandler(onAuthFailure);
    setAccessToken('old-token');

    const pending = http.get('/api/servers').catch((e: unknown) => e);
    clearTokens();
    setAccessToken('new-token');
    first.resolve(jsonResponse({ detail: 'expired' }, 401));

    expectSessionExpired(await pending);
    expect(calls.map((c) => c.path)).toEqual(['/api/servers']);
    expect(onAuthFailure).not.toHaveBeenCalled();
  });

  it('a refresh of the old session that fails after the new login leaves the new session alone', async () => {
    const refresh = deferredResponse();
    stubFetch(Promise.resolve(jsonResponse({ detail: 'expired' }, 401)), () => refresh.promise);
    const { http, setAccessToken, clearTokens, registerAuthFailureHandler } = await importClient();
    const onAuthFailure = vi.fn();
    registerAuthFailureHandler(onAuthFailure);
    setAccessToken('old-token');

    const pending = http.get('/api/servers').catch((e: unknown) => e);
    await vi.waitFor(() => expect(calls.map((c) => c.path)).toContain('/api/auth/refresh'));
    clearTokens();
    setAccessToken('new-token');
    refresh.resolve(jsonResponse({ detail: 'no' }, 401));

    expectSessionExpired(await pending);
    expect(onAuthFailure).not.toHaveBeenCalled();
    expect(calls.map((c) => c.path)).toEqual(['/api/servers', '/api/auth/refresh']);
  });

  it('requestRaw: does not refresh and leaves the new session alone', async () => {
    const first = deferredResponse();
    stubFetch(first.promise, () => Promise.resolve(jsonResponse({ detail: 'no' }, 401)));
    const { requestRaw, setAccessToken, clearTokens, registerAuthFailureHandler } =
      await importClient();
    const onAuthFailure = vi.fn();
    registerAuthFailureHandler(onAuthFailure);
    setAccessToken('old-token');

    const pending = requestRaw('/api/servers').catch((e: unknown) => e);
    clearTokens();
    setAccessToken('new-token');
    first.resolve(jsonResponse({ detail: 'expired' }, 401));

    expectSessionExpired(await pending);
    expect(onAuthFailure).not.toHaveBeenCalled();
    expect(calls.map((c) => c.path)).toEqual(['/api/servers']);
  });

  it('a logout alone ends the session for a request still open', async () => {
    const first = deferredResponse();
    stubFetch(first.promise, () => Promise.resolve(jsonResponse({ access_token: 'newer' })));
    const { http, setAccessToken, clearTokens, registerAuthFailureHandler } = await importClient();
    const onAuthFailure = vi.fn();
    registerAuthFailureHandler(onAuthFailure);
    setAccessToken('old-token');

    const pending = http.get('/api/servers').catch((e: unknown) => e);
    clearTokens();
    first.resolve(jsonResponse({ detail: 'expired' }, 401));

    expectSessionExpired(await pending);
    expect(onAuthFailure).not.toHaveBeenCalled();
    expect(calls.map((c) => c.path)).toEqual(['/api/servers']);
  });

  it('a login alone starts a new session for a request sent while logged out', async () => {
    const first = deferredResponse();
    stubFetch(first.promise, () => Promise.resolve(jsonResponse({ access_token: 'newer' })));
    const { http, setAccessToken, registerAuthFailureHandler } = await importClient();
    const onAuthFailure = vi.fn();
    registerAuthFailureHandler(onAuthFailure);

    const pending = http.get('/api/servers').catch((e: unknown) => e);
    setAccessToken('new-token');
    first.resolve(jsonResponse({ detail: 'expired' }, 401));

    expectSessionExpired(await pending);
    expect(onAuthFailure).not.toHaveBeenCalled();
    expect(calls.map((c) => c.path)).toEqual(['/api/servers']);
  });

  it('a refresh answered after the logout sets no token', async () => {
    const refresh = deferredResponse();
    stubFetch(Promise.resolve(jsonResponse({ detail: 'expired' }, 401)), () => refresh.promise);
    const { http, setAccessToken, clearTokens, getAccessToken } = await importClient();
    setAccessToken('old-token');

    const pending = http.get('/api/servers').catch((e: unknown) => e);
    await vi.waitFor(() => expect(calls.map((c) => c.path)).toContain('/api/auth/refresh'));
    clearTokens();
    refresh.resolve(jsonResponse({ access_token: 'late-token' }));

    expectSessionExpired(await pending);
    expect(getAccessToken()).toBeNull();
  });

  it('a new token within the same session still ends it on a failed refresh', async () => {
    const first = deferredResponse();
    stubFetch(first.promise, () => Promise.resolve(jsonResponse({ detail: 'no' }, 401)));
    const { http, setAccessToken, registerAuthFailureHandler } = await importClient();
    const onAuthFailure = vi.fn();
    registerAuthFailureHandler(onAuthFailure);
    setAccessToken('t1');

    const pending = http.get('/api/servers').catch((e: unknown) => e);
    setAccessToken('t2');
    first.resolve(jsonResponse({ detail: 'expired' }, 401));

    expectSessionExpired(await pending);
    expect(onAuthFailure).toHaveBeenCalledTimes(1);
  });
});
