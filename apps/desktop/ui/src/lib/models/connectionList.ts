// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The connection list (R-1065): library, filters, sorting, grouping, quick access and the
// command preview, as pure functions over the loaded connections.

import type { Connection, ConnectionKind } from '$lib/bridge/types';
import { csvCell } from '$lib/charts';
import { DEFAULT_PORTS, connectionGroupingHost } from './connection';

export type Library = 'all' | 'favorites' | 'recent' | 'tunnel';
export type SortKey = 'name' | 'ping' | 'lastUsed';
export type SortDir = 'asc' | 'desc';
export type Grouping = 'host' | 'tag' | 'kind' | 'none';
/** Latency in ms, null when unreachable, 'tunnel' when not probed, undefined while unknown. */
export type Reach = number | null | 'tunnel' | undefined;

export const LIBRARIES: readonly Library[] = ['all', 'favorites', 'recent', 'tunnel'];
export const KINDS: readonly ConnectionKind[] = ['ssh', 'rdp', 'web'];
export const RECENT_MS = 24 * 60 * 60 * 1000;
export const QUICK_ACCESS_MAX = 4;
/** Key of the group that collects connections without a host or without a tag. */
export const NO_GROUP = '';

export interface ListContext {
  favorites: ReadonlySet<string>;
  /** Ids of connections that run through an enabled tunnel mapping. */
  tunneled: ReadonlySet<string>;
  /** Epoch ms. */
  now: number;
}

export interface ListFilter {
  library: Library;
  kind: ConnectionKind | null;
  tag: string | null;
  search: string;
}

export interface ListGroup {
  key: string;
  connections: Connection[];
}

function usedAt(c: Connection): number | null {
  if (!c.lastUsed) return null;
  const t = Date.parse(c.lastUsed);
  return Number.isNaN(t) ? null : t;
}

export function inLibrary(c: Connection, library: Library, ctx: ListContext): boolean {
  switch (library) {
    case 'all':
      return true;
    case 'favorites':
      return ctx.favorites.has(c.id);
    case 'recent': {
      const t = usedAt(c);
      return t != null && ctx.now - t <= RECENT_MS;
    }
    case 'tunnel':
      return ctx.tunneled.has(c.id);
  }
}

function matchesSearch(c: Connection, q: string): boolean {
  if (!q) return true;
  return [c.name, c.host ?? '', c.url ?? '', c.username ?? '', c.domain ?? '', ...(c.tags ?? [])]
    .join(' ')
    .toLowerCase()
    .includes(q);
}

export function filterConnections(
  items: readonly Connection[],
  filter: ListFilter,
  ctx: ListContext,
): Connection[] {
  const q = filter.search.trim().toLowerCase();
  return items.filter(
    (c) =>
      inLibrary(c, filter.library, ctx) &&
      (filter.kind == null || c.kind === filter.kind) &&
      (filter.tag == null || (c.tags ?? []).includes(filter.tag)) &&
      matchesSearch(c, q),
  );
}

export function libraryCounts(
  items: readonly Connection[],
  ctx: ListContext,
): Record<Library, number> {
  const counts = { all: 0, favorites: 0, recent: 0, tunnel: 0 };
  for (const c of items) for (const l of LIBRARIES) if (inLibrary(c, l, ctx)) counts[l] += 1;
  return counts;
}

export function kindCounts(items: readonly Connection[]): Record<ConnectionKind, number> {
  const counts = { ssh: 0, rdp: 0, web: 0 };
  for (const c of items) counts[c.kind] += 1;
  return counts;
}

/** Each tag with the number of connections carrying it, by tag name. */
export function tagCounts(items: readonly Connection[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const c of items) for (const t of c.tags ?? []) counts.set(t, (counts.get(t) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

const byName = (a: Connection, b: Connection) =>
  String(a.name ?? '').localeCompare(String(b.name ?? ''));

/**
 * Sorts by the key; connections without a value (never used, not probed, unreachable)
 * stay at the end in both directions, ties go by name.
 */
export function sortConnections(
  items: readonly Connection[],
  key: SortKey,
  dir: SortDir,
  reach: Readonly<Record<string, Reach>> = {},
): Connection[] {
  const sign = dir === 'asc' ? 1 : -1;
  if (key === 'name') return [...items].sort((a, b) => sign * byName(a, b));
  const value = (c: Connection): number | null => {
    if (key === 'lastUsed') return usedAt(c);
    const r = reach[c.id];
    return typeof r === 'number' ? r : null;
  };
  return [...items].sort((a, b) => {
    const va = value(a);
    const vb = value(b);
    if (va == null || vb == null)
      return va == null && vb == null ? byName(a, b) : va == null ? 1 : -1;
    return sign * (va - vb) || byName(a, b);
  });
}

/**
 * The server a connection groups under 'host' ("by server"): its server's name, from
 * `serverNames` where the caller knows the servers, else from the display name the server
 * derived (R-1210). A connection without a server groups by its host.
 */
function groupingServer(c: Connection, serverNames: Readonly<Record<string, string>>): string {
  if (!c.serverId) return connectionGroupingHost(c).toLowerCase();
  return serverNames[c.serverId] ?? c.name.split(' · ')[0];
}

/**
 * Groups the (already sorted) connections, keeping their order inside each group. Under
 * 'tag' a connection appears once per tag. NO_GROUP collects those without a host or tag
 * and comes last; 'none' gives a single group.
 */
export function groupConnections(
  items: readonly Connection[],
  grouping: Grouping,
  serverNames: Readonly<Record<string, string>> = {},
): ListGroup[] {
  if (grouping === 'none') return [{ key: NO_GROUP, connections: [...items] }];
  const groups = new Map<string, Connection[]>();
  const add = (key: string, c: Connection) => {
    const list = groups.get(key);
    if (list) list.push(c);
    else groups.set(key, [c]);
  };
  for (const c of items) {
    if (grouping === 'kind') add(c.kind, c);
    else if (grouping === 'host') add(groupingServer(c, serverNames), c);
    else if ((c.tags ?? []).length === 0) add(NO_GROUP, c);
    else for (const t of c.tags) add(t, c);
  }
  const keys = [...groups.keys()];
  if (grouping === 'kind')
    keys.sort((a, b) => KINDS.indexOf(a as ConnectionKind) - KINDS.indexOf(b as ConnectionKind));
  else keys.sort((a, b) => (a === NO_GROUP ? 1 : b === NO_GROUP ? -1 : a.localeCompare(b)));
  return keys.map((key) => ({ key, connections: groups.get(key) ?? [] }));
}

/** Favorites first, then the most recently used others; at most QUICK_ACCESS_MAX. */
export function quickAccess(items: readonly Connection[], ctx: ListContext): Connection[] {
  const recentFirst = sortConnections(items, 'lastUsed', 'desc');
  const favorites = recentFirst.filter((c) => ctx.favorites.has(c.id));
  const used = recentFirst.filter((c) => !ctx.favorites.has(c.id) && usedAt(c) != null);
  return [...favorites, ...used].slice(0, QUICK_ACCESS_MAX);
}

function quote(arg: string): string {
  return /^[\w@%+=:,./-]+$/.test(arg) ? arg : `'${arg.replace(/'/g, `'\\''`)}'`;
}

/** The URL as the backend opens it: a scheme-less value gets https:// in front. */
function webUrl(raw: string): string {
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(raw) ? raw : `https://${raw}`;
}

/**
 * What connecting runs, as a preview: the ssh arguments as the backend builds them
 * (connection/ssh.rs), xfreerdp with target, user and domain (the window and scaling
 * options come from the settings and are left out), the URL for web.
 */
export function commandPreview(c: Connection): string {
  if (c.kind === 'web') return c.url ? webUrl(c.url.trim()) : '';
  const host = c.host?.trim() ?? '';
  const user = c.username?.trim() ?? '';
  if (c.kind === 'ssh') {
    const port = c.port ?? DEFAULT_PORTS.ssh;
    const args = ['ssh'];
    if (port !== DEFAULT_PORTS.ssh) args.push('-p', String(port));
    const key = c.keyPath?.trim();
    if (key) args.push('-i', quote(key));
    args.push('--', quote(user ? `${user}@${host}` : host));
    return args.join(' ');
  }
  const args = ['xfreerdp', quote(`/v:${host}:${c.port ?? DEFAULT_PORTS.rdp}`)];
  if (user) args.push(quote(`/u:${user}`));
  const domain = c.domain?.trim();
  if (domain) args.push(quote(`/d:${domain}`));
  return args.join(' ');
}

/** Host and port a reachability probe dials, or null when there is nothing to dial. */
export function probeTarget(c: Connection): { host: string; port: number } | null {
  if (c.kind === 'web') {
    if (!c.url) return null;
    let u: URL;
    try {
      u = new URL(webUrl(c.url.trim()));
    } catch {
      return null;
    }
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
    const host = u.hostname.replace(/^\[(.*)\]$/, '$1');
    const port = u.port ? Number(u.port) : u.protocol === 'https:' ? 443 : 80;
    // Port 0 is saved but never dialed; the probe refuses it.
    return host && port > 0 ? { host, port } : null;
  }
  const host = c.host?.trim();
  const port = c.port ?? DEFAULT_PORTS[c.kind];
  return host && port > 0 ? { host, port } : null;
}

/** The connections as CSV for a spreadsheet; cells that would run as a formula are quoted. */
export function connectionsCsv(conns: readonly Connection[]): string {
  const header = 'name,type,host,port,user,url,tags';
  const rows = conns.map((c) =>
    [
      c.name,
      c.kind,
      c.host ?? '',
      c.port == null ? '' : String(c.port),
      c.username ?? '',
      c.url ?? '',
      c.tags.join(' '),
    ]
      .map(csvCell)
      .join(','),
  );
  return [header, ...rows].join('\n') + '\n';
}
