// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { http } from './client';
import type {
  Hook,
  HookCreate,
  HookCreateResult,
  HookDetail,
  HookRunResult,
  HookTokenResult,
  HookUpdate,
} from './types';

export function list(): Promise<Hook[]> {
  return http.get<Hook[]>('/api/hooks');
}

export function get(id: string): Promise<HookDetail> {
  return http.get<HookDetail>(`/api/hooks/${id}`);
}

export function create(data: HookCreate): Promise<HookCreateResult> {
  return http.post<HookCreateResult>('/api/hooks', data);
}

export function update(id: string, data: HookUpdate): Promise<HookDetail> {
  return http.put<HookDetail>(`/api/hooks/${id}`, data);
}

export function remove(id: string): Promise<void> {
  return http.del<void>(`/api/hooks/${id}`);
}

export function toggle(id: string): Promise<Hook> {
  return http.post<Hook>(`/api/hooks/${id}/toggle`, {});
}

export function run(id: string): Promise<HookRunResult> {
  return http.post<HookRunResult>(`/api/hooks/${id}/run`, {});
}

export function rotate(id: string): Promise<HookTokenResult> {
  return http.post<HookTokenResult>(`/api/hooks/${id}/rotate`, {});
}
