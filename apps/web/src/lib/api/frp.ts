// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { http, requestRaw } from './client';
import type { FrpConfig, FrpConfigInput, FrpStatus } from './types';

export function listConfigs(): Promise<FrpConfig[]> {
  return http.get<FrpConfig[]>('/api/frp/server-config');
}

export function createConfig(data: FrpConfigInput): Promise<FrpConfig> {
  return http.post<FrpConfig>('/api/frp/server-config', data);
}

export function updateConfig(id: string, data: FrpConfigInput): Promise<FrpConfig> {
  return http.put<FrpConfig>(`/api/frp/server-config/${encodeURIComponent(id)}`, data);
}

// Text/blob endpoints (the JSON http client can't carry them) still go through
// the shared requestRaw so they get the same transparent 401 -> refresh -> retry.
async function fetchOk(path: string): Promise<Response> {
  const res = await requestRaw(path);
  if (!res.ok) {
    let detail: string | null = null;
    try {
      const data = await res.json();
      if (data && typeof data.detail === 'string') detail = data.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail ?? `HTTP ${res.status}`);
  }
  return res;
}

export function getFrpsToml(): Promise<string> {
  return fetchOk('/api/frp/generate/frps-toml').then((r) => r.text());
}

export function getVisitorToml(): Promise<string> {
  return fetchOk('/api/frp/generate/visitor-toml').then((r) => r.text());
}

export function getBulkZip(): Promise<Blob> {
  return fetchOk('/api/frp/generate/bulk-zip').then((r) => r.blob());
}

export function status(): Promise<FrpStatus> {
  return http.get<FrpStatus>('/api/frp/status');
}
