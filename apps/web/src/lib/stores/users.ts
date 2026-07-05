// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';
import type { User, UserCreate, UserUpdate } from '$lib/api/types';
import * as api from '$lib/api/users';

const _users = writable<User[]>([]);

// Stale-response guard: a slow refresh() list() that resolves AFTER a mutation (or a newer
// refresh) must not overwrite the current state — else e.g. a just-removed row reappears. Every
// mutation bumps the generation so an in-flight refresh drops its result (4.145).
let refreshGen = 0;

export const users = {
  subscribe: _users.subscribe,

  async refresh(): Promise<void> {
    const gen = ++refreshGen;
    const list = await api.list();
    if (gen === refreshGen) _users.set(list);
  },

  async create(data: UserCreate): Promise<User> {
    const created = await api.create(data);
    refreshGen++;
    _users.update((list) => [...list, created]);
    return created;
  },

  async update(id: number, data: UserUpdate): Promise<User> {
    const updated = await api.update(id, data);
    refreshGen++;
    _users.update((list) => list.map((u) => (u.id === id ? updated : u)));
    return updated;
  },

  async remove(id: number): Promise<void> {
    await api.remove(id);
    refreshGen++;
    _users.update((list) => list.filter((u) => u.id !== id));
  },
};
