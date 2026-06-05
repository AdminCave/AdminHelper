// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { http } from './client';
import type {
  MonCheckSummary,
  MonitoringTemplate,
  TemplateAssignment,
  MonitorCheck,
  MonitorCheckInput,
  AlertRule,
  AlertRuleInput,
  AlertLogEntry,
  MonitoringMetricsResponse,
  MonitoringTemplateFull,
  MonitoringTemplateInput,
} from './types';

// ── Legacy / server-modal calls ──────────────────────────────────────────
export function listStatus(): Promise<MonCheckSummary[]> {
  return http.get<MonCheckSummary[]>('/api/monitoring/status');
}

export function listTemplates(): Promise<MonitoringTemplate[]> {
  return http.get<MonitoringTemplate[]>('/api/monitoring/templates');
}

export function listAssignmentsForServer(serverId: string): Promise<TemplateAssignment[]> {
  return http.get<TemplateAssignment[]>(`/api/monitoring/templates/assignments/${serverId}`);
}

export function assignTemplate(
  templateId: string,
  serverId: string,
  hostname: string,
  serverName: string,
): Promise<unknown> {
  return http.post(`/api/monitoring/templates/${templateId}/assign`, {
    server_id: serverId,
    hostname,
    server_name: serverName,
  });
}

export function unassignTemplate(templateId: string, serverId: string): Promise<void> {
  return http.del<void>(`/api/monitoring/templates/${templateId}/assign/${serverId}`);
}

// ── Checks (full monitoring page) ────────────────────────────────────────
export function listChecks(): Promise<MonitorCheck[]> {
  return http.get<MonitorCheck[]>('/api/monitoring/status');
}

export function createCheck(data: MonitorCheckInput): Promise<MonitorCheck> {
  return http.post<MonitorCheck>('/api/monitoring/checks', data);
}

export function updateCheck(id: string, data: MonitorCheckInput): Promise<MonitorCheck> {
  return http.put<MonitorCheck>(`/api/monitoring/checks/${id}`, data);
}

export function removeCheck(id: string): Promise<void> {
  return http.del<void>(`/api/monitoring/checks/${id}`);
}

export function runCheck(id: string): Promise<MonitorCheck> {
  return http.post<MonitorCheck>(`/api/monitoring/checks/${id}/run`);
}

export function toggleCheck(id: string): Promise<MonitorCheck> {
  return http.post<MonitorCheck>(`/api/monitoring/checks/${id}/toggle`);
}

export function checkMetrics(
  id: string,
  period: '1h' | '6h' | '24h' | '7d',
): Promise<MonitoringMetricsResponse> {
  return http.get<MonitoringMetricsResponse>(
    `/api/monitoring/checks/${id}/metrics?period=${period}`,
  );
}

// ── Alerts ───────────────────────────────────────────────────────────────
export function listAlerts(): Promise<AlertRule[]> {
  return http.get<AlertRule[]>('/api/monitoring/alerts');
}

export function createAlert(data: AlertRuleInput): Promise<AlertRule> {
  return http.post<AlertRule>('/api/monitoring/alerts', data);
}

export function updateAlert(id: string, data: AlertRuleInput): Promise<AlertRule> {
  return http.put<AlertRule>(`/api/monitoring/alerts/${id}`, data);
}

export function removeAlert(id: string): Promise<void> {
  return http.del<void>(`/api/monitoring/alerts/${id}`);
}

export function toggleAlert(id: string): Promise<AlertRule> {
  return http.post<AlertRule>(`/api/monitoring/alerts/${id}/toggle`);
}

export function alertLog(limit = 50): Promise<AlertLogEntry[]> {
  return http.get<AlertLogEntry[]>(`/api/monitoring/alerts/log?limit=${limit}`);
}

// ── Templates (full definitions) ─────────────────────────────────────────
export function listTemplatesFull(): Promise<MonitoringTemplateFull[]> {
  return http.get<MonitoringTemplateFull[]>('/api/monitoring/templates');
}

export function createTemplate(data: MonitoringTemplateInput): Promise<MonitoringTemplateFull> {
  return http.post<MonitoringTemplateFull>('/api/monitoring/templates', data);
}

export function updateTemplate(
  id: string,
  data: MonitoringTemplateInput,
): Promise<MonitoringTemplateFull> {
  return http.put<MonitoringTemplateFull>(`/api/monitoring/templates/${id}`, data);
}

export function removeTemplate(id: string): Promise<void> {
  return http.del<void>(`/api/monitoring/templates/${id}`);
}
