// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Notifications API: typed wrappers around api_proxy for the server's
// notification hub — the caller's own bell feed, its incidents and their
// actions (R-1079), and per-user preferences.

import { apiRequest } from '$lib/api/request';
import type { AuthSession } from '$lib/bridge/types';
import type {
  IncidentAckResult,
  IncidentDetail,
  NotificationItem,
  NotificationPrefs,
  NotificationPrefsUpdate,
  NotificationServerMute,
} from '$lib/api/types';

const incident = (id: number, action = '') => `/api/notifications/incidents/${id}${action}`;
const serverMute = (serverId: string) =>
  `/api/notifications/server-mutes/${encodeURIComponent(serverId)}`;

export const notificationsApi = {
  fetchFeed(session: AuthSession, limit = 50, offset = 0): Promise<NotificationItem[]> {
    const page = offset ? `&offset=${offset}` : '';
    return apiRequest<NotificationItem[]>(
      session,
      'GET',
      `/api/notifications?limit=${limit}${page}`,
    );
  },
  fetchUnreadCount(session: AuthSession): Promise<{ count: number }> {
    return apiRequest<{ count: number }>(session, 'GET', '/api/notifications/unread-count');
  },
  // ids = null marks every unread entry of the caller as read.
  markRead(session: AuthSession, ids: number[] | null): Promise<{ updated: number }> {
    return apiRequest<{ updated: number }>(session, 'POST', '/api/notifications/read', { ids });
  },
  // Feed rows, not incidents; the next ping of their incident shows a hidden row again.
  hide(session: AuthSession, ids: number[]): Promise<{ updated: number }> {
    return apiRequest<{ updated: number }>(session, 'POST', '/api/notifications/hide', { ids });
  },
  markUnread(session: AuthSession, ids: number[]): Promise<{ updated: number }> {
    return apiRequest<{ updated: number }>(session, 'POST', '/api/notifications/unread', { ids });
  },
  fetchIncident(session: AuthSession, id: number): Promise<IncidentDetail> {
    return apiRequest<IncidentDetail>(session, 'GET', incident(id));
  },
  // Incident ids; one the caller may not act on, or that is not open, comes back in skipped.
  ackIncidents(session: AuthSession, ids: number[]): Promise<IncidentAckResult> {
    return apiRequest<IncidentAckResult>(session, 'POST', '/api/notifications/incidents/ack', {
      ids,
    });
  },
  resolveIncident(session: AuthSession, id: number): Promise<IncidentDetail> {
    return apiRequest<IncidentDetail>(session, 'POST', incident(id, '/resolve'));
  },
  reopenIncident(session: AuthSession, id: number): Promise<IncidentDetail> {
    return apiRequest<IncidentDetail>(session, 'POST', incident(id, '/reopen'));
  },
  addNote(session: AuthSession, id: number, text: string): Promise<IncidentDetail> {
    return apiRequest<IncidentDetail>(session, 'POST', incident(id, '/notes'), { text });
  },
  // until: an ISO time with zone, later than now and at most 7 days ahead (the server checks).
  muteIncident(session: AuthSession, id: number, until: string): Promise<NotificationItem> {
    return apiRequest<NotificationItem>(session, 'PUT', incident(id, '/mute'), { until });
  },
  unmuteIncident(session: AuthSession, id: number): Promise<NotificationItem> {
    return apiRequest<NotificationItem>(session, 'DELETE', incident(id, '/mute'));
  },
  fetchServerMutes(session: AuthSession): Promise<NotificationServerMute[]> {
    return apiRequest<NotificationServerMute[]>(session, 'GET', '/api/notifications/server-mutes');
  },
  muteServer(
    session: AuthSession,
    serverId: string,
    until: string,
  ): Promise<NotificationServerMute> {
    return apiRequest<NotificationServerMute>(session, 'PUT', serverMute(serverId), { until });
  },
  unmuteServer(session: AuthSession, serverId: string): Promise<void> {
    return apiRequest<void>(session, 'DELETE', serverMute(serverId));
  },
  fetchPrefs(session: AuthSession): Promise<NotificationPrefs> {
    return apiRequest<NotificationPrefs>(session, 'GET', '/api/users/me/notification-prefs');
  },
  savePrefs(session: AuthSession, prefs: NotificationPrefsUpdate): Promise<NotificationPrefs> {
    return apiRequest<NotificationPrefs>(session, 'PUT', '/api/users/me/notification-prefs', prefs);
  },
};
