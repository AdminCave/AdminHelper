// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';
import type { User, UserCreate, UserUpdate } from '$lib/api/types';
import * as api from '$lib/api/users';

const _users = writable<User[]>([]);

export const users = {
  subscribe: _users.subscribe,

  async refresh(): Promise<void> {
    _users.set(await api.list());
  },

  async create(data: UserCreate): Promise<User> {
    const created = await api.create(data);
    _users.update((list) => [...list, created]);
    return created;
  },

  async update(id: number, data: UserUpdate): Promise<User> {
    const updated = await api.update(id, data);
    _users.update((list) => list.map((u) => (u.id === id ? updated : u)));
    return updated;
  },

  async remove(id: number): Promise<void> {
    await api.remove(id);
    _users.update((list) => list.filter((u) => u.id !== id));
  },
};
