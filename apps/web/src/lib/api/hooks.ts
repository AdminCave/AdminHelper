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
  return http.get<HookDetail>(`/api/hooks/${encodeURIComponent(id)}`);
}

export function create(data: HookCreate): Promise<HookCreateResult> {
  return http.post<HookCreateResult>('/api/hooks', data);
}

export function update(id: string, data: HookUpdate): Promise<HookDetail> {
  return http.put<HookDetail>(`/api/hooks/${encodeURIComponent(id)}`, data);
}

export function remove(id: string): Promise<void> {
  return http.del<void>(`/api/hooks/${encodeURIComponent(id)}`);
}

export function toggle(id: string): Promise<Hook> {
  return http.post<Hook>(`/api/hooks/${encodeURIComponent(id)}/toggle`, {});
}

// The server runs the hook synchronously: up to 30 s of script
// (apps/server/app/modules/hooks/script_runner.py, SCRIPT_TIMEOUT_SECONDS), then bounded joins
// of its output threads. The gateway cuts a silent response after nginx's default 60 s
// (apps/gateway/nginx.conf sets proxy_read_timeout only for the SSE stream). 75 s lies above
// the script plus one join pass and above the gateway's cut: the client's 15 s default gave
// up first, lost the result and freed the run button while the hook was still running (R-0648).
const RUN_TIMEOUT_MS = 75_000;

export function run(id: string): Promise<HookRunResult> {
  return http.post<HookRunResult>(
    `/api/hooks/${encodeURIComponent(id)}/run`,
    {},
    { timeoutMs: RUN_TIMEOUT_MS },
  );
}

export function rotate(id: string): Promise<HookTokenResult> {
  return http.post<HookTokenResult>(`/api/hooks/${encodeURIComponent(id)}/rotate`, {});
}
