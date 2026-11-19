// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The server-wise arrangement of the one object list (R-1558, Kevin 2026-11-18: a server list as
// in today's monitoring): a summary per server for the list on the left, and the Lage grouped by
// server for "Alle Server". Nothing here rates a value: the worst status is the worst the server
// reported for an object that is not hidden.

import type { MonObject, Status } from '../model';
import { isHidden, statusRank } from '../grammar';
import { isProblem, lageOf, type LageEntry } from './lists';

/** Order of the segments in a server's status bar, worst first. */
export const BAR_ORDER: Status[] = [
  'critical',
  'warning',
  'unknown',
  'stale',
  'info',
  'not-collected',
  'ok',
];

export interface ServerSummary {
  server: string;
  worst: Status;
  problems: number;
  /** Objects that are not hidden, per status. */
  counts: Record<Status, number>;
  hidden: number;
  total: number;
  /** Identity of the host object; empty for a server without agent. */
  identity: string[];
}

function emptyCounts(): Record<Status, number> {
  return {
    critical: 0,
    warning: 0,
    unknown: 0,
    stale: 0,
    info: 0,
    'not-collected': 0,
    ok: 0,
  };
}

function summaryOf(server: string, own: readonly MonObject[]): ServerSummary {
  const counts = emptyCounts();
  // Not collected is no state of the server; it only shows when nothing else is reported.
  let worst: Status | undefined;
  let hidden = 0;
  for (const o of own) {
    if (isHidden(o)) {
      hidden++;
      continue;
    }
    counts[o.status]++;
    if (o.status !== 'not-collected' && (!worst || statusRank(o.status) < statusRank(worst)))
      worst = o.status;
  }
  return {
    server,
    worst: worst ?? 'not-collected',
    problems: own.filter(isProblem).length,
    counts,
    hidden,
    total: own.length,
    identity: own.find((o) => o.kind === 'host')?.identity ?? [],
  };
}

/** One summary per server: worst status first, then more problems, then by name. */
export function serverSummaries(all: readonly MonObject[]): ServerSummary[] {
  const by = new Map<string, MonObject[]>();
  for (const o of all) {
    const own = by.get(o.server);
    if (own) own.push(o);
    else by.set(o.server, [o]);
  }
  return [...by]
    .map(([server, own]) => summaryOf(server, own))
    .sort(
      (a, b) =>
        statusRank(a.worst) - statusRank(b.worst) ||
        b.problems - a.problems ||
        a.server.localeCompare(b.server, 'de'),
    );
}

export interface ServerLage {
  summary: ServerSummary;
  entries: LageEntry[];
  /** Stale objects whose host reports: they show with their server, not as a problem. */
  stale: MonObject[];
}

/** The Lage grouped by server: servers with problems or stale values in the order of the
 * server list, and the quiet rest as one line. */
export function lageByServer(all: readonly MonObject[]): {
  attention: ServerLage[];
  quiet: ServerSummary[];
} {
  const lage = lageOf(all);
  const attention: ServerLage[] = [];
  const quiet: ServerSummary[] = [];
  for (const summary of serverSummaries(all)) {
    const entries = lage.problems.filter((e) => e.object.server === summary.server);
    const stale = lage.staleLeft.find((g) => g.server === summary.server)?.objects ?? [];
    if (entries.length || stale.length) attention.push({ summary, entries, stale });
    else quiet.push(summary);
  }
  return { attention, quiet };
}
