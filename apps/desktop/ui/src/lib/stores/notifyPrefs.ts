// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The person's channel settings as far as the desktop itself delivers (R-1080): a new feed
// entry pops up as a toast and an OS notice only when the matrix has the desktop for its
// severity, the desktop channel is on and its category is not muted. The bell gets every
// entry regardless. Loaded when the notifications start and set again after a save; without
// them (a failed load, a server before R-1080) every entry pops up, as before.

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
