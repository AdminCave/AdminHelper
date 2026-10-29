// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';
import type { FrpConfig, FrpConfigInput } from '$lib/api/types';
import * as api from '$lib/api/frp';

const _config = writable<FrpConfig | null>(null);

// Stale-response guard: a refresh() keeps its result only if no newer refresh(), save() or reset()
// came in between, else a load started before a save() (or before logout) brings the old config
// back. reset() also starts a new session epoch: a save() answered after it returns its result but
// neither sets the store nor bumps the generation, which would drop the next session's load.
let refreshGen = 0;
let sessionEpoch = 0;

export const frpConfig = {
  subscribe: _config.subscribe,

  async refresh(): Promise<void> {
    const gen = ++refreshGen;
    const list = await api.listConfigs();
    if (gen === refreshGen) _config.set(list.length > 0 ? list[0] : null);
  },

  // Logout empties the store; the bumps keep a refresh() or save() still in flight out of it.
  reset(): void {
    refreshGen++;
    sessionEpoch++;
    _config.set(null);
  },

  async save(data: FrpConfigInput, existing: FrpConfig | null): Promise<FrpConfig> {
    const epoch = sessionEpoch;
    const response = existing
      ? await api.updateConfig(existing.id, data)
      : await api.createConfig(data);
    // The create response carries authToken and dashboardPassword in clear text
    // (create_server_config in apps/server/app/modules/frp/config_router.py), and this store lives
    // until the page reloads; the page never reads either value back. Hold the config the way GET
    // returns it, on both paths, so the store does not rely on the PUT response being masked.
    const saved: FrpConfig = { ...response, authToken: null, dashboardPassword: null };
    if (epoch === sessionEpoch) {
      refreshGen++;
      _config.set(saved);
    }
    return saved;
  },
};
