// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// hooks store: toggle() and update() merge only the fields the API returns onto the
// matching hook (by id), without disturbing the others; create() and update() keep only
// the fields of Hook in the list, never the script or the once-shown webhook token.

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

  it('create keeps neither token nor script in the list but returns both', async () => {
    await seed([h('a')]);
    vi.mocked(api.create).mockResolvedValue({
      ...h('b'),
      script: 'print("s3cr3t-script")',
      token: 'whk_s3cr3t',
    });
    const created = await hooks.create({ name: 'b', hook_type: 'webhook', script: '' });
    const entry = get(hooks).find((x) => x.id === 'b');
    expect(entry).toBeDefined();
    expect(entry).not.toHaveProperty('token');
    expect(entry).not.toHaveProperty('script');
    const stored = JSON.stringify(get(hooks));
    expect(stored).not.toContain('whk_s3cr3t');
    expect(stored).not.toContain('s3cr3t-script');
    expect(created.token).toBe('whk_s3cr3t');
  });

  it('update keeps no script in the list and leaves the other hooks alone', async () => {
    await seed([h('a'), h('b')]);
    vi.mocked(api.update).mockResolvedValue({
      ...h('a'),
      name: 'renamed',
      script: 'print("s3cr3t-script")',
    });
    await hooks.update('a', { name: 'renamed' });
    const a = get(hooks).find((x) => x.id === 'a');
    expect(a?.name).toBe('renamed');
    expect(a).not.toHaveProperty('script');
    expect(get(hooks).find((x) => x.id === 'b')).toEqual(h('b'));
  });

  it('update keeps a field the response does not carry', async () => {
    await seed([{ ...h('a'), description: 'keep' }]);
    vi.mocked(api.update).mockResolvedValue({ ...h('a'), name: 'renamed', script: '' });
    await hooks.update('a', { name: 'renamed' });
    expect(get(hooks).find((x) => x.id === 'a')?.description).toBe('keep');
  });

  it('remove drops the entry by id', async () => {
    await seed([h('a'), h('b')]);
    vi.mocked(api.remove).mockResolvedValue(undefined);
    await hooks.remove('a');
    expect(get(hooks).map((x) => x.id)).toEqual(['b']);
  });
});

describe('hooks store rejection (6.90)', () => {
  it('toggle leaves the list unchanged when the API rejects', async () => {
    await seed([h('a', true)]);
    vi.mocked(api.toggle).mockRejectedValue(new Error('500'));
    await expect(hooks.toggle('a')).rejects.toThrow('500');
    expect(get(hooks)).toEqual([h('a', true)]);
  });
});
