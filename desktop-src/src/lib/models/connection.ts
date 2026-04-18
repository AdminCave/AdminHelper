// Connection-Modell: Normalisierung, Validierung, Darstellungs-Helfer.
// 1:1-Port von desktop/src/connectionModel.js mit TS-Typen.

import type { Connection, ConnectionKind } from '$lib/bridge/types';

export const DEFAULT_PORTS: Record<Extract<ConnectionKind, 'ssh' | 'rdp'>, number> = {
  ssh: 22,
  rdp: 3389,
};

export function normalizeConnection(raw: Partial<Connection> & Record<string, unknown>): Connection {
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
    ? (raw.tags as unknown[])
        .map((tag) => String(tag).trim())
        .filter((tag) => tag.length > 0)
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
    return { ok: false, message: 'Name darf nicht leer sein' };
  }
  if (c.kind === 'web') {
    if (!c.url) return { ok: false, message: 'URL darf nicht leer sein' };
    return { ok: true };
  }
  if (!c.host) return { ok: false, message: 'Host darf nicht leer sein' };
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
