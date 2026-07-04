// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Form model for server-owned connections (ssh/rdp/web, plus a serverId). The
// kinds match what the server accepts (ConnectionCreate) and the launcher opens;
// the only extra vs. the bridge connection is the serverId the infra hub manages.
// Pure logic so it stays unit-testable.

import type { Connection, ConnectionKind } from '$lib/api/types';
import { tNow } from '$lib/i18n';

export const CONNECTION_KINDS: ConnectionKind[] = ['ssh', 'rdp', 'web'];

export interface ConnectionForm {
  id: string | null;
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

export interface ValidationResult {
  ok: boolean;
  message?: string;
}

export function emptyConnectionForm(serverId: string | null = null): ConnectionForm {
  return {
    id: null,
    name: '',
    kind: 'ssh',
    host: '',
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
    name: c.name,
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

export function parseTags(raw: string): string[] {
  return [
    ...new Set(
      raw
        .split(',')
        .map((t) => t.trim())
        .filter((t) => t.length > 0),
    ),
  ];
}

/** Builds the camelCase payload the server API expects (web parity). Trims
 * fields and drops empties to null; never sends the id (it routes the request). */
export function formToPayload(form: ConnectionForm): Partial<Connection> {
  const trimOrNull = (v: string): string | null => {
    const t = v.trim();
    return t.length > 0 ? t : null;
  };
  return {
    name: form.name.trim(),
    kind: form.kind,
    host: trimOrNull(form.host),
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
  if (!form.name.trim()) return { ok: false, message: tNow('infra.conn.validation.nameRequired') };
  if (form.kind === 'web') {
    if (!form.url.trim()) return { ok: false, message: tNow('infra.conn.validation.urlRequired') };
    return { ok: true };
  }
  if (!form.host.trim()) return { ok: false, message: tNow('infra.conn.validation.hostRequired') };
  return { ok: true };
}
