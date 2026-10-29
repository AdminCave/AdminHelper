// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import type { User, UserCreate, UserUpdate } from '$lib/api/types';
import * as api from '$lib/api/users';
import { listStore } from './listStore';

const list = listStore<User>(api.list);

export const users = {
  subscribe: list.subscribe,
  refresh: list.refresh,
  reset: list.reset,

  create(data: UserCreate): Promise<User> {
    return list.mutate(
      () => api.create(data),
      (users, created) => [...users, created],
    );
  },

  update(id: number, data: UserUpdate): Promise<User> {
    return list.mutate(
      () => api.update(id, data),
      (users, updated) => users.map((u) => (u.id === id ? updated : u)),
    );
  },

  remove(id: number): Promise<void> {
    return list.mutate(
      () => api.remove(id),
      (users) => users.filter((u) => u.id !== id),
    );
  },
};
