// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { http } from './client';
import type { ApiKey, ApiKeyCreate, ApiKeyCreateResult } from './types';

export function list(): Promise<ApiKey[]> {
  return http.get<ApiKey[]>('/api/api-keys');
}

export function create(data: ApiKeyCreate): Promise<ApiKeyCreateResult> {
  return http.post<ApiKeyCreateResult>('/api/api-keys', data);
}

export function remove(id: number): Promise<void> {
  return http.del<void>(`/api/api-keys/${id}`);
}
