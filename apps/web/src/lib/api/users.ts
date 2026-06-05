// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { http } from './client';
import type { User, UserCreate, UserUpdate } from './types';

export function list(): Promise<User[]> {
  return http.get<User[]>('/api/users');
}

export function create(data: UserCreate): Promise<User> {
  return http.post<User>('/api/users', data);
}

export function update(id: number, data: UserUpdate): Promise<User> {
  return http.put<User>(`/api/users/${id}`, data);
}

export function remove(id: number): Promise<void> {
  return http.del<void>(`/api/users/${id}`);
}
