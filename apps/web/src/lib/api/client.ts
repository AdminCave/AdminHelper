// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { ApiError, type HttpMethod, type RefreshResponse } from './types';

// The long-lived refresh token lives in an HttpOnly cookie (set by the server),
// out of reach of JavaScript/XSS. The short-lived access token is kept ONLY in
// this module's memory — never in localStorage/sessionStorage — so an XSS cannot
// exfiltrate it from persistent storage. On a fresh page load the access token
// is gone; the app rehydrates it via tryRefresh() (the refresh cookie survives).
// Purge any access/refresh-token copies left in storage by an older build.
localStorage.removeItem('adminhelper_token');
localStorage.removeItem('adminhelper_refresh_token');

let accessToken: string | null = null;
let refreshInFlight: Promise<boolean> | null = null;
let onAuthFailure: (() => void) | null = null;

const REQUEST_TIMEOUT_MS = 15_000;

// Abort a hung request (dead nginx upstream / no TCP response) after a bounded time instead of
// waiting minutes for the browser's internal timeout — otherwise 'submitting' stays true, save
// buttons stay disabled, login hangs, and hydrate() blocks the boot spinner forever (4.74).
async function fetchWithTimeout(input: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, { ...init, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'TimeoutError') {
      throw new ApiError(0, 'Request timed out');
    }
    throw err;
  }
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(access: string): void {
  accessToken = access;
}

export function clearTokens(): void {
  accessToken = null;
  // The refresh token lives in an HttpOnly cookie, cleared server-side by
  // POST /api/auth/logout.
}

// Rehydrate the in-memory access token from the HttpOnly refresh cookie at app
// start (the access token itself does not survive a reload). Returns true if a
// session was restored. Verified against the server: POST /api/auth/refresh
// accepts the refresh cookie alone, with no prior access token.
export function restoreSession(): Promise<boolean> {
  return tryRefresh();
}

export function registerAuthFailureHandler(handler: () => void): void {
  onAuthFailure = handler;
}

async function tryRefresh(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    try {
      // The refresh token rides along as the HttpOnly cookie (same-origin
      // request → sent automatically); the body is intentionally empty.
      const res = await fetchWithTimeout('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
      if (!res.ok) return false;
      const data = (await res.json()) as RefreshResponse;
      setAccessToken(data.access_token);
      return true;
    } catch {
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

async function request<T>(method: HttpMethod, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const jsonBody = body !== undefined ? JSON.stringify(body) : undefined;

  let res = await fetchWithTimeout(path, { method, headers, body: jsonBody });

  if (res.status === 401 && !path.includes('/auth/')) {
    const refreshed = await tryRefresh();
    if (refreshed && accessToken) {
      headers.Authorization = `Bearer ${accessToken}`;
      res = await fetchWithTimeout(path, { method, headers, body: jsonBody });
    } else {
      onAuthFailure?.();
      throw new ApiError(401, 'Session expired');
    }
  }

  if (res.status === 204) return null as T;

  let data: unknown;
  try {
    data = await res.json();
  } catch {
    data = null;
  }

  if (!res.ok) {
    const message =
      (data && typeof data === 'object' && 'detail' in data && typeof data.detail === 'string'
        ? data.detail
        : null) ?? `HTTP ${res.status}`;
    throw new ApiError(res.status, message, data);
  }

  return data as T;
}

// Raw GET that shares the same 401 -> tryRefresh -> retry path as request(), but
// returns the Response so callers can read text()/blob() (frps.toml preview, bulk
// ZIP). Without this those endpoints bypassed the transparent refresh and surfaced
// a bare HTTP 401 once the short-lived access token expired.
export async function requestRaw(path: string): Promise<Response> {
  const doFetch = () =>
    fetchWithTimeout(path, {
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    });

  let res = await doFetch();
  if (res.status === 401 && !path.includes('/auth/')) {
    const refreshed = await tryRefresh();
    if (refreshed && accessToken) {
      res = await doFetch();
    } else {
      onAuthFailure?.();
      throw new ApiError(401, 'Session expired');
    }
  }
  return res;
}

export const http = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
};
