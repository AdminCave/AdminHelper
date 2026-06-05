// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { http } from './client';
import type { Playbook, PlaybookContent, PlaybookInput } from './types';

export function list(): Promise<Playbook[]> {
  return http.get<Playbook[]>('/api/ansible/playbooks');
}

export function content(id: string): Promise<PlaybookContent> {
  return http.get<PlaybookContent>(`/api/ansible/playbooks/${id}/content`);
}

export function create(data: PlaybookInput): Promise<Playbook> {
  return http.post<Playbook>('/api/ansible/playbooks', data);
}

export function update(id: string, data: PlaybookInput): Promise<Playbook> {
  return http.put<Playbook>(`/api/ansible/playbooks/${id}`, data);
}

export function remove(id: string): Promise<void> {
  return http.del<void>(`/api/ansible/playbooks/${id}`);
}
