// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';
import type { Server, ServerInput } from '$lib/api/types';
import * as api from '$lib/api/servers';

const _servers = writable<Server[]>([]);

export const servers = {
  subscribe: _servers.subscribe,

  async refresh(): Promise<void> {
    _servers.set(await api.list());
  },

  async create(data: ServerInput): Promise<Server> {
    const created = await api.create(data);
    _servers.update((list) => [...list, created]);
    return created;
  },

  async update(id: string, data: ServerInput): Promise<Server> {
    const updated = await api.update(id, data);
    _servers.update((list) => list.map((s) => (s.id === id ? updated : s)));
    return updated;
  },

  async remove(id: string): Promise<void> {
    await api.remove(id);
    _servers.update((list) => list.filter((s) => s.id !== id));
  },

  set(list: Server[]): void {
    _servers.set(list);
  },
};
