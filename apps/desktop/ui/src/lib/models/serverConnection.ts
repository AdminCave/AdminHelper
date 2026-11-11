// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Form model for server-owned connections (ssh/rdp/web, plus a serverId). The
// kinds match what the server accepts (ConnectionCreate) and the launcher opens;
// the only extra vs. the bridge connection is the serverId the infra hub manages.
// Pure logic so it stays unit-testable.

import type { Connection, ConnectionKind } from '$lib/api/types';
import { tNow } from '$lib/i18n';
import { parseTags, type ValidationResult } from './shared';
export { parseTags };

export const CONNECTION_KINDS: ConnectionKind[] = ['ssh', 'rdp', 'web'];

export interface ConnectionForm {
  id: string | null;
  /** With a server the own text of the display name (R-1210), else the name. */
  name: string;
  kind: ConnectionKind;
  host: string;
  port: number | null;
  username: string;
  domain: string;
  keyPath: string;
  url: string;
  notes: string;
  tags: string[];
  trustCert: boolean;
  serverId: string | null;
}

/** `host`: the address of the server, which a new connection of it starts with. */
export function emptyConnectionForm(serverId: string | null = null, host = ''): ConnectionForm {
  return {
    id: null,
    name: '',
    kind: 'ssh',
    host,
    port: null,
    username: '',
    domain: '',
    keyPath: '',
    url: '',
    notes: '',
    tags: [],
    trustCert: false,
    serverId,
  };
}

export function connectionToForm(c: Connection): ConnectionForm {
  return {
    id: c.id,
    // A server from before R-1210 sends no label: its name is the stored one.
    name: c.serverId ? (c.label ?? c.name) : c.name,
    kind: c.kind,
    host: c.host ?? '',
    port: c.port ?? null,
    username: c.username ?? '',
    domain: c.domain ?? '',
    keyPath: c.keyPath ?? '',
    url: c.url ?? '',
    notes: c.notes ?? '',
    tags: [...(c.tags ?? [])],
    trustCert: c.trustCert ?? false,
    serverId: c.serverId ?? null,
  };
}

/** Builds the camelCase payload the server API expects (web parity). Trims
 * fields and drops empties to null; never sends the id (it routes the request).
 * With a server the own text goes as `label`; `name` carries it as well, or the server's
 * name without one, for a server from before R-1210 that requires a name. */
export function formToPayload(form: ConnectionForm, serverName = ''): Partial<Connection> {
  const trimOrNull = (v: string): string | null => {
    const t = v.trim();
    return t.length > 0 ? t : null;
  };
  const own = form.name.trim();
  return {
    name: own || (form.serverId ? serverName : ''),
    ...(form.serverId ? { label: own } : {}),
    kind: form.kind,
    // A new web connection leaves behind the host it started with; an existing one keeps its
    // own (the auto-connection of a web tunnel names its visitor at 127.0.0.1).
    host: form.kind === 'web' && form.id === null ? null : trimOrNull(form.host),
    port: form.port ?? null,
    username: trimOrNull(form.username),
    domain: trimOrNull(form.domain),
    keyPath: trimOrNull(form.keyPath),
    url: trimOrNull(form.url),
    notes: trimOrNull(form.notes),
    tags: [...new Set(form.tags.map((t) => t.trim()).filter((t) => t.length > 0))],
    trustCert: form.trustCert,
    serverId: form.serverId,
  };
}

export function validateConnectionForm(form: ConnectionForm): ValidationResult {
  // With a server the own text is optional: the display name derives from the server's name.
  if (!form.serverId && !form.name.trim()) {
    return { ok: false, message: tNow('infra.conn.validation.nameRequired') };
  }
  if (form.kind === 'web') {
    if (!form.url.trim()) return { ok: false, message: tNow('infra.conn.validation.urlRequired') };
    return { ok: true };
  }
  if (!form.host.trim()) return { ok: false, message: tNow('infra.conn.validation.hostRequired') };
  return { ok: true };
}
