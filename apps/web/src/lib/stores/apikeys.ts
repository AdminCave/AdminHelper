// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';
import type { ApiKey, ApiKeyCreate, ApiKeyCreateResult } from '$lib/api/types';
import * as api from '$lib/api/apikeys';

const _apikeys = writable<ApiKey[]>([]);

// Stale-response guard (see users.ts): a slow refresh() list() must not overwrite state a mutation
// already changed — else e.g. a just-removed key reappears (4.145).
let refreshGen = 0;

export const apikeys = {
  subscribe: _apikeys.subscribe,

  async refresh(): Promise<void> {
    const gen = ++refreshGen;
    const list = await api.list();
    if (gen === refreshGen) _apikeys.set(list);
  },

  async create(data: ApiKeyCreate): Promise<ApiKeyCreateResult> {
    const created = await api.create(data);
    refreshGen++;
    _apikeys.update((list) => [
      ...list,
      { id: created.id, name: created.name, permission: created.permission },
    ]);
    return created;
  },

  async remove(id: number): Promise<void> {
    await api.remove(id);
    refreshGen++;
    _apikeys.update((list) => list.filter((k) => k.id !== id));
  },
};
