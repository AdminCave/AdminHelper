// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// hooks store: the interesting bit is toggle() merging only the fields the API
// returns onto the matching hook (by id), without disturbing the others.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import type { Hook } from '$lib/api/types';

vi.mock('$lib/api/hooks', () => ({
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  toggle: vi.fn(),
}));

import * as api from '$lib/api/hooks';
import { hooks } from './hooks';

const h = (id: string, enabled = true): Hook => ({ id, name: id, hook_type: 'webhook', enabled });

beforeEach(() => vi.clearAllMocks());

async function seed(list: Hook[]): Promise<void> {
  vi.mocked(api.list).mockResolvedValue(list);
  await hooks.refresh();
}

describe('hooks store', () => {
  it('refresh replaces the list', async () => {
    await seed([h('a')]);
    expect(get(hooks).map((x) => x.id)).toEqual(['a']);
  });

  it('toggle merges the returned fields onto the matching hook only', async () => {
    await seed([h('a', true), h('b', true)]);
    vi.mocked(api.toggle).mockResolvedValue({ ...h('a'), enabled: false });
    await hooks.toggle('a');
    expect(get(hooks).find((x) => x.id === 'a')?.enabled).toBe(false);
    expect(get(hooks).find((x) => x.id === 'b')?.enabled).toBe(true);
  });

  it('create appends the returned hook and returns it (with token)', async () => {
    await seed([h('a')]);
    vi.mocked(api.create).mockResolvedValue({ ...h('b'), script: '', token: 'tok' });
    const created = await hooks.create({ name: 'b', hook_type: 'webhook', script: '' });
    expect(get(hooks).map((x) => x.id)).toEqual(['a', 'b']);
    expect(created.token).toBe('tok');
  });

  it('update merges the returned fields onto the matching hook only', async () => {
    await seed([h('a'), h('b')]);
    vi.mocked(api.update).mockResolvedValue({ ...h('a'), script: '', name: 'renamed' });
    await hooks.update('a', { name: 'renamed' });
    expect(get(hooks).find((x) => x.id === 'a')?.name).toBe('renamed');
    expect(get(hooks).find((x) => x.id === 'b')?.name).toBe('b');
  });

  it('remove drops the entry by id', async () => {
    await seed([h('a'), h('b')]);
    vi.mocked(api.remove).mockResolvedValue(undefined);
    await hooks.remove('a');
    expect(get(hooks).map((x) => x.id)).toEqual(['b']);
  });
});
