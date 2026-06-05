// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';
import type { Playbook, PlaybookInput } from '$lib/api/types';
import * as api from '$lib/api/ansible';

const _playbooks = writable<Playbook[]>([]);

export const playbooks = {
  subscribe: _playbooks.subscribe,

  async refresh(): Promise<void> {
    _playbooks.set(await api.list());
  },

  async create(data: PlaybookInput): Promise<Playbook> {
    const created = await api.create(data);
    _playbooks.update((list) => [...list, created]);
    return created;
  },

  async update(id: string, data: PlaybookInput): Promise<Playbook> {
    const updated = await api.update(id, data);
    _playbooks.update((list) => list.map((p) => (p.id === id ? updated : p)));
    return updated;
  },

  async remove(id: string): Promise<void> {
    await api.remove(id);
    _playbooks.update((list) => list.filter((p) => p.id !== id));
  },
};
