export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface RefreshResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface User {
  id: string;
  username: string;
  is_admin: boolean;
  created_at?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export type ConnectionKind = 'ssh' | 'rdp' | 'vnc' | 'web' | 'custom';

export interface Connection {
  id: string;
  name: string;
  kind: ConnectionKind;
  host?: string | null;
  url?: string | null;
  port?: number | null;
  username?: string | null;
  domain?: string | null;
  keyPath?: string | null;
  serverId?: string | null;
  tags?: string[];
  notes?: string | null;
  trustCert?: boolean | null;
  lastUsed?: string | null;
  scalingMode?: string | null;
}

export interface ConnectionImportResult {
  imported: number;
}

export interface Server {
  id: string;
  name: string;
  hostname: string;
  osType?: string | null;
  tags?: string[];
  notes?: string | null;
  connections?: Connection[];
}

export interface ServerInput {
  name: string;
  hostname: string;
  os_type: string | null;
  tags: string[];
  notes: string;
}

export type MonStatus = 'ok' | 'warning' | 'critical' | 'unknown' | 'pending';

export interface MonCheckSummary {
  id: string;
  serverId?: string | null;
  state?: { status?: MonStatus } | null;
}

export interface MonitoringTemplate {
  id: string;
  name: string;
}

export interface TemplateAssignment {
  templateId: string;
  serverId: string;
}
