// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Ansible API: playbook management via api_proxy. Reads (list/content/servers)
// feed the run wizard; the CRUD wrappers let the desktop author playbooks, which
// used to be web-only. Mirrors apps/web/src/lib/api/ansible.ts.

import { apiRequest } from '$lib/api/request';
import type { AuthSession } from '$lib/bridge/types';
import type { Playbook, PlaybookContent, PlaybookInput, Server } from '$lib/api/types';

export const ansibleApi = {
  fetchPlaybooks(session: AuthSession): Promise<Playbook[]> {
    return apiRequest<Playbook[]>(session, 'GET', '/api/ansible/playbooks');
  },
  fetchContent(session: AuthSession, id: string): Promise<PlaybookContent> {
    return apiRequest<PlaybookContent>(session, 'GET', `/api/ansible/playbooks/${id}/content`);
  },
  fetchServers(session: AuthSession): Promise<Server[]> {
    return apiRequest<Server[]>(session, 'GET', '/api/servers');
  },
  createPlaybook(session: AuthSession, data: PlaybookInput): Promise<Playbook> {
    return apiRequest<Playbook>(session, 'POST', '/api/ansible/playbooks', data);
  },
  updatePlaybook(session: AuthSession, id: string, data: PlaybookInput): Promise<Playbook> {
    return apiRequest<Playbook>(session, 'PUT', `/api/ansible/playbooks/${id}`, data);
  },
  removePlaybook(session: AuthSession, id: string): Promise<void> {
    return apiRequest<void>(session, 'DELETE', `/api/ansible/playbooks/${id}`);
  },
};
