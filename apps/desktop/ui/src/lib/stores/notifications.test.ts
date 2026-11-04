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
  const session = {
    serverUrl: 'https://srv',
    username: 'admin',
    isAdmin: true,
  };
  return {
    sessionStore: writable({
      settings: { mode: 'server', allowSelfSignedCerts: false },
      session,
    }),
    currentSession: () => session,
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
  togglePanel,
  panelOpen,
  markRead,
  loadCenter,
  centerItems,
  centerHasMore,
  CENTER_PAGE,
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
    expect(h.startStream).toHaveBeenCalledWith();
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

  it('undoes a stale activation when a logout races the SSE startup (4.41)', async () => {
    const staleUn = vi.fn();
    let resolveListen!: (un: () => void) => void;
    h.listen.mockReset();
    h.listen.mockImplementationOnce(
      () =>
        new Promise<() => void>((r) => {
          resolveListen = r;
        }),
    );

    const p = activateNotifications(); // this activation's generation
    await new Promise((r) => setTimeout(r, 0)); // let it park at `await listen`
    deactivateNotifications(); // bumps activationGen -> the in-flight activation is now stale
    h.stopStream.mockClear(); // isolate the guard's stop from deactivate's own
    resolveListen(staleUn); // listen resolves late
    await p;

    expect(staleUn).toHaveBeenCalled(); // the stale listener was unregistered
    expect(h.stopStream).toHaveBeenCalled(); // the restarted SSE stream was stopped
  });

  it('togglePanel opens and closes the panel without marking anything read', async () => {
    // R-1078: the panel has an "unread" tab, so opening it must leave the entries unread (the
    // badge clears through "mark all read" or by opening an entry). panelOpen isn't reset in
    // beforeEach, so normalize to closed first.
    if (get(panelOpen)) togglePanel();
    h.markRead.mockClear();
    expect(get(panelOpen)).toBe(false);

    togglePanel(); // open
    expect(get(panelOpen)).toBe(true);
    togglePanel(); // close
    expect(get(panelOpen)).toBe(false);
    await new Promise((r) => setTimeout(r, 0));
    expect(h.markRead).not.toHaveBeenCalled();
  });

  it('markRead marks the given entries in the feed and lowers the badge by the unread ones', async () => {
    h.fetchFeed.mockResolvedValueOnce([
      item({ id: 1, read: false }),
      item({ id: 2, read: false }),
      item({ id: 3, read: true }),
    ]);
    h.fetchUnreadCount.mockResolvedValueOnce({ count: 5 });
    await loadFeed();

    await markRead([1, 3]);
    expect(h.markRead).toHaveBeenCalledWith(expect.anything(), [1, 3]);
    expect(get(notificationItems).map((n) => [n.id, n.read])).toEqual([
      [1, true],
      [2, false],
      [3, true],
    ]);
    // Only id 1 was unread: 5 - 1 (the badge counts beyond the 50-row list).
    expect(get(unreadCount)).toBe(4);
  });

  it('markRead with no ids does not call the API', async () => {
    await markRead([]);
    expect(h.markRead).not.toHaveBeenCalled();
  });

  it('markRead keeps the feed when the API fails', async () => {
    h.fetchFeed.mockResolvedValueOnce([item({ id: 1, read: false })]);
    h.fetchUnreadCount.mockResolvedValueOnce({ count: 1 });
    await loadFeed();
    h.markRead.mockRejectedValueOnce(new Error('boom'));
    await markRead([1]);
    expect(get(notificationItems)[0].read).toBe(false);
    expect(get(unreadCount)).toBe(1);
  });

  it('loadCenter reads a page of the center size and appends the next one by offset', async () => {
    const page = (from: number, n: number) =>
      Array.from({ length: n }, (_, i) => item({ id: from - i, read: true }));
    h.fetchFeed.mockResolvedValueOnce(page(1000, CENTER_PAGE));
    await loadCenter();
    expect(h.fetchFeed).toHaveBeenLastCalledWith(expect.anything(), CENTER_PAGE, 0);
    expect(get(centerItems)).toHaveLength(CENTER_PAGE);
    expect(get(centerHasMore)).toBe(true);

    // The next page overlaps by one row (an entry arrived meanwhile): no duplicate.
    h.fetchFeed.mockResolvedValueOnce(page(501, 3));
    await loadCenter(false);
    expect(h.fetchFeed).toHaveBeenLastCalledWith(expect.anything(), CENTER_PAGE, CENTER_PAGE);
    expect(get(centerItems)).toHaveLength(CENTER_PAGE + 2);
    expect(get(centerHasMore)).toBe(false);

    // A reset starts from the top again.
    h.fetchFeed.mockResolvedValueOnce(page(7, 2));
    await loadCenter();
    expect(get(centerItems).map((n) => n.id)).toEqual([7, 6]);
  });

  it('loadCenter keeps the list when the API fails', async () => {
    h.fetchFeed.mockResolvedValueOnce([item({ id: 9 })]);
    await loadCenter();
    h.fetchFeed.mockRejectedValueOnce(new Error('boom'));
    await loadCenter(false);
    expect(get(centerItems).map((n) => n.id)).toEqual([9]);
  });

  it('markRead and markAllRead reach the center list too', async () => {
    h.fetchFeed.mockResolvedValueOnce([item({ id: 1 }), item({ id: 2 }), item({ id: 3 })]);
    await loadCenter();
    await markRead([2]);
    expect(get(centerItems).map((n) => n.read)).toEqual([false, true, false]);
    await markAllRead();
    expect(get(centerItems).every((n) => n.read)).toBe(true);
  });

  it('deactivate empties the center list', async () => {
    h.fetchFeed.mockResolvedValueOnce([item({ id: 1 })]);
    await loadCenter();
    deactivateNotifications();
    expect(get(centerItems)).toEqual([]);
    expect(get(centerHasMore)).toBe(false);
  });

  it('a center page that arrives after deactivate does not refill the list', async () => {
    let resolve: (v: NotificationItem[]) => void = () => {};
    h.fetchFeed.mockImplementationOnce(() => new Promise<NotificationItem[]>((r) => (resolve = r)));
    const pending = loadCenter();
    deactivateNotifications();
    resolve([item({ id: 1 })]);
    await pending;
    expect(get(centerItems)).toEqual([]);
  });

  it('a center page started just before activate is kept', async () => {
    // After a login the page's onMount load starts before AppShell activates.
    let resolve: (v: NotificationItem[]) => void = () => {};
    h.fetchFeed.mockImplementationOnce(() => new Promise<NotificationItem[]>((r) => (resolve = r)));
    const pending = loadCenter();
    const activation = activateNotifications();
    resolve([item({ id: 1 })]);
    await pending;
    await activation;
    expect(get(centerItems).map((n) => n.id)).toEqual([1]);
  });
});
