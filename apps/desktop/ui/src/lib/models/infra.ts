// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Server model for the infrastructure hub: empty/normalize/validate helpers and
// list filtering. Pure logic — kept out of the store and components so it stays
// unit-testable. Mirrors the shape the server API expects (ServerInput) and
// returns (Server).

import type { Server, ServerInput } from '$lib/api/types';
import { tNow } from '$lib/i18n';

export interface ValidationResult {
  ok: boolean;
  message?: string;
}

export function emptyServerInput(): ServerInput {
  return { name: '', hostname: '', os_type: null, tags: [], notes: '' };
}

export function serverToInput(s: Server): ServerInput {
  return {
    name: s.name,
    hostname: s.hostname,
    os_type: s.osType ?? null,
    tags: [...(s.tags ?? [])],
    notes: s.notes ?? '',
  };
}

export function parseTags(raw: string): string[] {
  return [
    ...new Set(
      raw
        .split(',')
        .map((tag) => tag.trim())
        .filter((tag) => tag.length > 0),
    ),
  ];
}

export function normalizeServerInput(input: ServerInput): ServerInput {
  const os = (input.os_type ?? '').trim();
  return {
    name: input.name.trim(),
    hostname: input.hostname.trim(),
    os_type: os || null,
    tags: [...new Set((input.tags ?? []).map((t) => t.trim()).filter((t) => t.length > 0))],
    notes: (input.notes ?? '').trim(),
  };
}

export function validateServerInput(input: ServerInput): ValidationResult {
  if (!input.name.trim()) return { ok: false, message: tNow('infra.validation.nameRequired') };
  if (!input.hostname.trim()) {
    return { ok: false, message: tNow('infra.validation.hostnameRequired') };
  }
  return { ok: true };
}

export function filterServers(servers: Server[], search: string): Server[] {
  const sorted = [...servers].sort((a, b) => a.name.localeCompare(b.name));
  const q = search.trim().toLowerCase();
  if (!q) return sorted;
  return sorted.filter((s) =>
    `${s.name} ${s.hostname} ${s.osType ?? ''} ${(s.tags ?? []).join(' ')}`
      .toLowerCase()
      .includes(q),
  );
}
