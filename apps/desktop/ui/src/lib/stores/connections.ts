// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Connections store. Loads, caches and saves connections via the
// Tauri bridge. Filter + search are derived stores - the UI reads them directly.

import { writable, derived, get } from 'svelte/store';
import * as bridge from '$lib/bridge';
import type { AuthSession, Connection, ConnectionKind, Settings } from '$lib/bridge/types';
import { groupConnectionsByHost, type ConnectionGroup } from '$lib/models/connection';

export type KindFilter = 'all' | 'ssh' | 'rdp' | 'web';
export type GroupFilter = 'single' | 'grouped';
export type ViewMode = 'list' | 'tree';

interface ConnectionsState {
  items: Connection[];
  loading: boolean;
  error: string | null;
}

const initial: ConnectionsState = { items: [], loading: false, error: null };
const _state = writable<ConnectionsState>(initial);

export const connectionsStore = { subscribe: _state.subscribe };
export const connections = derived(_state, ($s) => $s.items);
export const loading = derived(_state, ($s) => $s.loading);

export const searchTerm = writable<string>('');
export const kindFilter = writable<KindFilter>('all');
export const groupFilter = writable<GroupFilter>('single');
export const viewMode = writable<ViewMode>('list');

export const filteredConnections = derived(
  [_state, searchTerm, kindFilter],
  ([$s, $term, $kind]) => {
    const q = $term.trim().toLowerCase();
    return $s.items
      .filter((c) => {
        if ($kind !== 'all' && c.kind !== $kind) return false;
        if (!q) return true;
        const haystack = [
          c.name,
          c.host ?? '',
          c.url ?? '',
          c.username ?? '',
          c.domain ?? '',
          ...(c.tags ?? []),
        ]
          .join(' ')
          .toLowerCase();
        return haystack.includes(q);
      })
      .sort((a, b) => String(a.name ?? '').localeCompare(String(b.name ?? '')));
  },
);

export const groupedConnections = derived([_state, searchTerm], ([$s, $term]): ConnectionGroup[] =>
  groupConnectionsByHost($s.items, $term),
);

export async function load(): Promise<void> {
  _state.update((s) => ({ ...s, loading: true, error: null }));
  try {
    const items = await bridge.loadConnections();
    _state.set({ items, loading: false, error: null });
  } catch (err) {
    _state.set({
      items: [],
      loading: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
}

export async function reloadForMode(
  settings: Settings | null,
  session: AuthSession | null,
): Promise<void> {
  if (!settings) return load();
  _state.update((s) => ({ ...s, loading: true, error: null }));
  try {
    if (settings.mode === 'server' && session) {
      const items = await bridge.fetchConnectionsJwt(session.serverUrl, session.token);
      _state.set({ items, loading: false, error: null });
    } else if (settings.mode === 'sync' && settings.url) {
      const items = await bridge.syncConnections(settings.url);
      _state.set({ items, loading: false, error: null });
    } else {
      const items = await bridge.loadConnections();
      _state.set({ items, loading: false, error: null });
    }
  } catch (err) {
    _state.set({
      items: [],
      loading: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
}

export async function saveAll(items: Connection[]): Promise<void> {
  await bridge.saveConnections(items);
  _state.update((s) => ({ ...s, items }));
}

export async function upsert(conn: Connection): Promise<void> {
  const current = get(_state).items;
  const idx = current.findIndex((c) => c.id === conn.id);
  const next = idx >= 0 ? current.map((c, i) => (i === idx ? conn : c)) : [...current, conn];
  await saveAll(next);
}

/** Patches an item only in the memory store (no persistence). For sync and server mode. */
export function patchInMemory(conn: Connection): void {
  _state.update((s) => ({
    ...s,
    items: s.items.map((c) => (c.id === conn.id ? conn : c)),
  }));
}

export async function remove(id: string): Promise<void> {
  const next = get(_state).items.filter((c) => c.id !== id);
  await saveAll(next);
}

export function countByKind(): Record<ConnectionKind | 'total', number> {
  const items = get(_state).items;
  return {
    total: items.length,
    ssh: items.filter((c) => c.kind === 'ssh').length,
    rdp: items.filter((c) => c.kind === 'rdp').length,
    web: items.filter((c) => c.kind === 'web').length,
  };
}

export function recentConnections(limit = 5): Connection[] {
  return get(_state)
    .items.filter((c) => c.lastUsed)
    .sort((a, b) => {
      const ta = a.lastUsed ? Date.parse(a.lastUsed) : 0;
      const tb = b.lastUsed ? Date.parse(b.lastUsed) : 0;
      return tb - ta;
    })
    .slice(0, limit);
}
