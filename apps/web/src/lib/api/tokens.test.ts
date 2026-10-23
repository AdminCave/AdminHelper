// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The browser keeps the refresh token only in the HttpOnly cookie: for a browser request the
// server sends `refresh_token` as an empty string, and the web types do not declare the field.

import { describe, it, expect, afterEach, vi } from 'vitest';
import { login } from './auth';
import type { LoginResponse, RefreshResponse } from './types';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

interface FetchCall {
  path: string;
  method: string;
  body: string | null;
  authorization: string | null;
}

function storageKeys(storage: Storage): string[] {
  return Array.from({ length: storage.length }, (_, i) => storage.key(i) ?? '');
}

describe('token responses', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
    sessionStorage.clear();
  });

  it('signs in with the browser answer and stores no refresh token', async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const headers = (init?.headers ?? {}) as Record<string, string>;
        const path = String(input);
        calls.push({
          path,
          method: init?.method ?? 'GET',
          body: typeof init?.body === 'string' ? init.body : null,
          authorization: headers.Authorization ?? null,
        });
        if (path === '/api/auth/login') {
          return Promise.resolve(
            jsonResponse({ access_token: 'a1', refresh_token: '', token_type: 'bearer' }),
          );
        }
        if (path === '/api/auth/me') {
          return Promise.resolve(
            jsonResponse({ id: 1, username: 'admin', is_admin: true, idle_timeout_minutes: 30 }),
          );
        }
        return Promise.resolve(jsonResponse({ detail: 'unexpected' }, 500));
      }),
    );

    const user = await login('admin', 'pw');

    expect(user).toMatchObject({ id: 1, username: 'admin', is_admin: true });
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      'POST /api/auth/login',
      'GET /api/auth/me',
    ]);
    expect(JSON.parse(calls[0].body ?? 'null')).toEqual({ username: 'admin', password: 'pw' });
    expect(calls[1].authorization).toBe('Bearer a1');
    expect(storageKeys(localStorage).filter((k) => k.includes('refresh'))).toEqual([]);
    expect(storageKeys(sessionStorage).filter((k) => k.includes('refresh'))).toEqual([]);
  });

  // `npm run check` (svelte-check) type-checks this file: each directive below fails the check
  // as soon as its line stops being a type error, i.e. when refresh_token comes back to a type.
  it('declares no refresh_token in LoginResponse and RefreshResponse', () => {
    const loginBody: LoginResponse = { access_token: 'a1', token_type: 'bearer' };
    const refreshBody: RefreshResponse = { access_token: 'a2', token_type: 'bearer' };
    // @ts-expect-error the browser keeps the refresh token only in the HttpOnly cookie
    expect(loginBody.refresh_token).toBeUndefined();
    // @ts-expect-error the browser keeps the refresh token only in the HttpOnly cookie
    expect(refreshBody.refresh_token).toBeUndefined();
  });
});
