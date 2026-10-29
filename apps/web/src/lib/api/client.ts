// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { tNow } from '$lib/i18n';
import { storageRemove } from '$lib/utils/storage';
import { ApiError, type HttpMethod, type RefreshResponse } from './types';

// The long-lived refresh token lives in an HttpOnly cookie (set by the server),
// out of reach of JavaScript/XSS. The short-lived access token is kept ONLY in
// this module's memory — never in localStorage/sessionStorage — so an XSS cannot
// exfiltrate it from persistent storage. On a fresh page load the access token
// is gone; the app rehydrates it via tryRefresh() (the refresh cookie survives).
// Purge any access/refresh-token copies left in storage by an older build.
storageRemove('adminhelper_token');
storageRemove('adminhelper_refresh_token');

let accessToken: string | null = null;
let refreshInFlight: { session: number; promise: Promise<boolean> } | null = null;
let onAuthFailure: (() => void) | null = null;

const REQUEST_TIMEOUT_MS = 15_000;

export interface RequestOptions {
  timeoutMs?: number;
}

// Abort a hung request (dead nginx upstream / no TCP response) after a bounded time instead of
// waiting minutes for the browser's internal timeout — otherwise 'submitting' stays true, save
// buttons stay disabled, login hangs, and hydrate() blocks the boot spinner forever (4.74).
async function fetchWithTimeout(
  input: string,
  init?: RequestInit,
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<Response> {
  try {
    return await fetch(input, { ...init, signal: AbortSignal.timeout(timeoutMs) });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'TimeoutError') {
      throw new ApiError(0, tNow('error.timeout'));
    }
    throw err;
  }
}

export function getAccessToken(): string | null {
  return accessToken;
}

// A session starts with every setAccessToken() (a login, also one while a token is still held) and
// ends with clearTokens(); a refresh keeps it. A request answered 401 after its session ended must not refresh,
// retry or run the auth-failure handler: the handler ends the session that is current by then,
// refresh cookie included (stores/auth.ts).
let session = 0;

export function setAccessToken(access: string): void {
  session++;
  accessToken = access;
}

export function clearTokens(): void {
  session++;
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

// refreshInFlight bundles only within this tab, but all tabs share the refresh cookie. The server
// rotates the refresh token and treats a second refresh with the same token as reuse: every
// session of the user ends (R-0649). A logout blocks the cookie, so a refresh that still sends it
// counts as reuse too. A Web Lock holds per origin across all tabs: the refreshes and the logout
// (auth.ts) run under it one after another, and a tab that gets the lock after another one
// already sends the new cookie. Web Locks exist only in secure contexts (HTTPS, localhost);
// without them fn runs at once. Web Locks are not reentrant: fn must never wait for tryRefresh,
// which would wait for the lock fn holds. A request to an /auth/ path never calls tryRefresh.
export async function withAuthLock<T>(fn: () => Promise<T>): Promise<T> {
  if ('locks' in navigator) {
    return await navigator.locks.request('adminhelper-auth-refresh', fn);
  }
  return await fn();
}

async function tryRefresh(): Promise<boolean> {
  // A refresh started in an earlier session answers for that session only (refresh() returns false
  // once it ended): a request of the current one must not take its answer.
  if (refreshInFlight?.session === session) return refreshInFlight.promise;

  const started = session;
  const refresh = async (): Promise<boolean> => {
    // The refresh token rides along as the HttpOnly cookie (same-origin
    // request → sent automatically); the body is intentionally empty.
    const res = await fetchWithTimeout('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    if (!res.ok) return false;
    const data = (await res.json()) as RefreshResponse;
    // A refresh renews the session that asked for it, also one without a token yet: no new session.
    // One answered after that session ended (also one that waited for the lock across a login) sets
    // no token: it would replace the token of the session current by then.
    if (started !== session) return false;
    accessToken = data.access_token;
    return true;
  };

  const promise = (async () => {
    try {
      return await withAuthLock(refresh);
    } catch {
      return false;
    } finally {
      // session only grows, so at most one refresh per session is in flight: a later session's stays.
      if (refreshInFlight?.session === started) refreshInFlight = null;
    }
  })();
  refreshInFlight = { session: started, promise };
  return promise;
}

async function request<T>(
  method: HttpMethod,
  path: string,
  body?: unknown,
  opts?: RequestOptions,
): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const jsonBody = body !== undefined ? JSON.stringify(body) : undefined;

  const started = session;
  let res = await fetchWithTimeout(path, { method, headers, body: jsonBody }, opts?.timeoutMs);

  if (res.status === 401 && !path.includes('/auth/')) {
    const refreshed = started === session && (await tryRefresh());
    if (started !== session) throw new ApiError(401, 'Session expired');
    if (refreshed && accessToken) {
      headers.Authorization = `Bearer ${accessToken}`;
      res = await fetchWithTimeout(path, { method, headers, body: jsonBody }, opts?.timeoutMs);
    } else {
      onAuthFailure?.();
      throw new ApiError(401, 'Session expired');
    }
  }

  if (res.status === 204) return null as T;

  let data: unknown;
  let unreadable = false;
  try {
    data = await res.json();
  } catch {
    data = null;
    unreadable = true;
  }

  if (!res.ok) {
    const code = errorCode(data);
    const message = withoutCodePrefix(errorDetail(data), code);
    throw new ApiError(res.status, message ?? `HTTP ${res.status}`, data, code);
  }

  // A 2xx promises a T. A body that could not be read — cut off by a reload
  // mid-transfer, or not JSON at all — is not one: as null it reached the list
  // pages and crashed them on `.length` (R-0107). A JSON null stays null.
  if (unreadable) throw new ApiError(res.status, 'Invalid response body');

  return data as T;
}

// The message of an error body: a string detail as it is, or a 422 in the format the
// OpenAPI promises (HTTPValidationError, R-0207), a list of {loc, msg, type}, as its msg
// texts. Anything else has no message of its own.
function errorDetail(data: unknown): string | null {
  if (!data || typeof data !== 'object' || !('detail' in data)) return null;
  const { detail } = data;
  if (typeof detail === 'string') return detail;
  if (!Array.isArray(detail)) return null;
  const msgs = detail
    .map((d: unknown) =>
      d && typeof d === 'object' && 'msg' in d && typeof d.msg === 'string' ? d.msg : null,
    )
    .filter((m): m is string => m !== null);
  return msgs.length ? msgs.join('; ') : null;
}

// The stable code of an error body (R-0664), only in the form the server promises.
const ERROR_CODE = /^ERR_[A-Z0-9_]{1,64}$/;

function errorCode(data: unknown): string | undefined {
  if (!data || typeof data !== 'object' || !('code' in data)) return undefined;
  const { code } = data;
  return typeof code === 'string' && ERROR_CODE.test(code) ? code : undefined;
}

// The server keeps the code as prefix of the detail for clients that read the text; with
// the code at hand the message is the text alone.
function withoutCodePrefix(message: string | null, code: string | undefined): string | null {
  if (message === null || code === undefined) return message;
  const prefix = `${code}: `;
  return message.startsWith(prefix) ? message.slice(prefix.length) : message;
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

  const started = session;
  let res = await doFetch();
  if (res.status === 401 && !path.includes('/auth/')) {
    const refreshed = started === session && (await tryRefresh());
    if (started !== session) throw new ApiError(401, 'Session expired');
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
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>('POST', path, body, opts),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
};
