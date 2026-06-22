// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Notification store: feed loading, unread count, and the priming logic that
// keeps the first poll from firing OS notifications for the whole backlog.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { NotificationItem } from '$lib/api/types';

const h = vi.hoisted(() => ({
  fetchFeed: vi.fn(async (..._a: unknown[]) => [] as NotificationItem[]),
  markRead: vi.fn(async (..._a: unknown[]) => ({ updated: 0 })),
}));

vi.mock('$lib/api/notifications', () => ({
  notificationsApi: { fetchFeed: h.fetchFeed, markRead: h.markRead },
}));
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
    h.markRead.mockReset();
    h.markRead.mockResolvedValue({ updated: 0 });
    setNewNotificationHandler(null);
    deactivateNotifications(); // resets items + priming state
  });

  it('loadFeed populates items and derives the unread count', async () => {
    h.fetchFeed.mockResolvedValueOnce([item({ id: 1, read: false }), item({ id: 2, read: true })]);
    await loadFeed();
    expect(get(notificationItems)).toHaveLength(2);
    expect(get(unreadCount)).toBe(1);
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
    await loadFeed();
    expect(get(unreadCount)).toBe(1);
    await markAllRead();
    expect(get(unreadCount)).toBe(0);
    expect(h.markRead).toHaveBeenCalledWith(expect.anything(), null);
  });
});
