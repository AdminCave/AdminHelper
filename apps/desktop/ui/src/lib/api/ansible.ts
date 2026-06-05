// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Ansible API: wrapper around apiProxy() for playbook management.

import * as bridge from '$lib/bridge';
import type { AuthSession } from '$lib/bridge/types';
import type { Playbook, PlaybookContent, Server } from '$lib/api/types';

function request<T>(
  session: AuthSession,
  method: 'GET' | 'POST',
  path: string,
  body?: unknown,
): Promise<T> {
  return bridge.apiProxy<T>(
    session.serverUrl,
    session.token,
    method,
    path,
    body ? JSON.stringify(body) : undefined,
  );
}

export const ansibleApi = {
  fetchPlaybooks(session: AuthSession): Promise<Playbook[]> {
    return request<Playbook[]>(session, 'GET', '/api/ansible/playbooks');
  },
  fetchContent(session: AuthSession, id: string): Promise<PlaybookContent> {
    return request<PlaybookContent>(session, 'GET', `/api/ansible/playbooks/${id}/content`);
  },
  fetchServers(session: AuthSession): Promise<Server[]> {
    return request<Server[]>(session, 'GET', '/api/servers');
  },
};
