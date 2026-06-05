// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Monitoring API: typed wrappers around apiProxy() for monitoring endpoints.
// Takes the current AuthSession from the session store.

import { get } from 'svelte/store';
import * as bridge from '$lib/bridge';
import type { AuthSession } from '$lib/bridge/types';
import { sessionStore } from '$lib/stores/session';
import type {
  AlertLogEntry,
  AlertRule,
  MonitorCheck,
  MonitoringMetricsResponse,
  Server,
} from '$lib/api/types';

async function request<T>(
  session: AuthSession,
  method: 'GET' | 'POST',
  path: string,
  body?: unknown,
): Promise<T> {
  const allowSelfSigned = get(sessionStore).settings?.allowSelfSignedCerts ?? false;
  return bridge.apiProxy<T>(
    session.serverUrl,
    session.token,
    method,
    path,
    body ? JSON.stringify(body) : undefined,
    allowSelfSigned,
  );
}

export const monitoringApi = {
  fetchServers(session: AuthSession): Promise<Server[]> {
    return request<Server[]>(session, 'GET', '/api/servers');
  },
  fetchStatus(session: AuthSession): Promise<MonitorCheck[]> {
    return request<MonitorCheck[]>(session, 'GET', '/api/monitoring/status');
  },
  fetchAlerts(session: AuthSession): Promise<AlertRule[]> {
    return request<AlertRule[]>(session, 'GET', '/api/monitoring/alerts');
  },
  fetchAlertLog(session: AuthSession, limit = 50): Promise<AlertLogEntry[]> {
    return request<AlertLogEntry[]>(session, 'GET', `/api/monitoring/alerts/log?limit=${limit}`);
  },
  fetchMetrics(
    session: AuthSession,
    checkId: string,
    period = '1h',
  ): Promise<MonitoringMetricsResponse> {
    return request<MonitoringMetricsResponse>(
      session,
      'GET',
      `/api/monitoring/checks/${checkId}/metrics?period=${period}`,
    );
  },
  toggleCheck(session: AuthSession, checkId: string): Promise<void> {
    return request<void>(session, 'POST', `/api/monitoring/checks/${checkId}/toggle`);
  },
  toggleAlert(session: AuthSession, ruleId: string): Promise<void> {
    return request<void>(session, 'POST', `/api/monitoring/alerts/${ruleId}/toggle`);
  },
  runCheck(session: AuthSession, checkId: string): Promise<void> {
    return request<void>(session, 'POST', `/api/monitoring/checks/${checkId}/run`);
  },
};
