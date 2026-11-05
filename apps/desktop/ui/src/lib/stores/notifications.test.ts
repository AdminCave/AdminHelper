// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Notification store: feed loading, unread count, the priming logic that
// keeps the first poll from firing OS notifications for the whole backlog, the
// new-entry detection by ping time, and the incident actions (R-1079).

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { IncidentDetail, NotificationItem } from '$lib/api/types';

const h = vi.hoisted(() => ({
  fetchFeed: vi.fn(async (..._a: unknown[]) => [] as NotificationItem[]),
  fetchUnreadCount: vi.fn(async (..._a: unknown[]) => ({ count: 0 })),
  markRead: vi.fn(async (..._a: unknown[]) => ({ updated: 0 })),
  hide: vi.fn(async (..._a: unknown[]) => ({ updated: 0 })),
  markUnread: vi.fn(async (..._a: unknown[]) => ({ updated: 0 })),
  ackIncidents: vi.fn(async (..._a: unknown[]) => ({ updated: 0, skipped: [] as number[] })),
  resolveIncident: vi.fn(async (..._a: unknown[]) => ({}) as IncidentDetail),
  muteIncident: vi.fn(async (..._a: unknown[]) => ({}) as NotificationItem),
  muteServer: vi.fn(async (..._a: unknown[]) => ({ serverId: '', until: '' })),
  reportError: vi.fn(),
  startStream: vi.fn(async (..._a: unknown[]) => {}),
  stopStream: vi.fn(async () => {}),
  listen: vi.fn(async (..._a: unknown[]) => () => {}),
}));

vi.mock('$lib/api/notifications', () => ({
  notificationsApi: {
    fetchFeed: h.fetchFeed,
    fetchUnreadCount: h.fetchUnreadCount,
    markRead: h.markRead,
    hide: h.hide,
    markUnread: h.markUnread,
    ackIncidents: h.ackIncidents,
    resolveIncident: h.resolveIncident,
    muteIncident: h.muteIncident,
    muteServer: h.muteServer,
  },
}));
vi.mock('./statusBar', () => ({ reportError: h.reportError }));
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
  hide,
  markUnread,
  ackIncidents,
  resolveIncident,
  muteIncident,
  muteServer,
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
    for (const fn of [h.hide, h.markUnread, h.ackIncidents, h.resolveIncident, h.muteIncident])
      fn.mockReset();
    h.muteServer.mockReset();
    h.reportError.mockReset();
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

  it('without a ping time (a server before R-1079) fires only for ids newer than last seen', async () => {
    const seen: NotificationItem[][] = [];
    setNewNotificationHandler((items) => seen.push(items));
    h.fetchFeed.mockResolvedValueOnce([item({ id: 5, read: false })]);
    await loadFeed(); // priming → lastSeen = 5
    h.fetchFeed.mockResolvedValueOnce([item({ id: 7, read: false }), item({ id: 5, read: false })]);
    await loadFeed();
    expect(seen).toHaveLength(1);
    expect(seen[0].map((n) => n.id)).toEqual([7]);
  });

  it('fires for a newer ping, also of a row seen before, and not for older, read or muted rows', async () => {
    const seen: number[][] = [];
    setNewNotificationHandler((items) => seen.push(items.map((n) => n.id)));
    h.fetchFeed.mockResolvedValueOnce([
      item({ id: 5, notifiedAt: '2026-11-05T08:00:00Z' }),
      item({ id: 4, notifiedAt: '2026-11-05T07:00:00.250000Z', read: true }),
    ]);
    await loadFeed(); // priming
    h.fetchFeed.mockResolvedValueOnce([
      item({ id: 8, notifiedAt: '2026-11-05T09:10:00Z', muted: true }),
      item({ id: 7, notifiedAt: '2026-11-05T09:05:00Z', read: true }),
      item({ id: 4, notifiedAt: '2026-11-05T09:00:00.123456Z' }), // pinged again: unread, moved up
      item({ id: 5, notifiedAt: '2026-11-05T08:00:00Z' }), // unchanged
      item({ id: 3, notifiedAt: '2026-11-05T06:00:00Z' }), // an older row slid into the 50
    ]);
    await loadFeed();
    expect(seen).toEqual([[4]]);
  });

  it('a server update mid-session fires only for new ids until a ping time was seen', async () => {
    const seen: number[][] = [];
    setNewNotificationHandler((items) => seen.push(items.map((n) => n.id)));
    h.fetchFeed.mockResolvedValueOnce([item({ id: 5 }), item({ id: 4 })]);
    await loadFeed(); // priming against the old server: no ping times
    // The updated server fills notifiedAt in for every row; the unread backlog stays quiet.
    h.fetchFeed.mockResolvedValueOnce([
      item({ id: 5, notifiedAt: '2026-11-05T08:00:00Z' }),
      item({ id: 4, notifiedAt: '2026-11-05T07:00:00Z' }),
    ]);
    await loadFeed();
    expect(seen).toEqual([]);
    h.fetchFeed.mockResolvedValueOnce([
      item({ id: 6, notifiedAt: '2026-11-05T09:00:00Z' }),
      item({ id: 5, notifiedAt: '2026-11-05T08:00:00Z' }),
    ]);
    await loadFeed();
    h.fetchFeed.mockResolvedValueOnce([
      item({ id: 4, notifiedAt: '2026-11-05T09:30:00Z' }), // pinged again, now by its time
      item({ id: 6, notifiedAt: '2026-11-05T09:00:00Z' }),
    ]);
    await loadFeed();
    expect(seen).toEqual([[6], [4]]);
  });

  it('does not fire for a row the reader marked unread: its ping time stays', async () => {
    const seen: NotificationItem[][] = [];
    setNewNotificationHandler((items) => seen.push(items));
    h.fetchFeed.mockResolvedValueOnce([
      item({ id: 5, notifiedAt: '2026-11-05T08:00:00Z', read: true }),
    ]);
    await loadFeed();
    h.fetchFeed.mockResolvedValueOnce([item({ id: 5, notifiedAt: '2026-11-05T08:00:00Z' })]);
    await loadFeed();
    expect(seen).toEqual([]);
  });

  it('forgets the ping time on deactivate: the next session primes again', async () => {
    const seen: NotificationItem[][] = [];
    setNewNotificationHandler((items) => seen.push(items));
    h.fetchFeed.mockResolvedValueOnce([item({ id: 5, notifiedAt: '2026-11-05T08:00:00Z' })]);
    await loadFeed();
    deactivateNotifications();
    h.fetchFeed.mockResolvedValueOnce([item({ id: 2, notifiedAt: '2026-11-04T08:00:00Z' })]);
    await loadFeed(); // priming of the next session, no toast
    h.fetchFeed.mockResolvedValueOnce([
      item({ id: 3, notifiedAt: '2026-11-04T09:00:00Z' }),
      item({ id: 2, notifiedAt: '2026-11-04T08:00:00Z' }),
    ]);
    await loadFeed();
    expect(seen.map((b) => b.map((n) => n.id))).toEqual([[3]]);
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

  describe('incident actions (R-1079)', () => {
    const row = (over: Partial<NotificationItem>) =>
      item({ incidentId: 1, state: 'open', notifiedAt: '2026-11-05T08:00:00Z', ...over });

    // The center list and the bell feed both hold the rows; the reload after an action answers
    // with `after` (the server's view).
    async function seed(rows: NotificationItem[], after: NotificationItem[] = rows) {
      h.fetchFeed.mockResolvedValueOnce(rows);
      await loadCenter();
      h.fetchFeed.mockResolvedValueOnce(rows);
      await loadFeed();
      h.fetchFeed.mockResolvedValue(after);
    }

    it('hide drops the rows from the center and reloads the feed', async () => {
      await seed([row({ id: 1 }), row({ id: 2 })], [row({ id: 2 })]);
      h.hide.mockResolvedValueOnce({ updated: 1 });
      expect(await hide([1])).toBe(true);
      expect(h.hide).toHaveBeenCalledWith(expect.anything(), [1]);
      expect(get(centerItems).map((n) => n.id)).toEqual([2]);
      expect(get(notificationItems).map((n) => n.id)).toEqual([2]);
    });

    it('sends at most 500 ids per call, each id once', async () => {
      await seed([row({ id: 1 }), row({ id: 2 })], []);
      h.hide.mockResolvedValue({ updated: 0 });
      const ids = [1, 1, ...Array.from({ length: 500 }, (_, i) => i + 2)];
      expect(await hide(ids)).toBe(true);
      expect(h.hide.mock.calls.map((c) => (c[1] as number[]).length)).toEqual([500, 1]);
      expect(h.hide.mock.calls.flatMap((c) => c[1] as number[])).toEqual(
        Array.from({ length: 501 }, (_, i) => i + 1),
      );
      expect(get(centerItems)).toEqual([]);
    });

    it('adds up the answers of the parts of an acknowledgement', async () => {
      await seed([row({ id: 1 })]);
      h.ackIncidents
        .mockResolvedValueOnce({ updated: 499, skipped: [3] })
        .mockResolvedValueOnce({ updated: 0, skipped: [501] });
      const ids = Array.from({ length: 501 }, (_, i) => i + 1);
      expect(await ackIncidents(ids)).toEqual({ updated: 499, skipped: [3, 501] });
    });

    it('keeps the parts the server took when a later one fails', async () => {
      await seed([row({ id: 1 }), row({ id: 600, incidentId: 600 })]);
      h.ackIncidents
        .mockResolvedValueOnce({ updated: 1, skipped: [] })
        .mockRejectedValueOnce(new Error('boom'));
      const ids = Array.from({ length: 600 }, (_, i) => i + 1);
      expect(await ackIncidents(ids)).toBeNull();
      expect(h.reportError).toHaveBeenCalledWith('boom');
      expect(get(centerItems).map((n) => n.state)).toEqual(['acked', 'open']);
    });

    it('markUnread sets the rows unread on the center page', async () => {
      await seed([row({ id: 1, read: true }), row({ id: 2, read: true })]);
      h.markUnread.mockResolvedValueOnce({ updated: 1 });
      expect(await markUnread([2])).toBe(true);
      expect(get(centerItems).map((n) => n.read)).toEqual([true, false]);
    });

    it('ackIncidents takes incident ids and turns the rows of the acknowledged ones acked', async () => {
      await seed([
        row({ id: 10, incidentId: 1 }),
        row({ id: 11, incidentId: 2 }),
        row({ id: 12, incidentId: null, state: null }),
      ]);
      h.ackIncidents.mockResolvedValueOnce({ updated: 1, skipped: [2] });
      const res = await ackIncidents([1, 2]);
      expect(h.ackIncidents).toHaveBeenCalledWith(expect.anything(), [1, 2]);
      expect(res).toEqual({ updated: 1, skipped: [2] });
      expect(get(centerItems).map((n) => [n.id, n.state, n.ackedBy ?? null])).toEqual([
        [10, 'acked', 'admin'],
        [11, 'open', null],
        [12, null, null],
      ]);
    });

    it('resolveIncident puts the row of the answer in place and hands the detail back', async () => {
      await seed([row({ id: 10 }), row({ id: 11, incidentId: 2 })]);
      const resolved = row({ id: 10, state: 'resolved', resolvedBy: 'admin', read: true });
      h.resolveIncident.mockResolvedValueOnce({ id: 1, row: resolved } as IncidentDetail);
      const detail = await resolveIncident(1);
      expect(h.resolveIncident).toHaveBeenCalledWith(expect.anything(), 1);
      expect(detail?.row).toEqual(resolved);
      expect(get(centerItems)).toEqual([resolved, row({ id: 11, incidentId: 2 })]);
    });

    it('a failed action reports the error, answers null and changes no row', async () => {
      await seed([row({ id: 10 })]);
      h.resolveIncident.mockRejectedValueOnce(new Error('Incident is already resolved'));
      expect(await resolveIncident(1)).toBeNull();
      expect(h.reportError).toHaveBeenCalledWith('Incident is already resolved');
      expect(get(centerItems)).toEqual([row({ id: 10 })]);
    });

    it('muteIncident takes the row the server answers with', async () => {
      await seed([row({ id: 10 })]);
      const muted = row({
        id: 10,
        muted: true,
        mutedUntil: '2026-11-05T09:00:00Z',
        muteSource: 'incident',
      });
      h.muteIncident.mockResolvedValueOnce(muted);
      expect(await muteIncident(1, '2026-11-05T09:00:00.000Z')).toEqual(muted);
      expect(h.muteIncident).toHaveBeenCalledWith(expect.anything(), 1, '2026-11-05T09:00:00.000Z');
      expect(get(centerItems)).toEqual([muted]);
    });

    it('muteServer reloads a loaded center from the start: only the server knows its rows', async () => {
      await seed([row({ id: 10 })], [row({ id: 10, muted: true, muteSource: 'server' })]);
      h.fetchFeed.mockClear();
      expect(await muteServer('srv-1', '2026-11-06T08:00:00.000Z')).toBe(true);
      expect(h.muteServer).toHaveBeenCalledWith(
        expect.anything(),
        'srv-1',
        '2026-11-06T08:00:00.000Z',
      );
      expect(h.fetchFeed).toHaveBeenCalledWith(expect.anything(), CENTER_PAGE, 0);
      expect(get(centerItems).map((n) => n.muteSource)).toEqual(['server']);
    });

    it('muteServer leaves an unloaded center alone', async () => {
      h.fetchFeed.mockResolvedValue([]);
      expect(await muteServer('srv-1', '2026-11-06T08:00:00.000Z')).toBe(true);
      expect(h.fetchFeed).not.toHaveBeenCalledWith(expect.anything(), CENTER_PAGE, 0);
    });
  });
});
