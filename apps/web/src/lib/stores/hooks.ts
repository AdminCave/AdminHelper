// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';
import type { Hook, HookCreate, HookCreateResult, HookDetail, HookUpdate } from '$lib/api/types';
import * as api from '$lib/api/hooks';

const _hooks = writable<Hook[]>([]);

// Stale-response guard (see users.ts): a slow refresh() list() must not overwrite state a mutation
// already changed — else e.g. a just-removed hook reappears (4.145).
let refreshGen = 0;

export const hooks = {
  subscribe: _hooks.subscribe,

  async refresh(): Promise<void> {
    const gen = ++refreshGen;
    const list = await api.list();
    if (gen === refreshGen) _hooks.set(list);
  },

  async create(data: HookCreate): Promise<HookCreateResult> {
    const created = await api.create(data);
    refreshGen++;
    _hooks.update((list) => [...list, created]);
    return created;
  },

  async update(id: string, data: HookUpdate): Promise<HookDetail> {
    const updated = await api.update(id, data);
    refreshGen++;
    _hooks.update((list) => list.map((h) => (h.id === id ? { ...h, ...updated } : h)));
    return updated;
  },

  async remove(id: string): Promise<void> {
    await api.remove(id);
    refreshGen++;
    _hooks.update((list) => list.filter((h) => h.id !== id));
  },

  async toggle(id: string): Promise<void> {
    const updated = await api.toggle(id);
    refreshGen++;
    _hooks.update((list) => list.map((h) => (h.id === id ? { ...h, ...updated } : h)));
  },
};
