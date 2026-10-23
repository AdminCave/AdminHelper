// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';
import type { FrpConfig, FrpConfigInput } from '$lib/api/types';
import * as api from '$lib/api/frp';

const _config = writable<FrpConfig | null>(null);

// Stale-response guard (see users.ts): a refresh() of the old session that resolves after
// reset() must not bring its config back.
let refreshGen = 0;

export const frpConfig = {
  subscribe: _config.subscribe,

  async refresh(): Promise<void> {
    const gen = ++refreshGen;
    const list = await api.listConfigs();
    if (gen === refreshGen) _config.set(list.length > 0 ? list[0] : null);
  },

  // Logout empties the store; the bump makes a refresh() still in flight drop its result.
  reset(): void {
    refreshGen++;
    _config.set(null);
  },

  async save(data: FrpConfigInput, existing: FrpConfig | null): Promise<FrpConfig> {
    const response = existing
      ? await api.updateConfig(existing.id, data)
      : await api.createConfig(data);
    // The create response carries authToken and dashboardPassword in clear text
    // (create_server_config in apps/server/app/modules/frp/config_router.py), and this store lives
    // until the page reloads; the page never reads either value back. Hold the config the way GET
    // returns it, on both paths, so the store does not rely on the PUT response being masked.
    const saved: FrpConfig = { ...response, authToken: null, dashboardPassword: null };
    _config.set(saved);
    return saved;
  },
};
