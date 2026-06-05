// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';
import type { ApiKey, ApiKeyCreate, ApiKeyCreateResult } from '$lib/api/types';
import * as api from '$lib/api/apikeys';

const _apikeys = writable<ApiKey[]>([]);

export const apikeys = {
  subscribe: _apikeys.subscribe,

  async refresh(): Promise<void> {
    _apikeys.set(await api.list());
  },

  async create(data: ApiKeyCreate): Promise<ApiKeyCreateResult> {
    const created = await api.create(data);
    _apikeys.update((list) => [
      ...list,
      { id: created.id, name: created.name, permission: created.permission },
    ]);
    return created;
  },

  async remove(id: number): Promise<void> {
    await api.remove(id);
    _apikeys.update((list) => list.filter((k) => k.id !== id));
  },
};
