// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Method/path/body contract of notificationsApi against the apiProxy mock — the last API module
// without one. Non-obvious semantics worth pinning: markRead(null) = "mark everything read", and the
// limit query in fetchFeed (6.40).

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { AuthSession } from '$lib/bridge/types';
import type { NotificationPrefsUpdate } from '$lib/api/types';

vi.mock('$lib/bridge', () => ({ apiProxy: vi.fn(async () => ({})) }));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { sessionStore: writable({ settings: { allowSelfSignedCerts: false } }) };
});

import * as bridge from '$lib/bridge';
import { notificationsApi } from './notifications';

const session: AuthSession = {
  serverUrl: 'https://srv',
  token: 'tok',
  refreshToken: 'r',
  username: 'admin',
  isAdmin: true,
};
const proxy = vi.mocked(bridge.apiProxy);

const prefs: NotificationPrefsUpdate = {
  email: 'admin@example.com',
  telegram_chat_id: null,
  subscriptions: [],
};

// Each row: [label, invocation, expected method, expected path, expected body]
const cases: [string, () => Promise<unknown>, string, string, string | undefined][] = [
  [
    'fetchFeed (default limit)',
    () => notificationsApi.fetchFeed(session),
    'GET',
    '/api/notifications?limit=50',
    undefined,
  ],
  [
    'fetchFeed (custom limit)',
    () => notificationsApi.fetchFeed(session, 10),
    'GET',
    '/api/notifications?limit=10',
    undefined,
  ],
  [
    'fetchUnreadCount',
    () => notificationsApi.fetchUnreadCount(session),
    'GET',
    '/api/notifications/unread-count',
    undefined,
  ],
  [
    'markRead(null) = mark all read',
    () => notificationsApi.markRead(session, null),
    'POST',
    '/api/notifications/read',
    JSON.stringify({ ids: null }),
  ],
  [
    'markRead([1,2])',
    () => notificationsApi.markRead(session, [1, 2]),
    'POST',
    '/api/notifications/read',
    JSON.stringify({ ids: [1, 2] }),
  ],
  [
    'fetchPrefs',
    () => notificationsApi.fetchPrefs(session),
    'GET',
    '/api/users/me/notification-prefs',
    undefined,
  ],
  [
    'savePrefs',
    () => notificationsApi.savePrefs(session, prefs),
    'PUT',
    '/api/users/me/notification-prefs',
    JSON.stringify(prefs),
  ],
];

describe('notificationsApi', () => {
  beforeEach(() => proxy.mockClear());

  it.each(cases)('%s', async (_label, invoke, method, path, body) => {
    await invoke();
    expect(proxy).toHaveBeenCalledWith('https://srv', 'tok', method, path, body, false);
  });
});
