// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';
import type { Connection } from '$lib/bridge/types';

// Mock the bridge: the state transition logic (saveAll/upsert/remove) is what
// we want to test — persistence is just a side channel.
vi.mock('$lib/bridge', () => ({
  saveConnections: vi.fn(async () => {}),
  loadConnections: vi.fn(async () => []),
}));

import {
  searchTerm,
  kindFilter,
  filteredConnections,
  groupedConnections,
  connections,
  saveAll,
  upsert,
  remove,
  patchInMemory,
  countByKind,
  recentConnections,
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
    kindFilter.set('all');
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

  describe('filteredConnections (derived)', () => {
    beforeEach(async () => {
      await seed([
        conn({
          id: '1',
          name: 'Web Server',
          kind: 'web',
          url: 'https://prod.example.com',
        }),
        conn({
          id: '2',
          name: 'Alpha',
          kind: 'ssh',
          host: 'alpha.internal',
          username: 'root',
        }),
        conn({
          id: '3',
          name: 'Beta',
          kind: 'rdp',
          host: 'beta.internal',
          domain: 'CORP',
        }),
        conn({
          id: '4',
          name: 'Gamma',
          kind: 'ssh',
          host: 'gamma.internal',
          tags: ['db', 'prod'],
        }),
      ]);
    });

    it('sorts by name with empty search and "all" filter', () => {
      expect(get(filteredConnections).map((c) => c.name)).toEqual([
        'Alpha',
        'Beta',
        'Gamma',
        'Web Server',
      ]);
    });

    it('filters by kind', () => {
      kindFilter.set('ssh');
      expect(
        get(filteredConnections)
          .map((c) => c.id)
          .sort(),
      ).toEqual(['2', '4']);
    });

    it('matches search against host (case-insensitive)', () => {
      searchTerm.set('ALPHA.INTERNAL');
      expect(get(filteredConnections).map((c) => c.id)).toEqual(['2']);
    });

    it('matches search against url, username, domain and tags', () => {
      searchTerm.set('prod.example.com');
      expect(get(filteredConnections).map((c) => c.id)).toEqual(['1']);
      searchTerm.set('root');
      expect(get(filteredConnections).map((c) => c.id)).toEqual(['2']);
      searchTerm.set('corp');
      expect(get(filteredConnections).map((c) => c.id)).toEqual(['3']);
      searchTerm.set('db');
      expect(get(filteredConnections).map((c) => c.id)).toEqual(['4']);
    });

    it('combines kind filter and search', () => {
      kindFilter.set('ssh');
      searchTerm.set('gamma');
      expect(get(filteredConnections).map((c) => c.id)).toEqual(['4']);
    });

    it('returns empty when nothing matches', () => {
      searchTerm.set('nonexistent-xyz');
      expect(get(filteredConnections)).toEqual([]);
    });

    it('ignores surrounding whitespace in the search term', () => {
      searchTerm.set('   beta   ');
      expect(get(filteredConnections).map((c) => c.id)).toEqual(['3']);
    });
  });

  describe('groupedConnections (derived)', () => {
    it('groups connections that share a host', async () => {
      await seed([
        conn({ id: 's', name: 'box-ssh', kind: 'ssh', host: 'box.internal' }),
        conn({ id: 'r', name: 'box-rdp', kind: 'rdp', host: 'box.internal' }),
        conn({ id: 'o', name: 'other', kind: 'ssh', host: 'other.internal' }),
      ]);
      const groups = get(groupedConnections);
      const boxGroup = groups.find((g) => g.host === 'box.internal');
      expect(boxGroup?.connections.map((c) => c.id).sort()).toEqual(['r', 's']);
      expect(Object.keys(boxGroup?.byKind ?? {}).sort()).toEqual(['rdp', 'ssh']);
      expect(groups).toHaveLength(2);
    });
  });

  describe('countByKind', () => {
    it('counts per kind and total', async () => {
      await seed([
        conn({ id: '1', kind: 'ssh' }),
        conn({ id: '2', kind: 'ssh' }),
        conn({ id: '3', kind: 'rdp' }),
        conn({ id: '4', kind: 'web' }),
      ]);
      expect(countByKind()).toEqual({ total: 4, ssh: 2, rdp: 1, web: 1 });
    });

    it('is all-zero for an empty store', () => {
      expect(countByKind()).toEqual({ total: 0, ssh: 0, rdp: 0, web: 0 });
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
      expect(recentConnections().map((c) => c.id)).toEqual(['new', 'mid', 'old']);
    });

    it('honors the limit', async () => {
      await seed([
        conn({ id: 'a', lastUsed: '2024-01-01T00:00:00Z' }),
        conn({ id: 'b', lastUsed: '2024-02-01T00:00:00Z' }),
        conn({ id: 'c', lastUsed: '2024-03-01T00:00:00Z' }),
      ]);
      expect(recentConnections(2).map((c) => c.id)).toEqual(['c', 'b']);
    });
  });
});
