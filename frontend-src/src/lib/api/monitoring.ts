import { http } from './client';
import type { MonCheckSummary, MonitoringTemplate, TemplateAssignment } from './types';

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
