// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Servers API: server-inventory CRUD via api_proxy. Mirrors the endpoints the
// web frontend used in apps/web/src/lib/api/servers.ts. All writes are
// admin-only on the server side.

import { apiRequest } from '$lib/api/request';
import type { AuthSession } from '$lib/bridge/types';
import type { Server, ServerInput } from '$lib/api/types';

export const serversApi = {
  list(session: AuthSession): Promise<Server[]> {
    return apiRequest<Server[]>(session, 'GET', '/api/servers');
  },
  create(session: AuthSession, data: ServerInput): Promise<Server> {
    return apiRequest<Server>(session, 'POST', '/api/servers', data);
  },
  update(session: AuthSession, id: string, data: ServerInput): Promise<Server> {
    return apiRequest<Server>(session, 'PUT', `/api/servers/${encodeURIComponent(id)}`, data);
  },
  remove(session: AuthSession, id: string): Promise<void> {
    return apiRequest<void>(session, 'DELETE', `/api/servers/${encodeURIComponent(id)}`);
  },
};
