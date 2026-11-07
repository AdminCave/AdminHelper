// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Method/path/body contract of notificationsApi against the apiProxy mock — the last API module
// without one. Non-obvious semantics worth pinning: markRead(null) = "mark everything read", the
// limit query in fetchFeed (6.40), and the escaped server id of a server mute (R-1079).

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { AuthSession } from '$lib/bridge/types';
import type { NotificationPrefsUpdate } from '$lib/api/types';

vi.mock('$lib/bridge', () => ({ apiProxy: vi.fn(async () => ({})) }));

import * as bridge from '$lib/bridge';
import { notificationsApi } from './notifications';

const session: AuthSession = {
  serverUrl: 'https://srv',
  username: 'admin',
  isAdmin: true,
};
const proxy = vi.mocked(bridge.apiProxy);

const prefs: NotificationPrefsUpdate = {
  email: 'admin@example.com',
  telegram_chat_id: null,
  ntfy_url: 'https://ntfy.example/alerts',
  matrix: { critical: ['desktop', 'ntfy'], warning: ['desktop'], info: ['desktop'], ok: [] },
  disabled_channels: ['email'],
  muted_categories: ['agent'],
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
    'fetchFeed (a later page)',
    () => notificationsApi.fetchFeed(session, 500, 500),
    'GET',
    '/api/notifications?limit=500&offset=500',
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
    'hide',
    () => notificationsApi.hide(session, [3]),
    'POST',
    '/api/notifications/hide',
    JSON.stringify({ ids: [3] }),
  ],
  [
    'markUnread',
    () => notificationsApi.markUnread(session, [3, 4]),
    'POST',
    '/api/notifications/unread',
    JSON.stringify({ ids: [3, 4] }),
  ],
  [
    'fetchIncident',
    () => notificationsApi.fetchIncident(session, 7),
    'GET',
    '/api/notifications/incidents/7',
    undefined,
  ],
  [
    'ackIncidents (incident ids)',
    () => notificationsApi.ackIncidents(session, [7, 8]),
    'POST',
    '/api/notifications/incidents/ack',
    JSON.stringify({ ids: [7, 8] }),
  ],
  [
    'resolveIncident',
    () => notificationsApi.resolveIncident(session, 7),
    'POST',
    '/api/notifications/incidents/7/resolve',
    undefined,
  ],
  [
    'reopenIncident',
    () => notificationsApi.reopenIncident(session, 7),
    'POST',
    '/api/notifications/incidents/7/reopen',
    undefined,
  ],
  [
    'addNote',
    () => notificationsApi.addNote(session, 7, 'rotated the logs'),
    'POST',
    '/api/notifications/incidents/7/notes',
    JSON.stringify({ text: 'rotated the logs' }),
  ],
  [
    'muteIncident',
    () => notificationsApi.muteIncident(session, 7, '2026-11-05T07:00:00.000Z'),
    'PUT',
    '/api/notifications/incidents/7/mute',
    JSON.stringify({ until: '2026-11-05T07:00:00.000Z' }),
  ],
  [
    'unmuteIncident',
    () => notificationsApi.unmuteIncident(session, 7),
    'DELETE',
    '/api/notifications/incidents/7/mute',
    undefined,
  ],
  [
    'fetchServerMutes',
    () => notificationsApi.fetchServerMutes(session),
    'GET',
    '/api/notifications/server-mutes',
    undefined,
  ],
  [
    'muteServer (the id escaped)',
    () => notificationsApi.muteServer(session, 'a/b c', '2026-11-05T07:00:00.000Z'),
    'PUT',
    '/api/notifications/server-mutes/a%2Fb%20c',
    JSON.stringify({ until: '2026-11-05T07:00:00.000Z' }),
  ],
  [
    'unmuteServer',
    () => notificationsApi.unmuteServer(session, 'srv-1'),
    'DELETE',
    '/api/notifications/server-mutes/srv-1',
    undefined,
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
  [
    'testChannel',
    () => notificationsApi.testChannel(session, 'ntfy'),
    'POST',
    '/api/users/me/notification-prefs/test',
    JSON.stringify({ channel: 'ntfy' }),
  ],
];

describe('notificationsApi', () => {
  beforeEach(() => proxy.mockClear());

  it.each(cases)('%s', async (_label, invoke, method, path, body) => {
    await invoke();
    expect(proxy).toHaveBeenCalledWith(method, path, body);
  });
});
