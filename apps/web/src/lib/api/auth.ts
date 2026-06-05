// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { http, setTokens, clearTokens, getRefreshToken } from './client';
import type { LoginResponse, User } from './types';

export async function login(username: string, password: string): Promise<User> {
  const tokens = await http.post<LoginResponse>('/api/auth/login', { username, password });
  setTokens(tokens.access_token, tokens.refresh_token);
  return me();
}

export async function logout(): Promise<void> {
  const refresh = getRefreshToken();
  try {
    await http.post('/api/auth/logout', refresh ? { refresh_token: refresh } : undefined);
  } catch {
    // The local clear must happen in any case (e.g. if the server is unreachable).
  } finally {
    clearTokens();
  }
}

export function me(): Promise<User> {
  return http.get<User>('/api/auth/me');
}
