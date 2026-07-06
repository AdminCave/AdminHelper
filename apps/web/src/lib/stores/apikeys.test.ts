// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The apikeys store keeps the visible list in sync with the API. The security-
// relevant bit: create() returns the one-time secret to the caller (for display)
// but must store only id/name/permission — the secret never lands in the list.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import type { ApiKey, ApiKeyCreateResult } from '$lib/api/types';

vi.mock('$lib/api/apikeys', () => ({
  list: vi.fn(),
  create: vi.fn(),
  remove: vi.fn(),
}));

import * as api from '$lib/api/apikeys';
import { apikeys } from './apikeys';

beforeEach(() => vi.clearAllMocks());

async function seed(list: ApiKey[]): Promise<void> {
  vi.mocked(api.list).mockResolvedValue(list);
  await apikeys.refresh();
}

describe('apikeys store', () => {
  it('refresh replaces the list from the API', async () => {
    await seed([{ id: 1, name: 'a', permission: 'read' }]);
    expect(get(apikeys)).toEqual([{ id: 1, name: 'a', permission: 'read' }]);
  });

  it('create returns the secret but never stores it in the list', async () => {
    await seed([]);
    const result: ApiKeyCreateResult = {
      key: 'ah_SECRET_TOKEN',
      id: 2,
      name: 'ci',
      permission: 'read_write',
    };
    vi.mocked(api.create).mockResolvedValue(result);

    const returned = await apikeys.create({ name: 'ci', permission: 'read_write' });

    expect(returned).toEqual(result); // caller gets the one-time secret
    expect(get(apikeys)).toEqual([{ id: 2, name: 'ci', permission: 'read_write' }]);
    expect(JSON.stringify(get(apikeys))).not.toContain('ah_SECRET_TOKEN');
  });

  it('remove drops the entry by id', async () => {
    await seed([
      { id: 1, name: 'a', permission: 'read' },
      { id: 2, name: 'b', permission: 'read' },
    ]);
    vi.mocked(api.remove).mockResolvedValue(undefined);

    await apikeys.remove(1);

    expect(get(apikeys).map((k) => k.id)).toEqual([2]);
  });
});

describe('apikeys store rejection (6.90)', () => {
  it('create leaves the list unchanged when the API rejects', async () => {
    await seed([{ id: 1, name: 'a', permission: 'read' }]);
    vi.mocked(api.create).mockRejectedValue(new Error('409'));
    await expect(apikeys.create({ name: 'dup', permission: 'read_write' })).rejects.toThrow('409');
    expect(get(apikeys)).toEqual([{ id: 1, name: 'a', permission: 'read' }]);
  });
});
