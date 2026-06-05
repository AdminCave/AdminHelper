// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { http, getAccessToken } from './client';
import type { Connection, ConnectionImportResult } from './types';

export function list(): Promise<Connection[]> {
  return http.get<Connection[]>('/api/connections');
}

export function create(data: Partial<Connection>): Promise<Connection> {
  return http.post<Connection>('/api/connections', data);
}

export function update(id: string, data: Partial<Connection>): Promise<Connection> {
  return http.put<Connection>(`/api/connections/${id}`, data);
}

export function remove(id: string): Promise<void> {
  return http.del<void>(`/api/connections/${id}`);
}

export async function exportConnections(): Promise<Blob> {
  const token = getAccessToken();
  const res = await fetch('/api/connections/export', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.blob();
}

export function importConnections(
  connections: unknown[],
  mode: 'merge' | 'replace',
): Promise<ConnectionImportResult> {
  return http.post<ConnectionImportResult>('/api/connections/import', { connections, mode });
}
