// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Command palette (R-1062): the entries and the matching, without any store or DOM, so the
// shell feeds it what the current mode shows and the tests drive it directly.

import type { Connection } from '$lib/bridge/types';

export type PaletteKind = 'connection' | 'page' | 'action';

export interface PaletteEntry {
  id: string;
  kind: PaletteKind;
  label: string;
  /** Searched along with the label and shown beside it: host, path or shortcut. */
  hint?: string;
  run: () => void;
}

export interface PalettePage {
  id: string;
  label: string;
  href: string;
}

export interface PaletteAction {
  id: string;
  label: string;
  run: () => void;
}

export interface PaletteInput {
  connections: Connection[];
  pages: PalettePage[];
  actions: PaletteAction[];
  connect: (c: Connection) => void;
  navigate: (href: string) => void;
}

export const MAX_RESULTS = 9;

export function buildEntries(input: PaletteInput): PaletteEntry[] {
  const connections = input.connections.map<PaletteEntry>((c) => ({
    id: `connection:${c.id}`,
    kind: 'connection',
    label: c.name || c.host || c.url || '-',
    hint: c.kind === 'web' ? (c.url ?? undefined) : (c.host ?? undefined),
    run: () => input.connect(c),
  }));
  const pages = input.pages.map<PaletteEntry>((p) => ({
    id: `page:${p.id}`,
    kind: 'page',
    label: p.label,
    run: () => input.navigate(p.href),
  }));
  const actions = input.actions.map<PaletteEntry>((a) => ({
    id: `action:${a.id}`,
    kind: 'action',
    label: a.label,
    run: a.run,
  }));
  return [...connections, ...pages, ...actions];
}

// Case-insensitive; a label that starts with the query ranks before one that only contains
// it, and that before a match in the hint. Within a rank the input order stays.
export function filterEntries(entries: PaletteEntry[], query: string): PaletteEntry[] {
  const q = query.trim().toLocaleLowerCase();
  if (!q) return entries.slice(0, MAX_RESULTS);
  const rank = (e: PaletteEntry): number => {
    const label = e.label.toLocaleLowerCase();
    if (label.startsWith(q)) return 0;
    if (label.includes(q)) return 1;
    if (e.hint?.toLocaleLowerCase().includes(q)) return 2;
    return -1;
  };
  return entries
    .map((e, i) => ({ e, i, r: rank(e) }))
    .filter((x) => x.r >= 0)
    .sort((a, b) => a.r - b.r || a.i - b.i)
    .slice(0, MAX_RESULTS)
    .map((x) => x.e);
}
