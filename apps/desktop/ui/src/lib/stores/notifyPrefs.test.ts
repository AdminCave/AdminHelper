// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Loading the channel settings for the desktop's pop-ups (R-1080): loaded they gate, a failed
// load lets everything through as before, and the notifications load them when they start and
// drop them when they stop. R-1081: the quiet hours in the person's zone, the pass for critical
// and the tone switch.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { NotificationItem, NotificationPrefs } from '$lib/api/types';

const h = vi.hoisted(() => ({
  fetchPrefs: vi.fn(async (..._a: unknown[]): Promise<unknown> => ({})),
  fetchFeed: vi.fn(async (..._a: unknown[]) => [] as NotificationItem[]),
  fetchUnreadCount: vi.fn(async (..._a: unknown[]) => ({ count: 0 })),
}));

vi.mock('$lib/api/notifications', () => ({
  notificationsApi: {
    fetchPrefs: h.fetchPrefs,
    fetchFeed: h.fetchFeed,
    fetchUnreadCount: h.fetchUnreadCount,
  },
}));
vi.mock('$lib/bridge', () => ({
  startNotificationStream: vi.fn(async () => {}),
  stopNotificationStream: vi.fn(async () => {}),
}));
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn(async () => () => {}) }));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  const session = { serverUrl: 'https://srv', username: 'admin', isAdmin: true };
  return {
    sessionStore: writable({ settings: { mode: 'server' }, session }),
    currentSession: () => session,
  };
});

import {
  criticalPasses,
  desktopWants,
  inQuiet,
  loadDesktopPrefs,
  setDesktopPrefs,
  soundCritical,
} from './notifyPrefs';
import { activateNotifications, deactivateNotifications } from './notifications';

const entry: NotificationItem = {
  id: 1,
  createdAt: null,
  severity: 'warning',
  category: 'monitoring',
  eventType: 'monitoring.check.transition',
  title: 't',
  read: false,
};

const noDesktop: NotificationPrefs = {
  email: null,
  telegramChatId: null,
  matrix: { critical: ['desktop'], warning: [], info: [], ok: [] },
  disabledChannels: [],
  mutedCategories: [],
  subscriptions: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  setDesktopPrefs(null);
});

describe('notifyPrefs', () => {
  it('loaded settings gate the pop-up', async () => {
    h.fetchPrefs.mockResolvedValueOnce(noDesktop);
    await loadDesktopPrefs();
    expect(desktopWants(entry)).toBe(false);
    expect(desktopWants({ ...entry, severity: 'critical' })).toBe(true);
  });

  it('a failed load lets everything through, also after loaded ones', async () => {
    setDesktopPrefs(noDesktop);
    h.fetchPrefs.mockRejectedValueOnce(new Error('HTTP 404'));
    await loadDesktopPrefs();
    expect(desktopWants(entry)).toBe(true);
  });

  it('the notifications load them on start and drop them on stop', async () => {
    h.fetchPrefs.mockResolvedValueOnce(noDesktop);
    await activateNotifications();
    await vi.waitFor(() => expect(desktopWants(entry)).toBe(false));
    expect(h.fetchPrefs).toHaveBeenCalledTimes(1);

    deactivateNotifications();
    expect(desktopWants(entry)).toBe(true);
  });

  it('a load that answers after the logout puts nothing back', async () => {
    let answer: (p: NotificationPrefs) => void = () => {};
    h.fetchPrefs.mockReturnValueOnce(new Promise((r) => (answer = r)));
    const pending = loadDesktopPrefs();
    setDesktopPrefs(null);
    answer(noDesktop);
    await pending;
    expect(desktopWants(entry)).toBe(true);
  });

  it('an older load answering last does not replace the newer one', async () => {
    let first: (p: NotificationPrefs) => void = () => {};
    h.fetchPrefs.mockReturnValueOnce(new Promise((r) => (first = r)));
    h.fetchPrefs.mockResolvedValueOnce({
      ...noDesktop,
      matrix: { ...noDesktop.matrix, warning: ['desktop'] },
    });
    const older = loadDesktopPrefs();
    await loadDesktopPrefs();
    first(noDesktop);
    await older;
    expect(desktopWants(entry)).toBe(true);
  });
});

describe('notifyPrefs: quiet hours (R-1081)', () => {
  const quietPrefs = (over: Partial<NotificationPrefs> = {}): NotificationPrefs => ({
    ...noDesktop,
    timezone: 'UTC',
    quiet: { enabled: true, start: '22:00', end: '07:00', critical: true },
    soundCritical: false,
    ...over,
  });
  const utc = (hhmm: string) => Date.parse(`2026-11-07T${hhmm}:00Z`);

  it('across midnight: from the start up to before the end', () => {
    setDesktopPrefs(quietPrefs());
    expect([
      inQuiet(utc('21:59')),
      inQuiet(utc('22:00')),
      inQuiet(utc('23:59')),
      inQuiet(utc('00:00')),
      inQuiet(utc('06:59')),
      inQuiet(utc('07:00')),
      inQuiet(utc('12:00')),
    ]).toEqual([false, true, true, true, true, false, false]);
  });

  it('within a day, and start equal to end is no quiet at all', () => {
    setDesktopPrefs(
      quietPrefs({ quiet: { enabled: true, start: '12:00', end: '13:30', critical: true } }),
    );
    expect([
      inQuiet(utc('11:59')),
      inQuiet(utc('12:00')),
      inQuiet(utc('13:29')),
      inQuiet(utc('13:30')),
    ]).toEqual([false, true, true, false]);
    setDesktopPrefs(
      quietPrefs({ quiet: { enabled: true, start: '08:00', end: '08:00', critical: true } }),
    );
    expect([inQuiet(utc('07:59')), inQuiet(utc('08:00')), inQuiet(utc('20:00'))]).toEqual([
      false,
      false,
      false,
    ]);
  });

  it('in the stored zone, not the clock of this machine; an unknown zone counts as UTC', () => {
    // 21:30 UTC is 06:30 the next morning in Tokyo (UTC+9): inside 22:00–07:00 there.
    setDesktopPrefs(quietPrefs({ timezone: 'Asia/Tokyo' }));
    expect(inQuiet(utc('21:30'))).toBe(true);
    expect(inQuiet(utc('22:30'))).toBe(false);
    setDesktopPrefs(quietPrefs({ timezone: 'Mars/Olympus' }));
    expect(inQuiet(utc('21:30'))).toBe(false);
    expect(inQuiet(utc('22:30'))).toBe(true);
  });

  it('switched off, without settings, or from a server before them: never quiet', () => {
    setDesktopPrefs(
      quietPrefs({ quiet: { enabled: false, start: '00:00', end: '23:59', critical: true } }),
    );
    expect(inQuiet(utc('12:00'))).toBe(false);
    setDesktopPrefs(noDesktop);
    expect(inQuiet(utc('23:00'))).toBe(false);
    setDesktopPrefs(null);
    expect(inQuiet(utc('23:00'))).toBe(false);
  });

  it('critical passes and the tone is off unless the settings say otherwise', () => {
    expect([criticalPasses(), soundCritical()]).toEqual([true, false]);
    setDesktopPrefs(
      quietPrefs({
        quiet: { enabled: true, start: '22:00', end: '07:00', critical: false },
        soundCritical: true,
      }),
    );
    expect([criticalPasses(), soundCritical()]).toEqual([false, true]);
  });
});
