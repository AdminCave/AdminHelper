// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// users store: optimistic list updates. The bug-prone bit is update() replacing
// the right row BY ID (not by index), so a re-ordered list can't corrupt others.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import type { User } from '$lib/api/types';

vi.mock('$lib/api/users', () => ({
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
}));

import * as api from '$lib/api/users';
import { users } from './users';

const u = (id: number, username = `u${id}`): User => ({ id, username, is_admin: false });

beforeEach(() => vi.clearAllMocks());

async function seed(list: User[]): Promise<void> {
  vi.mocked(api.list).mockResolvedValue(list);
  await users.refresh();
}

describe('users store', () => {
  it('refresh replaces the list', async () => {
    await seed([u(1)]);
    expect(get(users)).toEqual([u(1)]);
  });

  it('create appends the created user', async () => {
    await seed([u(1)]);
    vi.mocked(api.create).mockResolvedValue(u(2, 'new'));
    await users.create({ username: 'new', password: 'x', is_admin: false, server_ids: [] });
    expect(get(users).map((x) => x.id)).toEqual([1, 2]);
  });

  it('update replaces the matching user by id and leaves others untouched', async () => {
    await seed([u(1), u(2)]);
    vi.mocked(api.update).mockResolvedValue({ ...u(2), username: 'renamed' });
    await users.update(2, { is_admin: false, server_ids: [] });
    expect(get(users).find((x) => x.id === 2)?.username).toBe('renamed');
    expect(get(users).find((x) => x.id === 1)?.username).toBe('u1');
  });

  it('remove drops the entry by id', async () => {
    await seed([u(1), u(2)]);
    vi.mocked(api.remove).mockResolvedValue(undefined);
    await users.remove(1);
    expect(get(users).map((x) => x.id)).toEqual([2]);
  });

  it('a slow refresh does not resurrect a row removed after it started (4.145)', async () => {
    await seed([u(1), u(2)]);

    // A slow refresh starts; its list() resolves later with the OLD list (still incl. user 1).
    let resolveSlow!: (v: User[]) => void;
    vi.mocked(api.list).mockReturnValueOnce(new Promise<User[]>((r) => (resolveSlow = r)));
    const slowRefresh = users.refresh();

    // Meanwhile remove(1) completes and drops user 1.
    vi.mocked(api.remove).mockResolvedValue(undefined);
    await users.remove(1);
    expect(get(users).map((x) => x.id)).toEqual([2]);

    // The slow refresh now resolves with the stale list (still incl. user 1).
    resolveSlow([u(1), u(2)]);
    await slowRefresh;

    // User 1 must NOT be resurrected — the generation guard drops the stale response.
    expect(get(users).map((x) => x.id)).toEqual([2]);
  });
});
