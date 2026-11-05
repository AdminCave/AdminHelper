// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Connection model: normalization, validation, presentation helpers.

import type {
  Connection,
  ConnectionKind,
  ConnectionOptions,
  RdpConnectionOptions,
  SshForward,
  SshOptions,
} from '$lib/bridge/types';
import { tNow } from '$lib/i18n';
import { parseTags, type ValidationResult } from './shared';
import { RDP_CUSTOM_SIZE_PATTERN } from './settings';
export { parseTags };

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
    // A port must be an integer in 1..65535. Drop anything else (negative, 0, >65535, fractional,
    // non-numeric) to null so the connection falls back to its default port instead of failing
    // later at the ssh/xfreerdp spawn with a cryptic process error (4.104).
    if (Number.isInteger(parsed) && parsed >= 1 && parsed <= 65535) port = parsed;
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
    serverId: (raw.serverId as string | null | undefined) ?? null,
    options: normalizeOptions(kind, raw.options as ConnectionOptions | null | undefined),
  };
}

// Drops every unset or empty field, so a field left empty keeps meaning "the global default"
// (R-1066); only the options of the connection's own kind are kept.
export function normalizeOptions(
  kind: ConnectionKind,
  raw: ConnectionOptions | null | undefined,
): ConnectionOptions | null {
  if (kind === 'ssh' && raw?.ssh) {
    const ssh = compactSsh(raw.ssh);
    return ssh ? { ssh } : null;
  }
  if (kind === 'rdp' && raw?.rdp) {
    const rdp = compactRdp(raw.rdp);
    return rdp ? { rdp } : null;
  }
  return null;
}

function text(v: string | null | undefined): string | undefined {
  const s = String(v ?? '').trim();
  return s || undefined;
}

function compactSsh(o: SshOptions): SshOptions | null {
  const forwards: SshForward[] = (o.forwards ?? [])
    .map((f) => ({ type: f.type, listen: String(f.listen ?? '').trim(), target: text(f.target) }))
    .filter((f) => f.listen !== '')
    .map((f) => (f.type === 'D' || !f.target ? { type: f.type, listen: f.listen } : f));
  const keepalive = o.keepalive === null || o.keepalive === undefined ? NaN : Number(o.keepalive);
  return compact<SshOptions>({
    jumpHost: text(o.jumpHost),
    forwards: forwards.length > 0 ? forwards : undefined,
    agentForwarding: o.agentForwarding ?? undefined,
    compression: o.compression ?? undefined,
    keepalive: Number.isFinite(keepalive) ? keepalive : undefined,
    authMethod: o.authMethod ?? undefined,
  });
}

function compactRdp(o: RdpConnectionOptions): RdpConnectionOptions | null {
  return compact<RdpConnectionOptions>({
    scalingMode: o.scalingMode ?? undefined,
    windowMode: o.windowMode ?? undefined,
    customSize: text(o.customSize),
    performanceProfile: o.performanceProfile ?? undefined,
    drives: o.drives ?? undefined,
    audio: o.audio ?? undefined,
    printers: o.printers ?? undefined,
    gateway: text(o.gateway),
    nla: o.nla ?? undefined,
  });
}

function compact<T extends object>(o: T): T | null {
  const entries = Object.entries(o).filter(([, v]) => v !== undefined);
  return entries.length > 0 ? (Object.fromEntries(entries) as T) : null;
}

// What the form checks before Rust and the server do: the fields whose message would else be
// a bare "invalid connection".
function validateOptions(c: Connection): ValidationResult {
  const ssh = c.options?.ssh;
  if (ssh?.keepalive !== undefined && ssh.keepalive !== null) {
    const k = ssh.keepalive;
    if (!Number.isInteger(k) || k < 1 || k > 3600) {
      return { ok: false, message: tNow('validation.keepalive') };
    }
  }
  if (ssh?.forwards?.some((f) => f.type !== 'D' && !f.target)) {
    return { ok: false, message: tNow('validation.forward.target') };
  }
  const size = c.options?.rdp?.customSize;
  if (size && !RDP_CUSTOM_SIZE_PATTERN.test(size)) {
    return { ok: false, message: tNow('validation.rdpSize.invalid') };
  }
  return { ok: true };
}

export function validateConnection(c: Connection): ValidationResult {
  if (!c.name) {
    return { ok: false, message: tNow('validation.name.empty') };
  }
  if (c.kind === 'web') {
    if (!c.url) return { ok: false, message: tNow('validation.url.empty') };
    // Only http/https reach open_connection (the browser); reject javascript:/file:/…
    // at the form boundary instead of relying solely on the Rust validate_web_url (3.67).
    // A scheme-less value (a bare domain) is accepted the same way the backend does it:
    // it prepends https:// before validating, so mirror that here.
    let proto: string;
    try {
      proto = new URL(c.url).protocol;
    } catch {
      try {
        proto = new URL(`https://${c.url}`).protocol;
      } catch {
        return { ok: false, message: tNow('validation.url.scheme') };
      }
    }
    if (proto !== 'http:' && proto !== 'https:') {
      return { ok: false, message: tNow('validation.url.scheme') };
    }
    return { ok: true };
  }
  if (!c.host) return { ok: false, message: tNow('validation.host.empty') };
  return validateOptions(c);
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
    serverId: null,
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

export function connectionGroupingHost(c: Connection): string {
  const host = String(c.host ?? '').trim();
  if (host) return host;
  if (c.kind === 'web') return parseUrlHost(c.url);
  return '';
}
