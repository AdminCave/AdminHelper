// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Monitoring API: typed wrappers around api_proxy for the monitoring endpoints
// (proxied by the AdminHelper server to the monitoring service). Covers the full
// surface — checks, alerts, templates and their assignments — so the desktop can
// manage monitoring, not just view it. Desktop-only — the web panel has no monitoring API.

import { apiRequest } from '$lib/api/request';
import type { AuthSession } from '$lib/bridge/types';
import type {
  AlertLogEntry,
  AlertRule,
  AlertRuleInput,
  MonitorCheck,
  MonitorCheckInput,
  MonitoringBuiltinUpdate,
  MonitoringMetricsResponse,
  MonitoringTemplateFull,
  MonitoringTemplateInput,
  MonitoringTemplateTagAssignment,
  MaintenanceWindow,
  MaintenanceInput,
  Server,
  TemplateAssignment,
  TemplateSuggestion,
} from '$lib/api/types';

export const monitoringApi = {
  // ── Reads ────────────────────────────────────────────────────────────────
  fetchServers(session: AuthSession): Promise<Server[]> {
    return apiRequest<Server[]>(session, 'GET', '/api/servers');
  },
  fetchStatus(session: AuthSession): Promise<MonitorCheck[]> {
    return apiRequest<MonitorCheck[]>(session, 'GET', '/api/monitoring/status');
  },
  fetchAlerts(session: AuthSession): Promise<AlertRule[]> {
    return apiRequest<AlertRule[]>(session, 'GET', '/api/monitoring/alerts');
  },
  fetchAlertLog(session: AuthSession, limit = 50): Promise<AlertLogEntry[]> {
    return apiRequest<AlertLogEntry[]>(session, 'GET', `/api/monitoring/alerts/log?limit=${limit}`);
  },
  fetchMetrics(
    session: AuthSession,
    checkId: string,
    period = '1h',
  ): Promise<MonitoringMetricsResponse> {
    return apiRequest<MonitoringMetricsResponse>(
      session,
      'GET',
      `/api/monitoring/checks/${encodeURIComponent(checkId)}/metrics?period=${period}`,
    );
  },

  // ── Checks ─────────────────────────────────────────────────────────────────
  createCheck(session: AuthSession, data: MonitorCheckInput): Promise<MonitorCheck> {
    return apiRequest<MonitorCheck>(session, 'POST', '/api/monitoring/checks', data);
  },
  updateCheck(session: AuthSession, id: string, data: MonitorCheckInput): Promise<MonitorCheck> {
    return apiRequest<MonitorCheck>(
      session,
      'PUT',
      `/api/monitoring/checks/${encodeURIComponent(id)}`,
      data,
    );
  },
  removeCheck(session: AuthSession, id: string): Promise<void> {
    return apiRequest<void>(session, 'DELETE', `/api/monitoring/checks/${encodeURIComponent(id)}`);
  },
  toggleCheck(session: AuthSession, checkId: string): Promise<void> {
    return apiRequest<void>(
      session,
      'POST',
      `/api/monitoring/checks/${encodeURIComponent(checkId)}/toggle`,
    );
  },
  runCheck(session: AuthSession, checkId: string): Promise<void> {
    return apiRequest<void>(
      session,
      'POST',
      `/api/monitoring/checks/${encodeURIComponent(checkId)}/run`,
    );
  },
  // Drops the user's changes to a template check; the server answers with the check
  // as it is now, with the template's values.
  resetCheck(session: AuthSession, checkId: string): Promise<MonitorCheck> {
    return apiRequest<MonitorCheck>(
      session,
      'POST',
      `/api/monitoring/checks/${encodeURIComponent(checkId)}/reset`,
    );
  },

  // ── Alerts ───────────────────────────────────────────────────────────────
  createAlert(session: AuthSession, data: AlertRuleInput): Promise<AlertRule> {
    return apiRequest<AlertRule>(session, 'POST', '/api/monitoring/alerts', data);
  },
  updateAlert(session: AuthSession, id: string, data: AlertRuleInput): Promise<AlertRule> {
    return apiRequest<AlertRule>(
      session,
      'PUT',
      `/api/monitoring/alerts/${encodeURIComponent(id)}`,
      data,
    );
  },
  removeAlert(session: AuthSession, id: string): Promise<void> {
    return apiRequest<void>(session, 'DELETE', `/api/monitoring/alerts/${encodeURIComponent(id)}`);
  },
  toggleAlert(session: AuthSession, ruleId: string): Promise<void> {
    return apiRequest<void>(
      session,
      'POST',
      `/api/monitoring/alerts/${encodeURIComponent(ruleId)}/toggle`,
    );
  },

  // ── Templates + assignments ────────────────────────────────────────────────
  fetchTemplates(session: AuthSession): Promise<MonitoringTemplateFull[]> {
    return apiRequest<MonitoringTemplateFull[]>(session, 'GET', '/api/monitoring/templates');
  },
  createTemplate(
    session: AuthSession,
    data: MonitoringTemplateInput,
  ): Promise<MonitoringTemplateFull> {
    return apiRequest<MonitoringTemplateFull>(session, 'POST', '/api/monitoring/templates', data);
  },
  updateTemplate(
    session: AuthSession,
    id: string,
    data: MonitoringTemplateInput,
  ): Promise<MonitoringTemplateFull> {
    return apiRequest<MonitoringTemplateFull>(
      session,
      'PUT',
      `/api/monitoring/templates/${encodeURIComponent(id)}`,
      data,
    );
  },
  removeTemplate(session: AuthSession, id: string): Promise<void> {
    return apiRequest<void>(
      session,
      'DELETE',
      `/api/monitoring/templates/${encodeURIComponent(id)}`,
    );
  },
  fetchAssignments(session: AuthSession, serverId: string): Promise<TemplateAssignment[]> {
    return apiRequest<TemplateAssignment[]>(
      session,
      'GET',
      `/api/monitoring/templates/assignments/${encodeURIComponent(serverId)}`,
    );
  },
  assignTemplate(
    session: AuthSession,
    templateId: string,
    serverId: string,
    hostname: string,
    serverName: string,
  ): Promise<unknown> {
    return apiRequest<unknown>(
      session,
      'POST',
      `/api/monitoring/templates/${encodeURIComponent(templateId)}/assign`,
      {
        server_id: serverId,
        hostname,
        server_name: serverName,
      },
    );
  },
  unassignTemplate(session: AuthSession, templateId: string, serverId: string): Promise<void> {
    return apiRequest<void>(
      session,
      'DELETE',
      `/api/monitoring/templates/${encodeURIComponent(templateId)}/assign/${encodeURIComponent(serverId)}`,
    );
  },
  // Creates the template checks deleted on this server again (removedChecks).
  restoreTemplateChecks(
    session: AuthSession,
    templateId: string,
    serverId: string,
  ): Promise<{ restored: number }> {
    return apiRequest<{ restored: number }>(
      session,
      'POST',
      `/api/monitoring/templates/${encodeURIComponent(templateId)}/assign/${encodeURIComponent(serverId)}/restore`,
    );
  },
  fetchTemplateSuggestions(session: AuthSession, serverId: string): Promise<TemplateSuggestion[]> {
    return apiRequest<TemplateSuggestion[]>(
      session,
      'GET',
      `/api/monitoring/templates/suggestions/${encodeURIComponent(serverId)}`,
    );
  },
  // Remembered per server and template; no undo yet, the template can still be
  // assigned by hand.
  dismissTemplateSuggestion(session: AuthSession, serverId: string, slug: string): Promise<void> {
    return apiRequest<void>(
      session,
      'POST',
      `/api/monitoring/templates/suggestions/${encodeURIComponent(serverId)}/dismiss`,
      { slug },
    );
  },
  fetchBuiltinUpdate(session: AuthSession, templateId: string): Promise<MonitoringBuiltinUpdate> {
    return apiRequest<MonitoringBuiltinUpdate>(
      session,
      'GET',
      `/api/monitoring/templates/${encodeURIComponent(templateId)}/builtin-update`,
    );
  },
  // Takes the shipped version of a standard template; the fields a user changed
  // on single checks stay. 409 when there is no newer version.
  applyBuiltinUpdate(session: AuthSession, templateId: string): Promise<MonitoringTemplateFull> {
    return apiRequest<MonitoringTemplateFull>(
      session,
      'POST',
      `/api/monitoring/templates/${encodeURIComponent(templateId)}/builtin-update`,
    );
  },
  assignTemplateTag(
    session: AuthSession,
    templateId: string,
    tag: string,
  ): Promise<MonitoringTemplateTagAssignment> {
    return apiRequest<MonitoringTemplateTagAssignment>(
      session,
      'POST',
      `/api/monitoring/templates/${encodeURIComponent(templateId)}/assign-tag`,
      { tag },
    );
  },
  unassignTemplateTag(session: AuthSession, templateId: string, tag: string): Promise<void> {
    return apiRequest<void>(
      session,
      'DELETE',
      `/api/monitoring/templates/${encodeURIComponent(templateId)}/assign-tag/${encodeURIComponent(tag)}`,
    );
  },

  // ── Maintenance windows ────────────────────────────────────────────────────
  fetchMaintenance(session: AuthSession): Promise<MaintenanceWindow[]> {
    return apiRequest<MaintenanceWindow[]>(session, 'GET', '/api/monitoring/maintenance');
  },
  createMaintenance(session: AuthSession, data: MaintenanceInput): Promise<MaintenanceWindow> {
    return apiRequest<MaintenanceWindow>(session, 'POST', '/api/monitoring/maintenance', data);
  },
  updateMaintenance(
    session: AuthSession,
    id: string,
    data: MaintenanceInput,
  ): Promise<MaintenanceWindow> {
    return apiRequest<MaintenanceWindow>(
      session,
      'PUT',
      `/api/monitoring/maintenance/${encodeURIComponent(id)}`,
      data,
    );
  },
  removeMaintenance(session: AuthSession, id: string): Promise<void> {
    return apiRequest<void>(
      session,
      'DELETE',
      `/api/monitoring/maintenance/${encodeURIComponent(id)}`,
    );
  },
};
