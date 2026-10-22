// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';
import type { Hook, HookCreate, HookCreateResult, HookDetail, HookUpdate } from '$lib/api/types';
import * as api from '$lib/api/hooks';

const _hooks = writable<Hook[]>([]);

// The list holds only what GET /api/hooks returns (HookResponse in
// apps/server/app/modules/hooks/router.py). The create and detail responses add the script and, for
// a webhook, the once-shown token; this store lives until the page reloads, so neither belongs in
// it. An allowlist keeps a new response field out by default; `satisfies` fails `npm run check`
// when a field of Hook is missing here or a field that Hook does not have is listed.
const HOOK_FIELDS = Object.keys({
  id: true,
  name: true,
  description: true,
  hook_type: true,
  enabled: true,
  created_at: true,
  event_triggers: true,
  schedule_interval: true,
  last_run: true,
  next_run: true,
} satisfies Record<keyof Hook, true>) as (keyof Hook)[];

// Copies only the fields the response carries: update() merges the entry onto the listed hook, and
// an explicit undefined would overwrite a value the response left out.
function toListEntry(h: Hook): Hook {
  const entry: Partial<Record<keyof Hook, unknown>> = {};
  for (const k of HOOK_FIELDS) if (k in h) entry[k] = h[k];
  return entry as Hook;
}

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
    _hooks.update((list) => [...list, toListEntry(created)]);
    return created;
  },

  async update(id: string, data: HookUpdate): Promise<HookDetail> {
    const updated = await api.update(id, data);
    refreshGen++;
    _hooks.update((list) => list.map((h) => (h.id === id ? { ...h, ...toListEntry(updated) } : h)));
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
