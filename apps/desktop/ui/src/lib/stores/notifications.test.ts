// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Notification store: feed loading, unread count, and the priming logic that
// keeps the first poll from firing OS notifications for the whole backlog.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { NotificationItem } from '$lib/api/types';

const h = vi.hoisted(() => ({
  fetchFeed: vi.fn(async (..._a: unknown[]) => [] as NotificationItem[]),
  fetchUnreadCount: vi.fn(async (..._a: unknown[]) => ({ count: 0 })),
  markRead: vi.fn(async (..._a: unknown[]) => ({ updated: 0 })),
  startStream: vi.fn(async (..._a: unknown[]) => {}),
  stopStream: vi.fn(async () => {}),
  listen: vi.fn(async (..._a: unknown[]) => () => {}),
}));

vi.mock('$lib/api/notifications', () => ({
  notificationsApi: {
    fetchFeed: h.fetchFeed,
    fetchUnreadCount: h.fetchUnreadCount,
    markRead: h.markRead,
  },
}));
vi.mock('$lib/bridge', () => ({
  startNotificationStream: h.startStream,
  stopNotificationStream: h.stopStream,
}));
vi.mock('@tauri-apps/api/event', () => ({ listen: h.listen }));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return {
    sessionStore: writable({
      settings: { mode: 'server', allowSelfSignedCerts: false },
      session: {
        serverUrl: 'https://srv',
        token: 'tok',
        refreshToken: 'r',
        username: 'admin',
        isAdmin: true,
      },
    }),
  };
});

import { get } from 'svelte/store';
import {
  loadFeed,
  markAllRead,
  unreadCount,
  notificationItems,
  activateNotifications,
  deactivateNotifications,
  setNewNotificationHandler,
} from './notifications';

const item = (over: Partial<NotificationItem>): NotificationItem => ({
  id: 1,
  createdAt: '2026-06-22T10:00:00Z',
  severity: 'warning',
  category: 'monitoring',
  eventType: 'monitoring.check.transition',
  title: 't',
  body: null,
  sourceType: 'server',
  sourceId: 'srv-1',
  read: false,
  readAt: null,
  ...over,
});

describe('notifications store', () => {
  beforeEach(() => {
    h.fetchFeed.mockReset();
    h.fetchUnreadCount.mockReset();
    h.fetchUnreadCount.mockResolvedValue({ count: 0 });
    h.markRead.mockReset();
    h.markRead.mockResolvedValue({ updated: 0 });
    setNewNotificationHandler(null);
    deactivateNotifications(); // resets items + priming state
    h.startStream.mockClear();
    h.stopStream.mockClear();
    h.listen.mockReset();
    h.listen.mockResolvedValue(() => {});
  });

  it('loadFeed populates items and takes the unread count from the endpoint', async () => {
    h.fetchFeed.mockResolvedValueOnce([item({ id: 1, read: false }), item({ id: 2, read: true })]);
    h.fetchUnreadCount.mockResolvedValueOnce({ count: 1 });
    await loadFeed();
    expect(get(notificationItems)).toHaveLength(2);
    expect(get(unreadCount)).toBe(1);
  });

  it('takes the badge from the dedicated endpoint, not the 50-row list', async () => {
    // list shows 1 unread, but the server reports 60 (beyond the 50-row window)
    h.fetchFeed.mockResolvedValueOnce([item({ id: 1, read: false })]);
    h.fetchUnreadCount.mockResolvedValueOnce({ count: 60 });
    await loadFeed();
    expect(get(unreadCount)).toBe(60);
  });

  it('falls back to the list count if the unread-count endpoint fails', async () => {
    h.fetchFeed.mockResolvedValueOnce([item({ id: 1, read: false }), item({ id: 2, read: false })]);
    h.fetchUnreadCount.mockRejectedValueOnce(new Error('boom'));
    await loadFeed();
    expect(get(unreadCount)).toBe(2);
  });

  it('does not fire the new-entry handler on the priming poll', async () => {
    const seen: NotificationItem[][] = [];
    setNewNotificationHandler((items) => seen.push(items));
    h.fetchFeed.mockResolvedValueOnce([item({ id: 5, read: false })]);
    await loadFeed();
    expect(seen).toHaveLength(0);
  });

  it('fires the new-entry handler only for entries newer than last seen', async () => {
    const seen: NotificationItem[][] = [];
    setNewNotificationHandler((items) => seen.push(items));
    h.fetchFeed.mockResolvedValueOnce([item({ id: 5, read: false })]);
    await loadFeed(); // priming → lastSeen = 5
    h.fetchFeed.mockResolvedValueOnce([item({ id: 7, read: false }), item({ id: 5, read: false })]);
    await loadFeed();
    expect(seen).toHaveLength(1);
    expect(seen[0].map((n) => n.id)).toEqual([7]);
  });

  it('markAllRead clears the unread count and calls the API with null', async () => {
    h.fetchFeed.mockResolvedValueOnce([item({ id: 1, read: false })]);
    h.fetchUnreadCount.mockResolvedValueOnce({ count: 1 });
    await loadFeed();
    expect(get(unreadCount)).toBe(1);
    await markAllRead();
    expect(get(unreadCount)).toBe(0);
    expect(h.markRead).toHaveBeenCalledWith(expect.anything(), null);
  });

  it('activate opens the SSE stream and reloads the feed on a notification event', async () => {
    let pushed: (() => void) | undefined;
    h.listen.mockImplementation(async (_evt: unknown, cb: unknown) => {
      pushed = cb as () => void;
      return () => {};
    });
    h.fetchFeed.mockResolvedValue([]);

    await activateNotifications();
    expect(h.startStream).toHaveBeenCalledWith('https://srv', 'tok');
    expect(h.listen).toHaveBeenCalledWith('notification', expect.any(Function));

    // A pushed event must reload the feed (single source of truth).
    h.fetchFeed.mockClear();
    pushed?.();
    expect(h.fetchFeed).toHaveBeenCalled();
  });

  it('deactivate stops the SSE stream', async () => {
    await activateNotifications();
    h.stopStream.mockClear();
    deactivateNotifications();
    expect(h.stopStream).toHaveBeenCalled();
  });
});
