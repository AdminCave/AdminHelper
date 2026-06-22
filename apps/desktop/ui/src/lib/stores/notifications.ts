// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Notification store: the bell feed + unread badge, polled app-wide while a
// server session is active (mirrors the monitoring store's activate/deactivate
// + setInterval pattern). New entries are surfaced to an optional handler so the
// OS-notification layer can stay decoupled from this store.

import { writable, derived, get } from 'svelte/store';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';
import { sessionStore } from './session';
import * as bridge from '$lib/bridge';
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
    // Accurate badge from the dedicated endpoint (the 50-row list would
    // undercount past 50); fall back to the list count if it fails.
    let unread = list.filter((n) => !n.read).length;
    try {
      const c = await notificationsApi.fetchUnreadCount(session);
      if (typeof c?.count === 'number') unread = c.count;
    } catch {
      /* keep the list-derived count */
    }
    _state.update((s) => ({ ...s, items: list, unreadCount: unread }));
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
let unlistenStream: UnlistenFn | null = null;

export async function activateNotifications(): Promise<void> {
  void loadFeed();
  if (pollTimer) clearInterval(pollTimer);
  // Polling stays as a fallback (SSE may be unavailable: no Redis, dead stream).
  pollTimer = setInterval(() => void loadFeed(), POLL_INTERVAL_MS);

  // Live SSE push: a `notification` Tauri event (emitted by the Rust stream
  // client) means "reload the feed now". We reuse loadFeed instead of merging a
  // payload, keeping a single source of truth (priming, unread-count, OS-notify).
  const session = requireSession();
  if (session) {
    try {
      await bridge.startNotificationStream(session.serverUrl, session.token);
      unlistenStream = await listen('notification', () => void loadFeed());
    } catch (err) {
      console.warn('Notification-Stream konnte nicht gestartet werden', err);
      // The fallback poll keeps the bell working — graceful degradation.
    }
  }
}

export function deactivateNotifications(): void {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  if (unlistenStream) {
    try {
      unlistenStream();
    } catch {
      /* ignore */
    }
    unlistenStream = null;
  }
  void bridge.stopNotificationStream();
  // Reset priming so a different user's backlog does not trigger OS spam.
  lastSeenId = 0;
  primed = false;
  _state.set({ items: [], unreadCount: 0, panelOpen: false });
}
