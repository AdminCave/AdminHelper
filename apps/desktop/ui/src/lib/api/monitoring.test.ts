// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { AuthSession } from '$lib/bridge/types';
import type { AlertRuleInput, MonitorCheckInput, MonitoringTemplateInput } from '$lib/api/types';

vi.mock('$lib/bridge', () => ({ apiProxy: vi.fn(async () => ({})) }));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { sessionStore: writable({ settings: { allowSelfSignedCerts: false } }) };
});

import * as bridge from '$lib/bridge';
import { monitoringApi } from './monitoring';

const session: AuthSession = {
  serverUrl: 'https://srv',
  token: 'tok',
  refreshToken: 'r',
  username: 'admin',
  isAdmin: true,
};
const proxy = vi.mocked(bridge.apiProxy);

const checkInput: MonitorCheckInput = {
  name: 'ping',
  server_id: 's1',
  check_type: 'ping',
  interval: '5m',
  severity: 'warning',
  consecutive_fails: 2,
  description: null,
  config: { target: '10.0.0.1' },
};
const alertInput: AlertRuleInput = {
  name: 'webhook',
  channel: 'webhook',
  match_severity: null,
  match_server_id: null,
  cooldown_minutes: 10,
  channel_config: { url: 'https://hook' },
};
const tplInput: MonitoringTemplateInput = {
  name: 'base',
  description: null,
  check_definitions: [],
  alert_definitions: [],
};

// Each row: [label, invocation, expected method, expected path, expected body]
const cases: [string, () => Promise<unknown>, string, string, string | undefined][] = [
  ['fetchServers', () => monitoringApi.fetchServers(session), 'GET', '/api/servers', undefined],
  [
    'fetchStatus',
    () => monitoringApi.fetchStatus(session),
    'GET',
    '/api/monitoring/status',
    undefined,
  ],
  [
    'fetchAlerts',
    () => monitoringApi.fetchAlerts(session),
    'GET',
    '/api/monitoring/alerts',
    undefined,
  ],
  [
    'fetchAlertLog (default limit)',
    () => monitoringApi.fetchAlertLog(session),
    'GET',
    '/api/monitoring/alerts/log?limit=50',
    undefined,
  ],
  [
    'fetchAlertLog (custom limit)',
    () => monitoringApi.fetchAlertLog(session, 10),
    'GET',
    '/api/monitoring/alerts/log?limit=10',
    undefined,
  ],
  [
    'fetchMetrics (default period)',
    () => monitoringApi.fetchMetrics(session, 'c1'),
    'GET',
    '/api/monitoring/checks/c1/metrics?period=1h',
    undefined,
  ],
  [
    'createCheck',
    () => monitoringApi.createCheck(session, checkInput),
    'POST',
    '/api/monitoring/checks',
    JSON.stringify(checkInput),
  ],
  [
    'updateCheck',
    () => monitoringApi.updateCheck(session, 'c1', checkInput),
    'PUT',
    '/api/monitoring/checks/c1',
    JSON.stringify(checkInput),
  ],
  [
    'removeCheck',
    () => monitoringApi.removeCheck(session, 'c1'),
    'DELETE',
    '/api/monitoring/checks/c1',
    undefined,
  ],
  [
    'toggleCheck',
    () => monitoringApi.toggleCheck(session, 'c1'),
    'POST',
    '/api/monitoring/checks/c1/toggle',
    undefined,
  ],
  [
    'runCheck',
    () => monitoringApi.runCheck(session, 'c1'),
    'POST',
    '/api/monitoring/checks/c1/run',
    undefined,
  ],
  [
    'createAlert',
    () => monitoringApi.createAlert(session, alertInput),
    'POST',
    '/api/monitoring/alerts',
    JSON.stringify(alertInput),
  ],
  [
    'updateAlert',
    () => monitoringApi.updateAlert(session, 'a1', alertInput),
    'PUT',
    '/api/monitoring/alerts/a1',
    JSON.stringify(alertInput),
  ],
  [
    'removeAlert',
    () => monitoringApi.removeAlert(session, 'a1'),
    'DELETE',
    '/api/monitoring/alerts/a1',
    undefined,
  ],
  [
    'toggleAlert',
    () => monitoringApi.toggleAlert(session, 'a1'),
    'POST',
    '/api/monitoring/alerts/a1/toggle',
    undefined,
  ],
  [
    'fetchTemplates',
    () => monitoringApi.fetchTemplates(session),
    'GET',
    '/api/monitoring/templates',
    undefined,
  ],
  [
    'createTemplate',
    () => monitoringApi.createTemplate(session, tplInput),
    'POST',
    '/api/monitoring/templates',
    JSON.stringify(tplInput),
  ],
  [
    'updateTemplate',
    () => monitoringApi.updateTemplate(session, 't1', tplInput),
    'PUT',
    '/api/monitoring/templates/t1',
    JSON.stringify(tplInput),
  ],
  [
    'removeTemplate',
    () => monitoringApi.removeTemplate(session, 't1'),
    'DELETE',
    '/api/monitoring/templates/t1',
    undefined,
  ],
  [
    'fetchAssignments',
    () => monitoringApi.fetchAssignments(session, 's1'),
    'GET',
    '/api/monitoring/templates/assignments/s1',
    undefined,
  ],
  [
    'unassignTemplate',
    () => monitoringApi.unassignTemplate(session, 't1', 's1'),
    'DELETE',
    '/api/monitoring/templates/t1/assign/s1',
    undefined,
  ],
  [
    'assignTemplateTag',
    () => monitoringApi.assignTemplateTag(session, 't1', 'web srv'),
    'POST',
    '/api/monitoring/templates/t1/assign-tag',
    // Tag with a space: body stays raw JSON, only the path is encoded (see DELETE).
    JSON.stringify({ tag: 'web srv' }),
  ],
  [
    'unassignTemplateTag',
    () => monitoringApi.unassignTemplateTag(session, 't1', 'web srv'),
    'DELETE',
    '/api/monitoring/templates/t1/assign-tag/web%20srv',
    undefined,
  ],
];

describe('monitoringApi', () => {
  beforeEach(() => proxy.mockClear());

  it.each(cases)('%s', async (_label, invoke, method, path, body) => {
    await invoke();
    expect(proxy).toHaveBeenCalledWith('https://srv', 'tok', method, path, body, false);
  });

  it('assignTemplate → POST with snake_case body', async () => {
    await monitoringApi.assignTemplate(session, 't1', 's1', 'web.lan', 'web');
    expect(proxy).toHaveBeenCalledWith(
      'https://srv',
      'tok',
      'POST',
      '/api/monitoring/templates/t1/assign',
      JSON.stringify({ server_id: 's1', hostname: 'web.lan', server_name: 'web' }),
      false,
    );
  });
});
