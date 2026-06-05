// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { http } from './client';
import type { Server, ServerInput } from './types';

export function list(): Promise<Server[]> {
  return http.get<Server[]>('/api/servers');
}

export function create(data: ServerInput): Promise<Server> {
  return http.post<Server>('/api/servers', data);
}

export function update(id: string, data: ServerInput): Promise<Server> {
  return http.put<Server>(`/api/servers/${id}`, data);
}

export function remove(id: string): Promise<void> {
  return http.del<void>(`/api/servers/${id}`);
}
