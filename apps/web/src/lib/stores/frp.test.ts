// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// frpConfig store: refresh keeps the first config (or null), save() routes
// to create vs update depending on whether a config already exists, and holds
// the result the way GET returns it (authToken and dashboardPassword null).

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

  it('save on create holds the config without authToken and dashboardPassword, like GET', async () => {
    const created = {
      ...cfg('new'),
      authToken: 'frp-s3cr3t-token',
      dashboardPassword: 'dash-s3cr3t',
    };
    vi.mocked(api.createConfig).mockResolvedValue(created);
    const saved = await frpConfig.save(INPUT, null);
    const expected = { ...cfg('new'), authToken: null, dashboardPassword: null };
    expect(get(frpConfig)).toEqual(expected);
    expect(saved).toEqual(expected);
    for (const value of [JSON.stringify(get(frpConfig)), JSON.stringify(saved)]) {
      expect(value).not.toContain('frp-s3cr3t-token');
      expect(value).not.toContain('dash-s3cr3t');
    }
  });

  it('save on update holds the config without authToken and dashboardPassword, like GET', async () => {
    const updated = {
      ...cfg('1', 'updated'),
      authToken: 'frp-s3cr3t-token',
      dashboardPassword: 'dash-s3cr3t',
    };
    vi.mocked(api.updateConfig).mockResolvedValue(updated);
    const saved = await frpConfig.save(INPUT, cfg('1'));
    const expected = { ...cfg('1', 'updated'), authToken: null, dashboardPassword: null };
    expect(get(frpConfig)).toEqual(expected);
    expect(saved).toEqual(expected);
    for (const value of [JSON.stringify(get(frpConfig)), JSON.stringify(saved)]) {
      expect(value).not.toContain('frp-s3cr3t-token');
      expect(value).not.toContain('dash-s3cr3t');
    }
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

// save() against a refresh() still in flight and against a logout (reset()) before its answer.
describe('frpConfig store: stale responses around save()', () => {
  function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void } {
    let resolve!: (v: T) => void;
    const promise = new Promise<T>((r) => (resolve = r));
    return { promise, resolve };
  }

  const masked = (c: FrpConfig): FrpConfig => ({ ...c, authToken: null, dashboardPassword: null });

  beforeEach(() => frpConfig.reset());

  it('a refresh() started before save() does not bring the old config back', async () => {
    const list = deferred<FrpConfig[]>();
    vi.mocked(api.listConfigs).mockReturnValueOnce(list.promise);
    const refreshing = frpConfig.refresh();

    vi.mocked(api.updateConfig).mockResolvedValueOnce(cfg('1', 'new'));
    await frpConfig.save(INPUT, cfg('1'));

    list.resolve([cfg('1', 'old')]);
    await refreshing;
    expect(get(frpConfig)).toEqual(masked(cfg('1', 'new')));
  });

  it('save() answered after reset() leaves the store empty and still returns the config', async () => {
    const response = deferred<FrpConfig>();
    vi.mocked(api.createConfig).mockReturnValueOnce(response.promise);
    const saving = frpConfig.save(INPUT, null);

    frpConfig.reset();
    response.resolve(cfg('1'));
    await expect(saving).resolves.toEqual(masked(cfg('1')));
    expect(get(frpConfig)).toBeNull();
  });

  it('save() answered after the next session loaded its config does not replace it', async () => {
    const response = deferred<FrpConfig>();
    vi.mocked(api.updateConfig).mockReturnValueOnce(response.promise);
    const saving = frpConfig.save(INPUT, cfg('1'));

    frpConfig.reset();
    vi.mocked(api.listConfigs).mockResolvedValueOnce([cfg('2')]);
    await frpConfig.refresh();

    response.resolve(cfg('1', 'old session'));
    await saving;
    expect(get(frpConfig)).toEqual(cfg('2'));
  });

  // Control: green before the fix too; a save() that bumped the generation after reset() would
  // make the next session's load drop its config.
  it('save() answered while the next session loads does not drop that load', async () => {
    const response = deferred<FrpConfig>();
    vi.mocked(api.updateConfig).mockReturnValueOnce(response.promise);
    const saving = frpConfig.save(INPUT, cfg('1'));

    frpConfig.reset();
    const list = deferred<FrpConfig[]>();
    vi.mocked(api.listConfigs).mockReturnValueOnce(list.promise);
    const refreshing = frpConfig.refresh();

    response.resolve(cfg('1', 'old session'));
    await saving;
    list.resolve([cfg('2')]);
    await refreshing;
    expect(get(frpConfig)).toEqual(cfg('2'));
  });
});
