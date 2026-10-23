// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// reset() of the data stores (R-0653): logout empties them, and a list() of the old session that
// resolves only after reset() must not fill them again.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get, type Readable } from 'svelte/store';
import type { ApiKey, FrpConfig, Hook, User } from '$lib/api/types';

vi.mock('$lib/api/users', () => ({ list: vi.fn() }));
vi.mock('$lib/api/hooks', () => ({ list: vi.fn() }));
vi.mock('$lib/api/apikeys', () => ({ list: vi.fn() }));
vi.mock('$lib/api/frp', () => ({ listConfigs: vi.fn() }));

import * as usersApi from '$lib/api/users';
import * as hooksApi from '$lib/api/hooks';
import * as apikeysApi from '$lib/api/apikeys';
import * as frpApi from '$lib/api/frp';
import { users } from './users';
import { hooks } from './hooks';
import { apikeys } from './apikeys';
import { frpConfig } from './frp';

function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void } {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

const USER: User = { id: 1, username: 'u1', is_admin: false };
const HOOK: Hook = { id: 'a', name: 'a', hook_type: 'webhook', enabled: true };
const KEY: ApiKey = { id: 1, name: 'k', permission: 'read' };
const CFG: FrpConfig = { id: '1', name: 'c', serverAddr: 'a', bindPort: 7000 };

interface StoreCase {
  name: string;
  store: Readable<unknown> & { refresh(): Promise<void>; reset(): void };
  // The next list() call resolves with one entry; `late` hands back its resolver instead.
  serve(): void;
  serveLate(): () => void;
  empty: [] | null;
}

const cases: StoreCase[] = [
  {
    name: 'users',
    store: users,
    serve: () => vi.mocked(usersApi.list).mockResolvedValueOnce([USER]),
    serveLate: () => {
      const d = deferred<User[]>();
      vi.mocked(usersApi.list).mockReturnValueOnce(d.promise);
      return () => d.resolve([USER]);
    },
    empty: [],
  },
  {
    name: 'hooks',
    store: hooks,
    serve: () => vi.mocked(hooksApi.list).mockResolvedValueOnce([HOOK]),
    serveLate: () => {
      const d = deferred<Hook[]>();
      vi.mocked(hooksApi.list).mockReturnValueOnce(d.promise);
      return () => d.resolve([HOOK]);
    },
    empty: [],
  },
  {
    name: 'apikeys',
    store: apikeys,
    serve: () => vi.mocked(apikeysApi.list).mockResolvedValueOnce([KEY]),
    serveLate: () => {
      const d = deferred<ApiKey[]>();
      vi.mocked(apikeysApi.list).mockReturnValueOnce(d.promise);
      return () => d.resolve([KEY]);
    },
    empty: [],
  },
  {
    name: 'frpConfig',
    store: frpConfig,
    serve: () => vi.mocked(frpApi.listConfigs).mockResolvedValueOnce([CFG]),
    serveLate: () => {
      const d = deferred<FrpConfig[]>();
      vi.mocked(frpApi.listConfigs).mockReturnValueOnce(d.promise);
      return () => d.resolve([CFG]);
    },
    empty: null,
  },
];

beforeEach(() => vi.clearAllMocks());

describe.each(cases)('$name store reset()', (c) => {
  it('empties a filled store', async () => {
    c.serve();
    await c.store.refresh();
    expect(get(c.store)).not.toEqual(c.empty);

    c.store.reset();
    expect(get(c.store)).toEqual(c.empty);
  });

  it('drops a refresh() whose list() resolves after reset()', async () => {
    c.serve();
    await c.store.refresh();

    const resolveLate = c.serveLate();
    const lateRefresh = c.store.refresh();
    c.store.reset();
    resolveLate();
    await lateRefresh;

    expect(get(c.store)).toEqual(c.empty);
  });
});
