// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Connections store. Loads, caches and saves connections via the
// Tauri bridge. Filter + search are derived stores - the UI reads them directly.

import { errMsg } from '$lib/utils/errors';
import { writable, derived, get } from 'svelte/store';
import * as bridge from '$lib/bridge';
import type { AuthSession, Connection, ConnectionKind, Settings } from '$lib/bridge/types';
import type { Connection as ServerConnection } from '$lib/api/types';
import { groupConnectionsByHost, type ConnectionGroup } from '$lib/models/connection';
import { connectionsApi } from '$lib/api/connections';
import { sessionStore } from './session';
import { showStatus } from './statusBar';
import { tNow } from '$lib/i18n';

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

// Group once per items change — the expensive part (URL parsing, sorting, haystack building) — then
// let the search filter cheaply on the prebuilt haystack, instead of re-grouping on every keystroke
// (5.13).
const allGroups = derived(_state, ($s): ConnectionGroup[] => groupConnectionsByHost($s.items, ''));

export const groupedConnections = derived(
  [allGroups, searchTerm],
  ([$groups, $term]): ConnectionGroup[] => {
    const q = $term.trim().toLowerCase();
    return q ? $groups.filter((g) => g.haystack.includes(q)) : $groups;
  },
);

// Shared request generation: load() (cache read) and reloadForMode() (network fetch) both write
// _state, and the pages mount a load while login() runs a reloadForMode in parallel. Without a
// shared generation a stale read (e.g. the OLD server's still-cached connections.json) could
// overwrite the new server's fetch, leaving the wrong server's connections shown and clickable —
// there was no out-of-order guard here, unlike the monitoring store's statusGen (4.39).
let loadGen = 0;

export async function load(): Promise<void> {
  const gen = ++loadGen;
  _state.update((s) => ({ ...s, loading: true, error: null }));
  try {
    const items = await bridge.loadConnections();
    if (gen !== loadGen) return;
    _state.set({ items, loading: false, error: null });
  } catch (err) {
    if (gen !== loadGen) return;
    _state.set({ items: [], loading: false, error: errMsg(err) });
  }
}

/** Mode-aware entry point for page mounts: reload connections for the current session's mode
 * instead of blindly reading the cache while a login's network fetch is in flight (4.39). */
export async function loadForCurrentMode(): Promise<void> {
  const { settings, session } = get(sessionStore);
  await reloadForMode(settings, session);
}

export async function reloadForMode(
  settings: Settings | null,
  session: AuthSession | null,
): Promise<void> {
  if (!settings) return load();
  const gen = ++loadGen;
  _state.update((s) => ({ ...s, loading: true, error: null }));
  try {
    let items: Connection[];
    if (settings.mode === 'server' && session) {
      items = await bridge.fetchConnectionsJwt(session.serverUrl, session.token);
    } else if (settings.mode === 'sync' && settings.url) {
      items = await bridge.syncConnections(settings.url);
    } else {
      items = await bridge.loadConnections();
    }
    if (gen !== loadGen) return;
    _state.set({ items, loading: false, error: null });
  } catch (err) {
    if (gen !== loadGen) return;
    _state.set({ items: [], loading: false, error: errMsg(err) });
  }
}

export async function saveAll(items: Connection[]): Promise<void> {
  await bridge.saveConnections(items);
  _state.update((s) => ({ ...s, items }));
}

/** Clears the in-memory connection list WITHOUT touching connections.json.
 * A server/sync fetch DOES write connections.json on the Rust side (it's the transient
 * server/sync cache), but in LOCAL mode connections.json is the user's persistent store.
 * Logout must drop the in-memory view but must NOT overwrite that file — in local mode that
 * would erase the user's locally saved connections. */
export function clearInMemory(): void {
  _state.set({ items: [], loading: false, error: null });
}

/** Maps the launcher's bridge connection onto the camelCase payload the server
 * API expects. The id is never sent — it routes the request (PUT) or is assigned
 * by the server (POST). serverId rides along so a server-mode edit keeps the
 * server association. */
function toServerPayload(conn: Connection): Partial<ServerConnection> {
  return {
    name: conn.name,
    kind: conn.kind,
    host: conn.host ?? null,
    port: conn.port ?? null,
    username: conn.username ?? null,
    domain: conn.domain ?? null,
    keyPath: conn.keyPath ?? null,
    url: conn.url ?? null,
    notes: conn.notes ?? null,
    tags: conn.tags ?? [],
    trustCert: conn.trustCert,
    serverId: conn.serverId ?? null,
  };
}

export async function upsert(conn: Connection): Promise<void> {
  const { settings, session } = get(sessionStore);
  // Server mode: connections are owned by the server — write through the API and
  // refresh from it. Local/sync mode keeps the file-backed behaviour below.
  if (settings?.mode === 'server' && session) {
    const exists = get(_state).items.some((c) => c.id === conn.id);
    if (exists) {
      await connectionsApi.update(session, conn.id, toServerPayload(conn));
    } else {
      await connectionsApi.create(session, toServerPayload(conn));
    }
    await reloadForMode(settings, session);
    return;
  }
  const current = get(_state).items;
  const idx = current.findIndex((c) => c.id === conn.id);
  const next = idx >= 0 ? current.map((c, i) => (i === idx ? conn : c)) : [...current, conn];
  if (settings?.mode === 'sync') {
    // Sync mode is read-through: connections.json is the transient cache the next sync (~1 min)
    // overwrites wholesale. Persisting an edit would silently vanish, so keep it in-memory only
    // and tell the user it's volatile instead of falsely showing "saved" (4.40).
    _state.update((s) => ({ ...s, items: next }));
    showStatus(tNow('status.syncEditVolatile'));
    return;
  }
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
  const { settings, session } = get(sessionStore);
  if (settings?.mode === 'server' && session) {
    await connectionsApi.remove(session, id);
    await reloadForMode(settings, session);
    return;
  }
  const next = get(_state).items.filter((c) => c.id !== id);
  if (settings?.mode === 'sync') {
    // Same as upsert: a sync-mode delete only lives until the next sync overwrites the cache
    // (4.40) — keep it in-memory and flag it as volatile rather than pretending it persisted.
    _state.update((s) => ({ ...s, items: next }));
    showStatus(tNow('status.syncEditVolatile'));
    return;
  }
  await saveAll(next);
}

/** Re-pulls connections from the server (server mode only). Lets other surfaces
 * (e.g. the infrastructure hub) keep the launcher's list fresh after they write. */
export async function refreshFromServer(): Promise<void> {
  const { settings, session } = get(sessionStore);
  if (settings?.mode === 'server' && session) {
    await reloadForMode(settings, session);
  }
}

export const kindCounts = derived(
  _state,
  ($s): Record<ConnectionKind | 'total', number> => ({
    total: $s.items.length,
    ssh: $s.items.filter((c) => c.kind === 'ssh').length,
    rdp: $s.items.filter((c) => c.kind === 'rdp').length,
    web: $s.items.filter((c) => c.kind === 'web').length,
  }),
);

// The dashboard's "recently used" list: most-recent first, capped.
const RECENT_LIMIT = 5;
export const recentConnections = derived(_state, ($s): Connection[] =>
  $s.items
    .filter((c) => c.lastUsed)
    .sort((a, b) => {
      const ta = a.lastUsed ? Date.parse(a.lastUsed) : 0;
      const tb = b.lastUsed ? Date.parse(b.lastUsed) : 0;
      return tb - ta;
    })
    .slice(0, RECENT_LIMIT),
);
