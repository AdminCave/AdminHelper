// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { ApiError, type HttpMethod, type RefreshResponse } from './types';

const TOKEN_KEY = 'adminhelper_token';
const REFRESH_KEY = 'adminhelper_refresh_token';

let accessToken: string | null = localStorage.getItem(TOKEN_KEY);
let refreshInFlight: Promise<boolean> | null = null;
let onAuthFailure: (() => void) | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setTokens(access: string, refresh: string): void {
  accessToken = access;
  localStorage.setItem(TOKEN_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens(): void {
  accessToken = null;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export function registerAuthFailureHandler(handler: () => void): void {
  onAuthFailure = handler;
}

async function tryRefresh(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  const refreshToken = localStorage.getItem(REFRESH_KEY);
  if (!refreshToken) return false;

  refreshInFlight = (async () => {
    try {
      const res = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) return false;
      const data = (await res.json()) as RefreshResponse;
      setTokens(data.access_token, data.refresh_token);
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

  let res = await fetch(path, { method, headers, body: jsonBody });

  if (res.status === 401 && !path.includes('/auth/')) {
    const refreshed = await tryRefresh();
    if (refreshed && accessToken) {
      headers.Authorization = `Bearer ${accessToken}`;
      res = await fetch(path, { method, headers, body: jsonBody });
    } else {
      onAuthFailure?.();
      throw new ApiError(401, 'Session expired');
    }
  }

  if (res.status === 204) return null as T;

  let data: unknown = null;
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

export const http = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
};
