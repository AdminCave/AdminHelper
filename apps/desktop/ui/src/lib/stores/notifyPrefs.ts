// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The person's channel settings as far as the desktop itself delivers (R-1080): a new feed
// entry pops up as a toast and an OS notice only when the matrix has the desktop for its
// severity, the desktop channel is on and its category is not muted. The bell gets every
// entry regardless. Loaded when the notifications start and set again after a save; without
// them (a failed load, a server before R-1080) every entry pops up, as before.
// Their quiet hours (R-1081) are reckoned here in the person's stored zone, the same clock the
// server holds the push channels by; do not disturb (dnd.ts) asks them.

import { currentSession } from './session';
import { notificationsApi } from '$lib/api/notifications';
import type { NotificationItem, NotificationMatrixRow, NotificationPrefs } from '$lib/api/types';

let prefs: NotificationPrefs | null = null;
// Every set and every load bumps it: a load that answers after a logout, a save or a later
// load (the next person's) must not put back what is no longer theirs.
let gen = 0;

export function setDesktopPrefs(next: NotificationPrefs | null): void {
  gen++;
  prefs = next;
}

export async function loadDesktopPrefs(): Promise<void> {
  const session = currentSession();
  if (!session) return;
  const mine = ++gen;
  let next: NotificationPrefs | null;
  try {
    next = await notificationsApi.fetchPrefs(session);
  } catch {
    next = null;
  }
  if (mine === gen) prefs = next;
}

/** Whether a new feed entry pops up on this desktop (toast and OS notice). */
export function desktopWants(n: NotificationItem): boolean {
  const matrix = prefs?.matrix;
  if (!matrix) return true;
  if (prefs?.disabledChannels?.includes('desktop')) return false;
  if (prefs?.mutedCategories?.includes(n.category)) return false;
  // The entry of a resolved incident is the all-clear; an unknown severity counts as
  // critical, as on the server.
  const row: NotificationMatrixRow = n.state === 'resolved' ? 'ok' : n.severity;
  return (matrix[row] ?? matrix.critical ?? []).includes('desktop');
}

// The minute of the day `now` has in `zone`; an unknown zone counts as UTC, as on the server.
function minuteIn(zone: string | undefined, now: number): number {
  const opts: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' };
  let parts: Intl.DateTimeFormatPart[];
  try {
    parts = new Intl.DateTimeFormat('en-GB', { ...opts, timeZone: zone || 'UTC' }).formatToParts(
      now,
    );
  } catch {
    parts = new Intl.DateTimeFormat('en-GB', { ...opts, timeZone: 'UTC' }).formatToParts(now);
  }
  const part = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  return part('hour') * 60 + part('minute');
}

function minuteOf(hhmm: string): number {
  const [h, m] = hhmm.split(':').map(Number);
  return h * 60 + m;
}

/** Whether `now` lies in the person's quiet hours: from start to before end, across midnight
 * when end is earlier; start equal to end is an empty span. */
export function inQuiet(now: number = Date.now()): boolean {
  const quiet = prefs?.quiet;
  if (!quiet?.enabled) return false;
  const start = minuteOf(quiet.start);
  const end = minuteOf(quiet.end);
  const at = minuteIn(prefs?.timezone, now);
  return start <= end ? start <= at && at < end : at >= start || at < end;
}

/** Whether a critical notice passes the quiet hours and do not disturb (on by default). */
export function criticalPasses(): boolean {
  return prefs?.quiet?.critical ?? true;
}

/** Whether a shown critical toast plays the tone. */
export function soundCritical(): boolean {
  return prefs?.soundCritical ?? false;
}
