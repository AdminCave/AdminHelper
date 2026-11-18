// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Lists the views derive from the one object list (R-1558): the Lage, the filter of the object
// table and module parts nested under their instance. The views only arrange what the server
// rated; nothing here rates a value.

import type { Ack, Kind, MonObject, Status } from '../model';
import { KIND_LABEL, dateText, isHidden, sortObjects } from '../grammar';

// Statuses that open a problem (Konzept §2). Stale values are not a problem of their own: the
// silent host is, and its stale objects fold into it.
const PROBLEM: ReadonlySet<Status> = new Set<Status>(['critical', 'warning', 'unknown']);

export function isProblem(o: MonObject): boolean {
  return !isHidden(o) && PROBLEM.has(o.status);
}

/** "Bestätigt von admin, 18.11.2026, 08:30 — Notiz": the problem stays open (Konzept §2). */
export function ackText(a: Ack): string {
  const base = `Bestätigt von ${a.by}, ${dateText(a.at)}`;
  return a.note ? `${base} — ${a.note}` : base;
}

export interface LageEntry {
  object: MonObject;
  /** Named parts of a module instance that are problems themselves. */
  parts: MonObject[];
  /** Objects of the same server with stale values, when `object` is its silent host. */
  stale: MonObject[];
}

export interface Lage {
  problems: LageEntry[];
  /** Stale objects without a host problem to fold into, by server. */
  staleLeft: { server: string; objects: MonObject[] }[];
  ok: number;
  info: number;
  notCollected: number;
  hidden: number;
  servers: number;
}

function byServer(list: readonly MonObject[]): Map<string, MonObject[]> {
  const out = new Map<string, MonObject[]>();
  for (const o of list) out.set(o.server, [...(out.get(o.server) ?? []), o]);
  return out;
}

export function lageOf(all: readonly MonObject[]): Lage {
  const problems = sortObjects(all.filter(isProblem));
  const problemKeys = new Set(problems.map((o) => o.key));
  const stale = byServer(all.filter((o) => !isHidden(o) && o.status === 'stale'));
  const entries: LageEntry[] = [];
  for (const o of problems) {
    if (o.parent && problemKeys.has(o.parent)) continue;
    const own = o.kind === 'host' ? (stale.get(o.server) ?? []) : [];
    if (own.length) stale.delete(o.server);
    entries.push({ object: o, parts: problems.filter((p) => p.parent === o.key), stale: own });
  }
  const shown = all.filter((o) => !isHidden(o));
  return {
    problems: entries,
    staleLeft: [...stale].map(([server, objects]) => ({ server, objects })),
    ok: shown.filter((o) => o.status === 'ok').length,
    info: shown.filter((o) => o.status === 'info').length,
    notCollected: shown.filter((o) => o.status === 'not-collected').length,
    hidden: all.length - shown.length,
    servers: new Set(all.map((o) => o.server)).size,
  };
}

export interface ObjectFilter {
  kind: Kind | '';
  /** A status, `problems` for every problem status, or '' for all. */
  status: Status | 'problems' | '';
  server: string;
  showHidden: boolean;
  query: string;
}

export const NO_FILTER: ObjectFilter = {
  kind: '',
  status: '',
  server: '',
  showHidden: true,
  query: '',
};

function matchesStatus(o: MonObject, status: ObjectFilter['status']): boolean {
  if (!status) return true;
  // A hidden object is not rated, so no status filter finds it.
  if (isHidden(o)) return false;
  return status === 'problems' ? isProblem(o) : o.status === status;
}

function text(o: MonObject): string {
  return [o.name, o.server, o.reason, o.key, KIND_LABEL[o.kind], ...o.identity]
    .join(' ')
    .toLocaleLowerCase('de');
}

/** The objects that pass the filter, worst first, hidden ones grey at the end. */
export function filterObjects(all: readonly MonObject[], f: ObjectFilter): MonObject[] {
  const q = f.query.trim().toLocaleLowerCase('de');
  return sortObjects(
    all.filter(
      (o) =>
        (!f.kind || o.kind === f.kind) &&
        (!f.server || o.server === f.server) &&
        (f.showHidden || !isHidden(o)) &&
        matchesStatus(o, f.status) &&
        (!q || text(o).includes(q)),
    ),
  );
}

export interface Nested {
  object: MonObject;
  depth: 0 | 1;
}

/** Parts right after their module instance; a part whose instance is not listed stays on top. */
export function nestParts(sorted: readonly MonObject[]): Nested[] {
  const listed = new Set(sorted.map((o) => o.key));
  const out: Nested[] = [];
  for (const o of sorted) {
    if (o.parent && listed.has(o.parent)) continue;
    out.push({ object: o, depth: 0 });
    for (const p of sorted) if (p.parent === o.key) out.push({ object: p, depth: 1 });
  }
  return out;
}

export function serversOf(all: readonly MonObject[]): string[] {
  return [...new Set(all.map((o) => o.server))].sort((a, b) => a.localeCompare(b, 'de'));
}
