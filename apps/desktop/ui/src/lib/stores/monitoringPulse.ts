// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The desktop's dead man's switch for monitoring (concept decision 9c, no outside ping):
// while an admin session exists it asks the server's summary once a minute, on every page,
// and says how long monitoring has produced no result once that exceeds the limit.

import { readable, type Readable } from 'svelte/store';
import { monitoringApi } from '$lib/api/monitoring';
import type { MonitoringStatusSummary } from '$lib/api/types';
import { currentSession, session } from './session';

export const PULSE_INTERVAL_MS = 60_000;
const FLOOR_MS = 10 * 60_000;

/** max(10 min, 2 × the shortest interval of an enabled check). */
export function pulseLimitMs(minIntervalS: number | null): number {
  return Math.max(FLOOR_MS, 2 * (minIntervalS ?? 0) * 1000);
}

export interface PulseSeen {
  /** The last answer; null before the first one. */
  summary: MonitoringStatusSummary | null;
  /** First answer with enabled checks but no result at all yet. */
  noResultSince: number | null;
  /** First failed ask since the last answer. */
  failingSince: number | null;
}

/**
 * Minutes without a result once that exceeds the limit, else null. Nothing is said
 * before the first answer (whether there are checks is unknown) nor without an enabled
 * check; an outage counts from the last result known, at the latest from its own start.
 */
export function silentMinutes(seen: PulseSeen, now: number): number | null {
  const summary = seen.summary;
  if (!summary || summary.minIntervalS === null) return null;
  const parsed = summary.lastResultAt ? Date.parse(summary.lastResultAt) : NaN;
  const last = Number.isNaN(parsed) ? seen.noResultSince : parsed;
  const since = Math.min(last ?? now, seen.failingSince ?? now);
  const age = now - since;
  return age > pulseLimitMs(summary.minIntervalS) ? Math.floor(age / 60_000) : null;
}

const FRESH: PulseSeen = { summary: null, noResultSince: null, failingSince: null };

/**
 * Minutes monitoring has been without a result, or null. The asking runs while anyone
 * subscribes (the status footer, for the whole app) and an admin session exists; signing out
 * stops it and forgets what it saw.
 */
export const monitoringSilentMinutes: Readable<number | null> = readable<number | null>(
  null,
  (set) => {
    let seen = FRESH;
    let timer: ReturnType<typeof setInterval> | null = null;
    // Bumped on sign-in and sign-out: an answer of the session before is dropped.
    let gen = 0;
    let busy = false;

    async function ask(g: number): Promise<void> {
      const auth = currentSession();
      if (!auth || busy) return;
      busy = true;
      try {
        const summary = await monitoringApi.fetchStatusSummary(auth);
        if (g !== gen) return;
        const now = Date.now();
        const waiting = summary.minIntervalS !== null && !summary.lastResultAt;
        seen = {
          summary,
          noResultSince: waiting ? (seen.noResultSince ?? now) : null,
          failingSince: null,
        };
        set(silentMinutes(seen, now));
      } catch {
        if (g !== gen) return;
        const now = Date.now();
        seen = { ...seen, failingSince: seen.failingSince ?? now };
        set(silentMinutes(seen, now));
      } finally {
        if (g === gen) busy = false;
      }
    }

    function stop(): void {
      gen += 1;
      busy = false;
      if (timer) clearInterval(timer);
      timer = null;
      seen = FRESH;
      set(null);
    }

    // The session store also fires on settings changes: only signing in or out counts. The
    // monitoring proxy answers non-admins 403, so only an admin session asks at all.
    let active = false;
    const unsubscribe = session.subscribe((auth) => {
      const admin = auth?.isAdmin === true;
      if (admin === active) return;
      active = admin;
      stop();
      if (!active) return;
      const g = gen;
      void ask(g);
      timer = setInterval(() => void ask(g), PULSE_INTERVAL_MS);
    });

    return () => {
      unsubscribe();
      stop();
    };
  },
);
