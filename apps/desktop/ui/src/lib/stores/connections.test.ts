// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';
import type { Connection } from '$lib/bridge/types';

// Mock the bridge: the state transition logic (saveAll/upsert/remove) is what
// we want to test — persistence is just a side channel.
vi.mock('$lib/bridge', () => ({
  saveConnections: vi.fn(async () => {}),
  loadConnections: vi.fn(async () => []),
  probeTargets: vi.fn(async (targets: unknown[]) => targets.map(() => 5)),
}));

// Mock the session (mode) + status bar so the sync-mode volatility path (4.40) is testable.
// Default settings=null keeps every other test on the local/file-backed path.
const h = vi.hoisted(() => ({
  sess: { settings: null as unknown, session: null as unknown },
  showStatus: vi.fn(),
  setFavoriteConnections: vi.fn(),
}));
vi.mock('./session', () => ({
  sessionStore: {
    subscribe: (fn: (v: unknown) => void) => {
      fn(h.sess);
      return () => {};
    },
  },
  setFavoriteConnections: h.setFavoriteConnections,
}));
vi.mock('./statusBar', () => ({ showStatus: h.showStatus, reportError: vi.fn() }));
vi.mock('$lib/i18n', () => ({ tNow: (k: string) => k, setLanguage: vi.fn() }));

import * as bridge from '$lib/bridge';
import {
  searchTerm,
  connections,
  saveAll,
  upsert,
  remove,
  patchInMemory,
  clearInMemory,
  kindCounts,
  recentConnections,
  load,
  favorites,
  toggleFavorite,
  reachability,
  probeVisible,
  startReachability,
  PROBE_INTERVAL_MS,
} from './connections';

const conn = (over: Partial<Connection>): Connection => ({
  id: 'id',
  name: 'name',
  kind: 'ssh',
  host: null,
  port: null,
  username: null,
  domain: null,
  keyPath: null,
  url: null,
  notes: null,
  tags: [],
  trustCert: false,
  lastUsed: null,
  ...over,
});

async function seed(items: Connection[]): Promise<void> {
  await saveAll(items);
}

describe('connections store', () => {
  beforeEach(async () => {
    searchTerm.set('');
    await saveAll([]);
  });

  describe('saveAll / state', () => {
    it('replaces the items list', async () => {
      await seed([conn({ id: 'a', name: 'Alpha' })]);
      expect(get(connections).map((c) => c.id)).toEqual(['a']);
      await seed([conn({ id: 'b', name: 'Beta' })]);
      expect(get(connections).map((c) => c.id)).toEqual(['b']);
    });
  });

  describe('upsert', () => {
    it('appends a new connection', async () => {
      await seed([conn({ id: 'a', name: 'Alpha' })]);
      await upsert(conn({ id: 'b', name: 'Beta' }));
      expect(get(connections).map((c) => c.id)).toEqual(['a', 'b']);
    });

    it('replaces an existing connection in place (no reorder)', async () => {
      await seed([conn({ id: 'a', name: 'Alpha' }), conn({ id: 'b', name: 'Beta' })]);
      await upsert(conn({ id: 'a', name: 'Alpha renamed' }));
      const items = get(connections);
      expect(items.map((c) => c.id)).toEqual(['a', 'b']);
      expect(items[0].name).toBe('Alpha renamed');
    });
  });

  describe('remove', () => {
    it('drops the matching id and keeps the rest', async () => {
      await seed([conn({ id: 'a' }), conn({ id: 'b' }), conn({ id: 'c' })]);
      await remove('b');
      expect(get(connections).map((c) => c.id)).toEqual(['a', 'c']);
    });

    it('is a no-op for an unknown id', async () => {
      await seed([conn({ id: 'a' })]);
      await remove('zzz');
      expect(get(connections).map((c) => c.id)).toEqual(['a']);
    });
  });

  describe('patchInMemory', () => {
    it('updates a single item without touching others', async () => {
      await seed([conn({ id: 'a', name: 'A' }), conn({ id: 'b', name: 'B' })]);
      patchInMemory(conn({ id: 'b', name: 'B2' }));
      const items = get(connections);
      expect(items.find((c) => c.id === 'a')?.name).toBe('A');
      expect(items.find((c) => c.id === 'b')?.name).toBe('B2');
    });

    it('ignores an id that is not present', async () => {
      await seed([conn({ id: 'a', name: 'A' })]);
      patchInMemory(conn({ id: 'ghost', name: 'X' }));
      expect(get(connections).map((c) => c.id)).toEqual(['a']);
    });
  });

  describe('clearInMemory', () => {
    it('empties the in-memory list without writing connections.json', async () => {
      await seed([conn({ id: 'a' }), conn({ id: 'b' })]);
      vi.mocked(bridge.saveConnections).mockClear();
      clearInMemory();
      expect(get(connections)).toEqual([]);
      // The on-disk connections.json is the local-mode store. Logout drops the
      // in-memory (server-mode) view via clearInMemory and must NOT overwrite
      // that file — otherwise the user's locally saved connections are lost.
      expect(bridge.saveConnections).not.toHaveBeenCalled();
    });
  });

  describe('kindCounts', () => {
    it('counts per kind and total', async () => {
      await seed([
        conn({ id: '1', kind: 'ssh' }),
        conn({ id: '2', kind: 'ssh' }),
        conn({ id: '3', kind: 'rdp' }),
        conn({ id: '4', kind: 'web' }),
      ]);
      expect(get(kindCounts)).toEqual({ total: 4, ssh: 2, rdp: 1, web: 1 });
    });

    it('is all-zero for an empty store', () => {
      expect(get(kindCounts)).toEqual({ total: 0, ssh: 0, rdp: 0, web: 0 });
    });
  });

  describe('recentConnections', () => {
    it('returns only used connections, newest first', async () => {
      await seed([
        conn({ id: 'old', lastUsed: '2024-01-01T00:00:00Z' }),
        conn({ id: 'never', lastUsed: null }),
        conn({ id: 'new', lastUsed: '2024-06-01T00:00:00Z' }),
        conn({ id: 'mid', lastUsed: '2024-03-01T00:00:00Z' }),
      ]);
      expect(get(recentConnections).map((c) => c.id)).toEqual(['new', 'mid', 'old']);
    });

    it('caps at 5, newest first', async () => {
      await seed(
        ['a', 'b', 'c', 'd', 'e', 'f'].map((id, i) =>
          conn({ id, lastUsed: `2024-0${i + 1}-01T00:00:00Z` }),
        ),
      );
      expect(get(recentConnections).map((c) => c.id)).toEqual(['f', 'e', 'd', 'c', 'b']);
    });
  });
});

describe('load generation guard (4.39)', () => {
  beforeEach(async () => {
    vi.mocked(bridge.loadConnections).mockReset();
    vi.mocked(bridge.loadConnections).mockResolvedValue([]);
    await saveAll([]);
  });

  it('drops a superseded load so the newer call wins', async () => {
    const older = conn({ id: 'old-server' });
    const newer = conn({ id: 'new-server' });
    // The FIRST load's fetch resolves LAST (slow); the second resolves first (fast).
    let resolveFirst!: (v: Connection[]) => void;
    vi.mocked(bridge.loadConnections)
      .mockImplementationOnce(
        () =>
          new Promise<Connection[]>((r) => {
            resolveFirst = r;
          }),
      )
      .mockImplementationOnce(async () => [newer]);

    const p1 = load(); // gen 1 (slow)
    const p2 = load(); // gen 2 (fast) -> wins
    await p2;
    expect(get(connections)).toEqual([newer]);
    resolveFirst([older]); // gen 1 resolves late...
    await p1;
    expect(get(connections)).toEqual([newer]); // ...but is dropped; newer stays
  });
});

describe('sync-mode edits are volatile (4.40)', () => {
  beforeEach(async () => {
    h.sess.settings = null;
    await saveAll([conn({ id: 'a', name: 'A' })]);
    h.sess.settings = { mode: 'sync', url: 'https://srv' };
    h.showStatus.mockClear();
    vi.mocked(bridge.saveConnections).mockClear();
  });
  afterEach(() => {
    h.sess.settings = null;
  });

  it('upsert keeps the edit in-memory but does NOT persist to the cache', async () => {
    await upsert(conn({ id: 'a', name: 'edited' }));
    expect(get(connections).find((c) => c.id === 'a')?.name).toBe('edited');
    expect(bridge.saveConnections).not.toHaveBeenCalled();
    expect(h.showStatus).toHaveBeenCalledWith('status.syncEditVolatile');
  });

  it('remove drops it in-memory but does NOT persist', async () => {
    await remove('a');
    expect(get(connections).find((c) => c.id === 'a')).toBeUndefined();
    expect(bridge.saveConnections).not.toHaveBeenCalled();
    expect(h.showStatus).toHaveBeenCalledWith('status.syncEditVolatile');
  });
});

describe('favorites (R-1065)', () => {
  beforeEach(() => {
    h.sess.settings = { mode: 'local', favoriteConnections: ['a'] };
    h.setFavoriteConnections.mockReset();
    // As the session store does: the saved list becomes the current settings.
    h.setFavoriteConnections.mockImplementation(async (ids: string[]) => {
      await Promise.resolve();
      h.sess.settings = { ...(h.sess.settings as object), favoriteConnections: ids };
    });
  });
  afterEach(() => {
    h.sess.settings = null;
  });

  it('reads the starred ids from the settings', () => {
    expect([...get(favorites)]).toEqual(['a']);
  });

  it('adds and removes an id and always saves the whole list', async () => {
    await toggleFavorite('b');
    expect(h.setFavoriteConnections).toHaveBeenLastCalledWith(['a', 'b']);
    await toggleFavorite('a');
    expect(h.setFavoriteConnections).toHaveBeenLastCalledWith(['b']);
  });

  it('keeps both of two quick toggles', async () => {
    await Promise.all([toggleFavorite('b'), toggleFavorite('c')]);
    expect(h.setFavoriteConnections).toHaveBeenLastCalledWith(['a', 'b', 'c']);
  });

  it('a failed save does not block the next toggle', async () => {
    h.setFavoriteConnections.mockRejectedValueOnce(new Error('disk'));
    await expect(toggleFavorite('b')).rejects.toThrow('disk');
    await toggleFavorite('c');
    expect(h.setFavoriteConnections).toHaveBeenLastCalledWith(['a', 'c']);
  });
});

describe('reachability (R-1067)', () => {
  const probe = () => vi.mocked(bridge.probeTargets);
  beforeEach(() => {
    probe().mockReset();
    probe().mockImplementation(async (targets) => targets.map((_, i) => 10 + i));
  });

  it('dials ssh/rdp host and port and web URLs, marks tunneled ones, skips the rest', async () => {
    await probeVisible(
      [
        conn({ id: 's', kind: 'ssh', host: 'srv.example', port: null }),
        conn({ id: 'r', kind: 'rdp', host: 'win.example', port: 3390 }),
        conn({ id: 'w', kind: 'web', url: 'https://web.example:8443/x' }),
        conn({ id: 't', kind: 'ssh', host: 'behind.frp', port: 22 }),
        conn({ id: 'n', kind: 'ssh', host: null }),
      ],
      new Set(['t']),
    );
    expect(probe()).toHaveBeenCalledTimes(1);
    expect(probe().mock.calls[0][0]).toEqual([
      { host: 'srv.example', port: 22 },
      { host: 'win.example', port: 3390 },
      { host: 'web.example', port: 8443 },
    ]);
    const r = get(reachability);
    expect([r.s, r.r, r.w, r.t]).toEqual([10, 11, 12, 'tunnel']);
    expect(r.n).toBeUndefined();
  });

  it('dials a shared host and port once and gives every connection its answer', async () => {
    probe().mockResolvedValueOnce([null]);
    await probeVisible(
      [
        conn({ id: 'x1', host: 'same.example', port: 22 }),
        conn({ id: 'x2', host: 'same.example', port: 22 }),
      ],
      new Set(),
    );
    expect(probe().mock.calls[0][0]).toHaveLength(1);
    const r = get(reachability);
    expect([r.x1, r.x2]).toEqual([null, null]);
  });

  it('splits more than 256 targets into several calls', async () => {
    const many = Array.from({ length: 300 }, (_, i) =>
      conn({ id: `m${i}`, host: `h${i}.example` }),
    );
    await probeVisible(many, new Set());
    expect(probe().mock.calls.map((c) => c[0].length)).toEqual([256, 44]);
    expect(get(reachability).m299).toBe(10 + 43);
  });

  it('forgets the last value of a connection that lost its target', async () => {
    await probeVisible([conn({ id: 'g', host: 'gone.example', port: 22 })], new Set());
    expect(get(reachability).g).toBe(10);
    await probeVisible([conn({ id: 'g', host: null })], new Set());
    expect(get(reachability).g).toBeUndefined();
  });

  describe('startReachability', () => {
    let hidden = false;
    let visibility: { mockRestore: () => void };
    beforeEach(() => {
      vi.useFakeTimers();
      hidden = false;
      visibility = vi
        .spyOn(document, 'visibilityState', 'get')
        .mockImplementation(() => (hidden ? 'hidden' : 'visible'));
    });
    afterEach(() => {
      vi.useRealTimers();
      visibility.mockRestore();
    });
    const visible = () => ({
      conns: [conn({ id: 'v', host: 'v.example' })],
      tunneled: new Set<string>(),
    });

    it('probes at once and then every interval, not while hidden, and stops', async () => {
      const stop = startReachability(visible);
      await vi.advanceTimersByTimeAsync(0);
      expect(probe()).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(PROBE_INTERVAL_MS);
      expect(probe()).toHaveBeenCalledTimes(2);
      hidden = true;
      await vi.advanceTimersByTimeAsync(PROBE_INTERVAL_MS);
      expect(probe()).toHaveBeenCalledTimes(2);
      hidden = false;
      document.dispatchEvent(new Event('visibilitychange'));
      await vi.advanceTimersByTimeAsync(0);
      expect(probe()).toHaveBeenCalledTimes(3);
      stop();
      await vi.advanceTimersByTimeAsync(PROBE_INTERVAL_MS * 3);
      document.dispatchEvent(new Event('visibilitychange'));
      expect(probe()).toHaveBeenCalledTimes(3);
    });

    it('does not probe again on a visibility change within the interval', async () => {
      const stop = startReachability(visible);
      await vi.advanceTimersByTimeAsync(0);
      document.dispatchEvent(new Event('visibilitychange'));
      await vi.advanceTimersByTimeAsync(0);
      expect(probe()).toHaveBeenCalledTimes(1);
      stop();
    });

    it('keeps the last values when a probe fails', async () => {
      await probeVisible(visible().conns, new Set());
      probe().mockRejectedValueOnce(new Error('ipc'));
      const stop = startReachability(visible);
      await vi.advanceTimersByTimeAsync(0);
      expect(get(reachability).v).toBe(10);
      stop();
    });
  });
});
