// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Connection model: normalization, validation, presentation helpers.

import type { Connection, ConnectionKind } from '$lib/bridge/types';
import { tNow } from '$lib/i18n';

export const DEFAULT_PORTS: Record<Extract<ConnectionKind, 'ssh' | 'rdp'>, number> = {
  ssh: 22,
  rdp: 3389,
};

export function normalizeConnection(
  raw: Partial<Connection> & Record<string, unknown>,
): Connection {
  const name = String(raw.name ?? '').trim();
  const kind = (raw.kind as ConnectionKind) || 'ssh';
  const host = String(raw.host ?? '').trim();
  const username = String(raw.username ?? '').trim();
  const domain = String(raw.domain ?? '').trim();
  const keyPath = String(raw.keyPath ?? '').trim();
  const url = String(raw.url ?? '').trim();
  const notes = String(raw.notes ?? '').trim();
  const trustCert = Boolean(raw.trustCert);
  const tags = Array.isArray(raw.tags)
    ? [
        ...new Set(
          (raw.tags as unknown[]).map((tag) => String(tag).trim()).filter((tag) => tag.length > 0),
        ),
      ]
    : [];

  let port: number | null = null;
  const rawPort = raw.port as unknown;
  if (rawPort !== null && rawPort !== undefined && rawPort !== '') {
    const parsed = Number(rawPort);
    if (!Number.isNaN(parsed)) port = parsed;
  }

  return {
    id: String(raw.id ?? (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString())),
    name,
    kind,
    host: host || null,
    port,
    username: username || null,
    domain: domain || null,
    keyPath: keyPath || null,
    url: url || null,
    notes: notes || null,
    trustCert,
    tags,
    lastUsed: (raw.lastUsed as string | null | undefined) ?? null,
  };
}

export function parseTags(raw: string): string[] {
  return raw
    .split(',')
    .map((tag) => tag.trim())
    .filter((tag) => tag.length > 0);
}

export interface ValidationResult {
  ok: boolean;
  message?: string;
}

export function validateConnection(c: Connection): ValidationResult {
  if (!c.name) {
    return { ok: false, message: tNow('validation.name.empty') };
  }
  if (c.kind === 'web') {
    if (!c.url) return { ok: false, message: tNow('validation.url.empty') };
    return { ok: true };
  }
  if (!c.host) return { ok: false, message: tNow('validation.host.empty') };
  return { ok: true };
}

export function toCardMeta(c: Connection): string {
  if (c.kind === 'web') return c.url || '-';
  const host = c.host || '-';
  const port = c.port ?? DEFAULT_PORTS[c.kind as 'ssh' | 'rdp'] ?? '-';
  const user = c.username ? `${c.username}@` : '';
  return `${user}${host}:${port}`;
}

export function emptyConnection(kind: ConnectionKind = 'ssh'): Connection {
  return {
    id: crypto.randomUUID(),
    name: '',
    kind,
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
  };
}

function parseUrlHost(rawUrl: string | null | undefined): string {
  const trimmed = String(rawUrl ?? '').trim();
  if (!trimmed) return '';
  try {
    return new URL(trimmed).hostname || '';
  } catch {
    try {
      return new URL(`https://${trimmed}`).hostname || '';
    } catch {
      return '';
    }
  }
}

function connectionGroupingHost(c: Connection): string {
  const host = String(c.host ?? '').trim();
  if (host) return host;
  if (c.kind === 'web') return parseUrlHost(c.url);
  return '';
}

function connectionHaystack(c: Connection): string {
  const tagText = (c.tags ?? []).join(' ');
  return `${c.name} ${c.host ?? ''} ${c.url ?? ''} ${c.domain ?? ''} ${tagText}`.toLowerCase();
}

function pickPreferredConnection(conns: Connection[]): Connection {
  return [...conns].sort((a, b) => {
    const aTime = a.lastUsed ? Date.parse(a.lastUsed) || 0 : 0;
    const bTime = b.lastUsed ? Date.parse(b.lastUsed) || 0 : 0;
    if (aTime !== bTime) return bTime - aTime;
    return String(a.name ?? '').localeCompare(String(b.name ?? ''));
  })[0];
}

export interface ConnectionGroup {
  key: string;
  host: string;
  displayName: string;
  connections: Connection[];
  byKind: Partial<Record<ConnectionKind, Connection>>;
  haystack: string;
}

export function groupConnectionsByHost(
  connections: Connection[],
  search: string,
): ConnectionGroup[] {
  const groups = new Map<
    string,
    {
      key: string;
      host: string;
      connections: Connection[];
      kindBuckets: Record<'ssh' | 'rdp' | 'web', Connection[]>;
    }
  >();
  const query = (search ?? '').toLowerCase();

  for (const c of connections) {
    const host = connectionGroupingHost(c);
    const normalizedHost = host.toLowerCase();
    const key = normalizedHost || `__${c.id}`;
    const displayHost = host || c.name || c.id;

    if (!groups.has(key)) {
      groups.set(key, {
        key,
        host: displayHost,
        connections: [],
        kindBuckets: { ssh: [], rdp: [], web: [] },
      });
    }
    const g = groups.get(key)!;
    g.connections.push(c);
    if (c.kind === 'ssh' || c.kind === 'rdp' || c.kind === 'web') {
      g.kindBuckets[c.kind].push(c);
    }
  }

  return Array.from(groups.values())
    .map((g) => {
      const byKind: Partial<Record<ConnectionKind, Connection>> = {};
      for (const kind of ['ssh', 'rdp', 'web'] as const) {
        if (g.kindBuckets[kind].length > 0) {
          byKind[kind] = pickPreferredConnection(g.kindBuckets[kind]);
        }
      }
      const preferred = pickPreferredConnection(g.connections);
      const displayName = String(preferred?.name ?? '').trim();
      const haystack = `${g.host} ${g.connections.map(connectionHaystack).join(' ')}`.toLowerCase();
      return {
        key: g.key,
        host: g.host,
        displayName,
        connections: g.connections,
        byKind,
        haystack,
      };
    })
    .filter((g) => !query || g.haystack.includes(query))
    .sort((a, b) => String(a.host ?? '').localeCompare(String(b.host ?? '')));
}

export function groupedTagKeys(group: ConnectionGroup, untaggedLabel: string): string[] {
  const tags = new Map<string, string>();
  for (const c of group.connections) {
    for (const raw of c.tags ?? []) {
      const normalized = String(raw ?? '').trim();
      if (!normalized) continue;
      const key = normalized.toLowerCase();
      if (!tags.has(key)) tags.set(key, normalized);
    }
  }
  if (tags.size === 0) return [untaggedLabel];
  return Array.from(tags.values());
}
