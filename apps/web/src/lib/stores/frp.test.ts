// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// frpConfig store: refresh keeps the first config (or null), and save() routes
// to create vs update depending on whether a config already exists.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import type { FrpConfig, FrpConfigInput } from '$lib/api/types';

vi.mock('$lib/api/frp', () => ({
  listConfigs: vi.fn(),
  createConfig: vi.fn(),
  updateConfig: vi.fn(),
}));

import * as api from '$lib/api/frp';
import { frpConfig } from './frp';

const cfg = (id: string, name = id): FrpConfig => ({ id, name, serverAddr: 'a', bindPort: 7000 });
const INPUT: FrpConfigInput = { name: 'c', server_addr: 'a', bind_port: 7000 };

beforeEach(() => vi.clearAllMocks());

describe('frpConfig store', () => {
  it('refresh keeps the first config, or null when empty', async () => {
    vi.mocked(api.listConfigs).mockResolvedValue([cfg('1'), cfg('2')]);
    await frpConfig.refresh();
    expect(get(frpConfig)?.id).toBe('1');

    vi.mocked(api.listConfigs).mockResolvedValue([]);
    await frpConfig.refresh();
    expect(get(frpConfig)).toBeNull();
  });

  it('save creates when there is no existing config', async () => {
    vi.mocked(api.createConfig).mockResolvedValue(cfg('new'));
    await frpConfig.save(INPUT, null);
    expect(api.createConfig).toHaveBeenCalledWith(INPUT);
    expect(api.updateConfig).not.toHaveBeenCalled();
    expect(get(frpConfig)?.id).toBe('new');
  });

  it('save updates when a config already exists', async () => {
    vi.mocked(api.updateConfig).mockResolvedValue(cfg('1', 'updated'));
    await frpConfig.save(INPUT, cfg('1'));
    expect(api.updateConfig).toHaveBeenCalledWith('1', INPUT);
    expect(api.createConfig).not.toHaveBeenCalled();
    expect(get(frpConfig)?.name).toBe('updated');
  });
});

describe('frpConfig store rejection (6.90)', () => {
  it('save does not set a config when the API rejects', async () => {
    vi.mocked(api.listConfigs).mockResolvedValue([]);
    await frpConfig.refresh();
    vi.mocked(api.createConfig).mockRejectedValue(new Error('422'));
    await expect(frpConfig.save(INPUT, null)).rejects.toThrow('422');
    expect(get(frpConfig)).toBeNull();
  });
});
