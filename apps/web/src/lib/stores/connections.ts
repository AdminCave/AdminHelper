// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';
import type { Connection } from '$lib/api/types';
import * as api from '$lib/api/connections';

const _connections = writable<Connection[]>([]);

export const connections = {
  subscribe: _connections.subscribe,

  async refresh(): Promise<void> {
    _connections.set(await api.list());
  },

  async create(data: Partial<Connection>): Promise<Connection> {
    const created = await api.create(data);
    _connections.update((list) => [...list, created]);
    return created;
  },

  async update(id: string, data: Partial<Connection>): Promise<Connection> {
    const updated = await api.update(id, data);
    _connections.update((list) => list.map((c) => (c.id === id ? updated : c)));
    return updated;
  },

  async remove(id: string): Promise<void> {
    await api.remove(id);
    _connections.update((list) => list.filter((c) => c.id !== id));
  },

  set(list: Connection[]): void {
    _connections.set(list);
  },
};
