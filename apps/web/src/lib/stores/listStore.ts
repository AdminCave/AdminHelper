// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable, type Readable } from 'svelte/store';

export interface ListStore<T> extends Readable<T[]> {
  refresh(): Promise<void>;
  reset(): void;
  mutate<R>(call: () => Promise<R>, apply: (list: T[], result: R) => T[]): Promise<R>;
}

// A list loaded from the API, with a stale-response guard: a slow refresh() whose list() resolves
// AFTER a mutation (or a newer refresh) must not overwrite the current state — else e.g. a
// just-removed row reappears. Every mutation of the current session bumps the generation once its
// call succeeded, so an in-flight refresh drops its result (4.145); a refused call bumps nothing.
export function listStore<T>(fetchList: () => Promise<T[]>): ListStore<T> {
  const store = writable<T[]>([]);
  let refreshGen = 0;
  // Bumped only by reset(): a mutation answered after a logout belongs to the old session. Its
  // result goes back to the caller, but it neither touches the list nor bumps the generation —
  // the emptied store must stay empty, and a bump would drop the next session's first refresh().
  let sessionEpoch = 0;

  return {
    subscribe: store.subscribe,

    async refresh(): Promise<void> {
      const gen = ++refreshGen;
      const list = await fetchList();
      if (gen === refreshGen) store.set(list);
    },

    // Logout empties the store; the bump makes a refresh() still in flight drop its result.
    reset(): void {
      refreshGen++;
      sessionEpoch++;
      store.set([]);
    },

    async mutate<R>(call: () => Promise<R>, apply: (list: T[], result: R) => T[]): Promise<R> {
      const epoch = sessionEpoch;
      const result = await call();
      if (epoch !== sessionEpoch) return result;
      refreshGen++;
      store.update((list) => apply(list, result));
      return result;
    },
  };
}
