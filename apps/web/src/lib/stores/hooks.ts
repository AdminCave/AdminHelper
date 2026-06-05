// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';
import type { Hook } from '$lib/api/types';
import * as api from '$lib/api/hooks';

const _hooks = writable<Hook[]>([]);

export const hooks = {
  subscribe: _hooks.subscribe,

  async refresh(): Promise<void> {
    _hooks.set(await api.list());
  },

  async remove(id: string): Promise<void> {
    await api.remove(id);
    _hooks.update((list) => list.filter((h) => h.id !== id));
  },

  async toggle(id: string): Promise<void> {
    const updated = await api.toggle(id);
    _hooks.update((list) => list.map((h) => (h.id === id ? { ...h, ...updated } : h)));
  },
};
