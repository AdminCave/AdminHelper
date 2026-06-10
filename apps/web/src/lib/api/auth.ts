// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { http, setAccessToken, clearTokens } from './client';
import type { LoginResponse, User } from './types';

export async function login(username: string, password: string): Promise<User> {
  const tokens = await http.post<LoginResponse>('/api/auth/login', { username, password });
  // The refresh token is set by the server as an HttpOnly cookie; only the
  // short-lived access token is kept client-side.
  setAccessToken(tokens.access_token);
  return me();
}

export async function logout(): Promise<void> {
  try {
    // The refresh cookie is sent automatically and cleared by the server.
    await http.post('/api/auth/logout');
  } catch {
    // The local clear must happen in any case (e.g. if the server is unreachable).
  } finally {
    clearTokens();
  }
}

export function me(): Promise<User> {
  return http.get<User>('/api/auth/me');
}
