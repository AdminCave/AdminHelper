// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Stale-response guard of the list stores (R-0724), pinned per mutation path: a refresh() whose
// list() resolves after a mutation or after a newer refresh() must not overwrite the store, and a
// mutation the API rejects must not drop a refresh() still in flight. A mutation answered after a
// logout (reset()) changes no list, neither the empty one nor the next session's (R-0777).

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get, type Readable } from 'svelte/store';
import type { ApiKey, Hook, User } from '$lib/api/types';

vi.mock('$lib/api/users', () => ({
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
}));
vi.mock('$lib/api/hooks', () => ({
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  toggle: vi.fn(),
}));
vi.mock('$lib/api/apikeys', () => ({
  list: vi.fn(),
  create: vi.fn(),
  remove: vi.fn(),
}));

import * as usersApi from '$lib/api/users';
import * as hooksApi from '$lib/api/hooks';
import * as apikeysApi from '$lib/api/apikeys';
import { users } from './users';
import { hooks } from './hooks';
import { apikeys } from './apikeys';

function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void } {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

type ListStore = Readable<unknown> & { refresh(): Promise<void>; reset(): void };

// The part of an API mock the cases use, typed by what the call resolves with.
interface Answers<R> {
  mockResolvedValueOnce(value: R): unknown;
  mockRejectedValueOnce(error: unknown): unknown;
  mockReturnValueOnce(value: Promise<R>): unknown;
}

interface StoreCase {
  name: string;
  store: ListStore;
  // What seed() puts into the store, and a list that neither it nor any mutation below produces.
  before: unknown[];
  fresh: unknown[];
  seed(): Promise<void>;
  // The next list() call waits; the returned function answers it with `before` or `fresh`.
  listLater(): (answer: 'before' | 'fresh') => void;
}

function storeCase<T>(
  name: string,
  store: ListStore,
  list: Answers<T[]>,
  before: T[],
  fresh: T[],
): StoreCase {
  return {
    name,
    store,
    before,
    fresh,
    async seed() {
      list.mockResolvedValueOnce(before);
      await store.refresh();
    },
    listLater() {
      const d = deferred<T[]>();
      list.mockReturnValueOnce(d.promise);
      return (answer) => d.resolve(answer === 'before' ? before : fresh);
    },
  };
}

interface MutationCase {
  name: string;
  on: StoreCase;
  // The list after the mutation applied the API's response to `on.before`.
  after: unknown[];
  // Queue the API's answer to the next call of the mutation.
  succeed(): void;
  // The next call waits; the returned function answers it with the response.
  succeedLater(): () => void;
  fail(err: Error): void;
  run(): Promise<unknown>;
}

function mutationCase<R>(
  name: string,
  on: StoreCase,
  call: Answers<R>,
  response: R,
  run: () => Promise<unknown>,
  after: unknown[],
): MutationCase {
  return {
    name,
    on,
    after,
    succeed: () => call.mockResolvedValueOnce(response),
    succeedLater: () => {
      const d = deferred<R>();
      call.mockReturnValueOnce(d.promise);
      return () => d.resolve(response);
    },
    fail: (err) => call.mockRejectedValueOnce(err),
    run,
  };
}

const user = (id: number, is_admin = false): User => ({ id, username: `u${id}`, is_admin });
const hook = (id: string, name = id, enabled = true): Hook => ({
  id,
  name,
  hook_type: 'webhook',
  enabled,
});
const key = (id: number): ApiKey => ({ id, name: `k${id}`, permission: 'read' });

const USERS = storeCase('users', users, vi.mocked(usersApi.list), [user(1), user(2)], [user(4)]);
const HOOKS = storeCase(
  'hooks',
  hooks,
  vi.mocked(hooksApi.list),
  [hook('a'), hook('b')],
  [hook('d')],
);
const APIKEYS = storeCase(
  'apikeys',
  apikeys,
  vi.mocked(apikeysApi.list),
  [key(1), key(2)],
  [key(4)],
);

const mutations: MutationCase[] = [
  mutationCase(
    'users.create',
    USERS,
    vi.mocked(usersApi.create),
    user(3),
    () => users.create({ username: 'u3', password: 'pw', is_admin: false, server_ids: [] }),
    [user(1), user(2), user(3)],
  ),
  mutationCase(
    'users.update',
    USERS,
    vi.mocked(usersApi.update),
    user(2, true),
    () => users.update(2, { is_admin: true, server_ids: [] }),
    [user(1), user(2, true)],
  ),
  mutationCase(
    'users.remove',
    USERS,
    vi.mocked(usersApi.remove),
    undefined,
    () => users.remove(1),
    [user(2)],
  ),
  mutationCase(
    'hooks.create',
    HOOKS,
    vi.mocked(hooksApi.create),
    { ...hook('c'), script: '' },
    () => hooks.create({ name: 'c', hook_type: 'webhook', script: '' }),
    [hook('a'), hook('b'), hook('c')],
  ),
  mutationCase(
    'hooks.update',
    HOOKS,
    vi.mocked(hooksApi.update),
    { ...hook('a', 'renamed'), script: '' },
    () => hooks.update('a', { name: 'renamed' }),
    [hook('a', 'renamed'), hook('b')],
  ),
  mutationCase(
    'hooks.remove',
    HOOKS,
    vi.mocked(hooksApi.remove),
    undefined,
    () => hooks.remove('a'),
    [hook('b')],
  ),
  mutationCase(
    'hooks.toggle',
    HOOKS,
    vi.mocked(hooksApi.toggle),
    hook('a', 'a', false),
    () => hooks.toggle('a'),
    [hook('a', 'a', false), hook('b')],
  ),
  mutationCase(
    'apikeys.create',
    APIKEYS,
    vi.mocked(apikeysApi.create),
    { ...key(3), key: 'one-time-placeholder' },
    () => apikeys.create({ name: 'k3', permission: 'read' }),
    [key(1), key(2), key(3)],
  ),
  mutationCase(
    'apikeys.remove',
    APIKEYS,
    vi.mocked(apikeysApi.remove),
    undefined,
    () => apikeys.remove(1),
    [key(2)],
  ),
];

// The stores are module singletons: every test starts from empty stores.
beforeEach(() => {
  users.reset();
  hooks.reset();
  apikeys.reset();
  vi.clearAllMocks();
});

describe.each(mutations)('$name', (m) => {
  it('a refresh() that started before it and resolves after it keeps its result', async () => {
    await m.on.seed();
    const answerList = m.on.listLater();
    const refresh = m.on.store.refresh();

    m.succeed();
    await m.run();
    expect(get(m.on.store)).toEqual(m.after);

    answerList('before');
    await refresh;
    expect(get(m.on.store)).toEqual(m.after);
  });

  it('rejected by the API, it lets a refresh() in flight set its list', async () => {
    await m.on.seed();
    const answerList = m.on.listLater();
    const refresh = m.on.store.refresh();

    m.fail(new Error('rejected'));
    await expect(m.run()).rejects.toThrow('rejected');
    expect(get(m.on.store)).toEqual(m.on.before);

    answerList('fresh');
    await refresh;
    expect(get(m.on.store)).toEqual(m.on.fresh);
  });
});

describe.each(mutations)('$name answered after a logout', (m) => {
  it('leaves the emptied store empty', async () => {
    await m.on.seed();
    const answer = m.succeedLater();
    const running = m.run();

    m.on.store.reset();
    answer();
    await running;
    expect(get(m.on.store)).toEqual([]);
  });

  it("keeps the next session's list", async () => {
    await m.on.seed();
    const answer = m.succeedLater();
    const running = m.run();

    m.on.store.reset();
    const answerList = m.on.listLater();
    const refresh = m.on.store.refresh();
    answer();
    await running;
    answerList('fresh');
    await refresh;
    expect(get(m.on.store)).toEqual(m.on.fresh);
  });
});

describe.each([USERS, HOOKS, APIKEYS])('$name store refresh()', (s) => {
  it('keeps the newer list when the older refresh() resolves last', async () => {
    const answerOlder = s.listLater();
    const older = s.store.refresh();
    const answerNewer = s.listLater();
    const newer = s.store.refresh();

    answerNewer('fresh');
    await newer;
    expect(get(s.store)).toEqual(s.fresh);

    answerOlder('before');
    await older;
    expect(get(s.store)).toEqual(s.fresh);
  });
});
