// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Native OS notifications for new bell-feed entries. Kept separate from the
// notification store so the store stays platform-agnostic and testable — this
// module is the only place that touches the Tauri notification plugin and is
// wired in as the store's "new entries" handler when the user opts in.

import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from '@tauri-apps/plugin-notification';
import { tNow } from '$lib/i18n';
import type { NotificationItem } from '$lib/api/types';

// Burst guard: above this many fresh entries at once, send one summary instead
// of a wall of toasts.
const SUMMARY_THRESHOLD = 3;

/** Ensure OS notification permission, requesting it once if needed. */
export async function ensureNotificationPermission(): Promise<boolean> {
  try {
    if (await isPermissionGranted()) return true;
    return (await requestPermission()) === 'granted';
  } catch {
    return false;
  }
}

/** Fire OS notifications for freshly-arrived feed entries (best-effort). */
export async function notifyOs(items: NotificationItem[]): Promise<void> {
  if (!items.length) return;
  if (!(await ensureNotificationPermission())) return;
  try {
    if (items.length > SUMMARY_THRESHOLD) {
      sendNotification({
        title: tNow('notifications.title'),
        body: tNow('notifications.osSummary', { count: items.length }),
      });
      return;
    }
    for (const n of items) {
      sendNotification({ title: n.title, body: n.body ?? '' });
    }
  } catch {
    /* best-effort: a failed OS toast must not affect the in-app feed */
  }
}
