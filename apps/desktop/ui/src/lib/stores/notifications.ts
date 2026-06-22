// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Notification store: the bell feed + unread badge, polled app-wide while a
// server session is active (mirrors the monitoring store's activate/deactivate
// + setInterval pattern). New entries are surfaced to an optional handler so the
// OS-notification layer can stay decoupled from this store.

import { writable, derived, get } from 'svelte/store';
import { sessionStore } from './session';
import { notificationsApi } from '$lib/api/notifications';
import type { NotificationItem } from '$lib/api/types';

const POLL_INTERVAL_MS = 30_000;

interface NotifState {
  items: NotificationItem[];
  unreadCount: number;
  panelOpen: boolean;
}

const _state = writable<NotifState>({ items: [], unreadCount: 0, panelOpen: false });
export const notifications = { subscribe: _state.subscribe };
export const notificationItems = derived(_state, ($s) => $s.items);
export const unreadCount = derived(_state, ($s) => $s.unreadCount);
export const panelOpen = derived(_state, ($s) => $s.panelOpen);

function requireSession() {
  return get(sessionStore).session;
}

// Highest feed id we have already seen. Guards OS notifications from firing for
// the whole backlog on the first poll: priming sets it without firing; only
// later polls treat id > lastSeenId as genuinely new.
let lastSeenId = 0;
let primed = false;
let onNew: ((items: NotificationItem[]) => void) | null = null;

/** Register a handler called with newly-arrived unread entries (for OS notifications). */
export function setNewNotificationHandler(fn: ((items: NotificationItem[]) => void) | null): void {
  onNew = fn;
}

export async function loadFeed(): Promise<void> {
  const session = requireSession();
  if (!session) return;
  try {
    const res = await notificationsApi.fetchFeed(session, 50);
    const list = Array.isArray(res) ? res : [];
    const maxId = list.reduce((m, n) => Math.max(m, n.id), lastSeenId);
    if (primed) {
      const fresh = list.filter((n) => n.id > lastSeenId && !n.read);
      if (fresh.length && onNew) onNew(fresh);
    }
    lastSeenId = maxId;
    primed = true;
    _state.update((s) => ({
      ...s,
      items: list,
      unreadCount: list.filter((n) => !n.read).length,
    }));
  } catch {
    // Session expiry / transient errors: keep the current feed, retry next poll.
  }
}

export async function markAllRead(): Promise<void> {
  const session = requireSession();
  if (!session) return;
  try {
    await notificationsApi.markRead(session, null);
    _state.update((s) => ({
      ...s,
      items: s.items.map((n) => ({ ...n, read: true })),
      unreadCount: 0,
    }));
  } catch {
    /* ignore — next poll reconciles */
  }
}

export function togglePanel(): void {
  _state.update((s) => ({ ...s, panelOpen: !s.panelOpen }));
  // Opening the panel marks the feed as seen.
  if (get(_state).panelOpen) void markAllRead();
}

export function closePanel(): void {
  _state.update((s) => ({ ...s, panelOpen: false }));
}

let pollTimer: ReturnType<typeof setInterval> | null = null;

export function activateNotifications(): void {
  void loadFeed();
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => void loadFeed(), POLL_INTERVAL_MS);
}

export function deactivateNotifications(): void {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  // Reset priming so a different user's backlog does not trigger OS spam.
  lastSeenId = 0;
  primed = false;
  _state.set({ items: [], unreadCount: 0, panelOpen: false });
}
