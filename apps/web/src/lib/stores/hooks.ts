// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import type { Hook, HookCreate, HookCreateResult, HookDetail, HookUpdate } from '$lib/api/types';
import * as api from '$lib/api/hooks';
import { listStore } from './listStore';

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

const list = listStore<Hook>(api.list);

export const hooks = {
  subscribe: list.subscribe,
  refresh: list.refresh,
  reset: list.reset,

  create(data: HookCreate): Promise<HookCreateResult> {
    return list.mutate(
      () => api.create(data),
      (hooks, created) => [...hooks, toListEntry(created)],
    );
  },

  update(id: string, data: HookUpdate): Promise<HookDetail> {
    return list.mutate(
      () => api.update(id, data),
      (hooks, updated) => hooks.map((h) => (h.id === id ? { ...h, ...toListEntry(updated) } : h)),
    );
  },

  remove(id: string): Promise<void> {
    return list.mutate(
      () => api.remove(id),
      (hooks) => hooks.filter((h) => h.id !== id),
    );
  },

  async toggle(id: string): Promise<void> {
    await list.mutate(
      () => api.toggle(id),
      (hooks, updated) => hooks.map((h) => (h.id === id ? { ...h, ...updated } : h)),
    );
  },
};
