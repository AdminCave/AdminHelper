// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable } from 'svelte/store';
import type { FrpConfig, FrpConfigInput, FrpTunnel, FrpTunnelInput } from '$lib/api/types';
import * as api from '$lib/api/frp';

const _config = writable<FrpConfig | null>(null);
const _tunnels = writable<FrpTunnel[]>([]);

export const frpConfig = {
  subscribe: _config.subscribe,

  async refresh(): Promise<void> {
    const list = await api.listConfigs();
    _config.set(list.length > 0 ? list[0] : null);
  },

  async save(data: FrpConfigInput, existing: FrpConfig | null): Promise<FrpConfig> {
    const saved = existing
      ? await api.updateConfig(existing.id, data)
      : await api.createConfig(data);
    _config.set(saved);
    return saved;
  },
};

export const frpTunnels = {
  subscribe: _tunnels.subscribe,

  async refresh(): Promise<void> {
    _tunnels.set(await api.listTunnels());
  },

  async create(data: FrpTunnelInput): Promise<FrpTunnel> {
    const created = await api.createTunnel(data);
    _tunnels.update((list) => [...list, created]);
    return created;
  },

  async update(id: string, data: FrpTunnelInput): Promise<FrpTunnel> {
    const updated = await api.updateTunnel(id, data);
    _tunnels.update((list) => list.map((t) => (t.id === id ? updated : t)));
    return updated;
  },

  async remove(id: string): Promise<void> {
    await api.removeTunnel(id);
    _tunnels.update((list) => list.filter((t) => t.id !== id));
  },
};
