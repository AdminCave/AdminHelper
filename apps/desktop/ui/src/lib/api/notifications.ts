// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Notifications API: typed wrappers around api_proxy for the server's
// notification hub — the caller's own bell feed and per-user preferences.

import { apiRequest } from '$lib/api/request';
import type { AuthSession } from '$lib/bridge/types';
import type { NotificationItem, NotificationPrefs, NotificationPrefsUpdate } from '$lib/api/types';

export const notificationsApi = {
  fetchFeed(session: AuthSession, limit = 50): Promise<NotificationItem[]> {
    return apiRequest<NotificationItem[]>(session, 'GET', `/api/notifications?limit=${limit}`);
  },
  fetchUnreadCount(session: AuthSession): Promise<{ count: number }> {
    return apiRequest<{ count: number }>(session, 'GET', '/api/notifications/unread-count');
  },
  // ids = null marks every unread entry of the caller as read.
  markRead(session: AuthSession, ids: number[] | null): Promise<{ updated: number }> {
    return apiRequest<{ updated: number }>(session, 'POST', '/api/notifications/read', { ids });
  },
  fetchPrefs(session: AuthSession): Promise<NotificationPrefs> {
    return apiRequest<NotificationPrefs>(session, 'GET', '/api/users/me/notification-prefs');
  },
  savePrefs(session: AuthSession, prefs: NotificationPrefsUpdate): Promise<NotificationPrefs> {
    return apiRequest<NotificationPrefs>(session, 'PUT', '/api/users/me/notification-prefs', prefs);
  },
};
