// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { http } from './client';
import type { EnrollmentGrant, User, UserCreate, UserUpdate } from './types';

export function list(): Promise<User[]> {
  return http.get<User[]>('/api/users');
}

export function create(data: UserCreate): Promise<User> {
  return http.post<User>('/api/users', data);
}

export function update(id: number, data: UserUpdate): Promise<User> {
  return http.put<User>(`/api/users/${encodeURIComponent(id)}`, data);
}

export function remove(id: number): Promise<void> {
  return http.del<void>(`/api/users/${encodeURIComponent(id)}`);
}

// No `browser` flag on purpose: the web panel never mints a long-lived browser leaf; that stays
// with the API (R-0396). The server CLI cannot mint one either.
export function mintEnrollToken(username: string, ttlMinutes: number): Promise<EnrollmentGrant> {
  return http.post<EnrollmentGrant>('/api/enrollment/token/for', {
    username,
    ttl_minutes: ttlMinutes,
  });
}
