// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { http, getAccessToken } from './client';
import type {
  FrpConfig,
  FrpConfigInput,
  FrpTunnel,
  FrpTunnelInput,
  FrpPkiStatus,
  FrpStatus,
} from './types';

export function listConfigs(): Promise<FrpConfig[]> {
  return http.get<FrpConfig[]>('/api/frp/server-config');
}

export function createConfig(data: FrpConfigInput): Promise<FrpConfig> {
  return http.post<FrpConfig>('/api/frp/server-config', data);
}

export function updateConfig(id: string, data: FrpConfigInput): Promise<FrpConfig> {
  return http.put<FrpConfig>(`/api/frp/server-config/${id}`, data);
}

export function listTunnels(): Promise<FrpTunnel[]> {
  return http.get<FrpTunnel[]>('/api/frp/tunnels');
}

export function createTunnel(data: FrpTunnelInput): Promise<FrpTunnel> {
  return http.post<FrpTunnel>('/api/frp/tunnels', data);
}

export function updateTunnel(id: string, data: FrpTunnelInput): Promise<FrpTunnel> {
  return http.put<FrpTunnel>(`/api/frp/tunnels/${id}`, data);
}

export function removeTunnel(id: string): Promise<void> {
  return http.del<void>(`/api/frp/tunnels/${id}`);
}

async function _fetchText(path: string): Promise<string> {
  const token = getAccessToken();
  const res = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
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
  return res.text();
}

async function _fetchBlob(path: string): Promise<Blob> {
  const token = getAccessToken();
  const res = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
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
  return res.blob();
}

export function getFrpsToml(): Promise<string> {
  return _fetchText('/api/frp/generate/frps-toml');
}

export function getVisitorToml(): Promise<string> {
  return _fetchText('/api/frp/generate/visitor-toml');
}

export function getFrpcToml(serverId: string): Promise<string> {
  return _fetchText(`/api/frp/generate/frpc-toml/${serverId}`);
}

export function getBulkZip(): Promise<Blob> {
  return _fetchBlob('/api/frp/generate/bulk-zip');
}

export function pkiStatus(): Promise<FrpPkiStatus> {
  return http.get<FrpPkiStatus>('/api/frp/pki/status');
}

export function pkiGenerateCA(): Promise<{ expiry: string }> {
  return http.post<{ expiry: string }>('/api/frp/pki/ca');
}

export function pkiGenerateServerCert(): Promise<{ commonName: string }> {
  return http.post<{ commonName: string }>('/api/frp/pki/server-cert', {});
}

export function pkiGenerateClientCert(name: string): Promise<{ commonName: string }> {
  return http.post<{ commonName: string }>(`/api/frp/pki/client-cert/${encodeURIComponent(name)}`);
}

export function pkiDownload(filename: string): Promise<Blob> {
  return _fetchBlob(`/api/frp/pki/download/${encodeURIComponent(filename)}`);
}

export function pkiDownloadBundle(clientName: string): Promise<Blob> {
  return _fetchBlob(`/api/frp/pki/download-client-bundle/${encodeURIComponent(clientName)}`);
}

export function status(): Promise<FrpStatus> {
  return http.get<FrpStatus>('/api/frp/status');
}
