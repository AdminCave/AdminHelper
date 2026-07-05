// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// FRP API: tunnel CRUD + read access to the FRP server configs (needed as a
// picker when creating a tunnel). The server-config itself stays an
// instance-admin concern in the web frontend, so no create/update wrappers for
// it live here — only the read used to populate the tunnel form.
//
// The TOML/ZIP generation endpoints are intentionally absent: they return
// text/binary, which the JSON-only api_proxy cannot carry. Agents receive their
// frpc config through provisioning instead.

import { apiRequest } from '$lib/api/request';
import type { AuthSession } from '$lib/bridge/types';
import type { FrpConfig, FrpStatus, FrpTunnel, FrpTunnelInput } from '$lib/api/types';

export const frpApi = {
  listConfigs(session: AuthSession): Promise<FrpConfig[]> {
    return apiRequest<FrpConfig[]>(session, 'GET', '/api/frp/server-config');
  },
  listTunnels(session: AuthSession): Promise<FrpTunnel[]> {
    return apiRequest<FrpTunnel[]>(session, 'GET', '/api/frp/tunnels');
  },
  createTunnel(session: AuthSession, data: FrpTunnelInput): Promise<FrpTunnel> {
    return apiRequest<FrpTunnel>(session, 'POST', '/api/frp/tunnels', data);
  },
  updateTunnel(session: AuthSession, id: string, data: FrpTunnelInput): Promise<FrpTunnel> {
    return apiRequest<FrpTunnel>(
      session,
      'PUT',
      `/api/frp/tunnels/${encodeURIComponent(id)}`,
      data,
    );
  },
  removeTunnel(session: AuthSession, id: string): Promise<void> {
    return apiRequest<void>(session, 'DELETE', `/api/frp/tunnels/${encodeURIComponent(id)}`);
  },
  status(session: AuthSession): Promise<FrpStatus> {
    return apiRequest<FrpStatus>(session, 'GET', '/api/frp/status');
  },
};
