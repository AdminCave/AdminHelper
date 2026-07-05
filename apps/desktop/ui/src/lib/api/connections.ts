// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Connections API: server-side CRUD via api_proxy, for server-mode. Mirrors
// apps/web/src/lib/api/connections.ts (the server accepts the camelCase
// Connection shape directly). In server mode connections are owned by the
// server; the local-file path (connections.json) is used only in local/sync
// mode — see the connections store for the mode split.
//
// Export/import are intentionally omitted: they return a file download / take a
// bulk payload, which the JSON-only api_proxy does not carry, and the desktop
// already syncs the full list from the server.

import { apiRequest } from '$lib/api/request';
import type { AuthSession, Connection as LauncherConnection } from '$lib/bridge/types';
import type { Connection } from '$lib/api/types';

export const connectionsApi = {
  list(session: AuthSession): Promise<Connection[]> {
    return apiRequest<Connection[]>(session, 'GET', '/api/connections');
  },
  create(session: AuthSession, data: Partial<Connection>): Promise<Connection> {
    return apiRequest<Connection>(session, 'POST', '/api/connections', data);
  },
  update(session: AuthSession, id: string, data: Partial<Connection>): Promise<Connection> {
    return apiRequest<Connection>(
      session,
      'PUT',
      `/api/connections/${encodeURIComponent(id)}`,
      data,
    );
  },
  // Bumps lastUsed server-side and echoes the connection back. Returns the
  // launcher-shaped Connection because the caller (connectFlow) patches it
  // straight into the launcher store, not the server-API view.
  touch(session: AuthSession, id: string): Promise<LauncherConnection> {
    return apiRequest<LauncherConnection>(
      session,
      'POST',
      `/api/connections/${encodeURIComponent(id)}/touch`,
    );
  },
  remove(session: AuthSession, id: string): Promise<void> {
    return apiRequest<void>(session, 'DELETE', `/api/connections/${encodeURIComponent(id)}`);
  },
};
