// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// No refresh_token: the browser keeps it only in the HttpOnly cookie, and the server sends the
// body field to a browser request as an empty string.
export interface LoginResponse {
  access_token: string;
  token_type?: string;
}

export interface RefreshResponse {
  access_token: string;
  token_type?: string;
}

export interface User {
  id: number;
  username: string;
  is_admin: boolean;
  created_at?: string | null;
  server_ids?: string[];
  // Only GET /api/auth/me sends it: the minutes without input before the panel signs out, 0 = off.
  idle_timeout_minutes?: number;
}

export interface UserCreate {
  username: string;
  password: string;
  is_admin: boolean;
  server_ids: string[];
}

export interface UserUpdate {
  is_admin: boolean;
  server_ids: string[];
  password?: string;
}

export interface EnrollmentGrant {
  token: string;
  subjectId: string;
  scope: string;
  browser: boolean;
  enrollPort: number;
  expiresAt: string | null;
}

export type ApiKeyPermission = 'read' | 'read_write';

export interface ApiKey {
  id: number;
  name: string;
  permission: ApiKeyPermission;
  created_at?: string | null;
}

export interface ApiKeyCreate {
  name: string;
  permission: ApiKeyPermission;
}

export interface ApiKeyCreateResult {
  key: string;
  id: number;
  name: string;
  permission: ApiKeyPermission;
  created_at?: string | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  // The server's stable code (ERR_…) of an error a client reacts to; branch on it, not on the text.
  readonly code: string | undefined;

  constructor(status: number, message: string, detail?: unknown, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.code = code;
  }
}

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

// One server as GET /api/servers/summary lists it.
export interface ServerSummary {
  id: string;
  name: string;
  hostname: string;
}

export type HookType = 'webhook' | 'event' | 'schedule';

export interface Hook {
  id: string;
  name: string;
  description?: string | null;
  hook_type: HookType;
  enabled: boolean;
  created_at?: string | null;
  event_triggers?: string[] | null;
  schedule_interval?: string | null;
  last_run?: string | null;
  next_run?: string | null;
}

export interface HookDetail extends Hook {
  script: string;
}

export interface HookCreateResult extends HookDetail {
  token?: string | null;
}

export interface HookCreate {
  name: string;
  description?: string | null;
  hook_type: HookType;
  script: string;
  event_triggers?: string[];
  schedule_interval?: string;
}

export interface HookUpdate {
  name?: string;
  description?: string | null;
  script?: string;
  enabled?: boolean;
  event_triggers?: string[];
  schedule_interval?: string;
}

export interface HookRunResult {
  success: boolean;
  result: unknown;
  logs: string[];
  error?: string;
}

export interface HookTokenResult {
  token: string;
}

export interface FrpConfig {
  id: string;
  name: string;
  serverAddr: string;
  bindPort: number | null;
  vhostHttpsPort?: number | null;
  authToken?: string | null;
  subdomainHost?: string | null;
  maxPortsPerClient?: number | null;
  dashboardPort?: number | null;
  dashboardUser?: string | null;
  dashboardPassword?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface FrpConfigInput {
  name: string;
  server_addr: string;
  bind_port: number;
  vhost_https_port?: number | null;
  auth_token?: string | null;
  subdomain_host?: string | null;
  max_ports_per_client?: number | null;
  dashboard_port?: number | null;
  dashboard_user?: string | null;
  dashboard_password?: string | null;
}

export interface FrpStatusProxy {
  name: string;
  type: string;
  status: string;
  curConns: number;
  clientVersion?: string;
  todayTrafficIn: number;
  todayTrafficOut: number;
  lastStartTime?: string;
  lastCloseTime?: string;
}

export interface FrpStatus {
  proxies: FrpStatusProxy[];
  total?: number;
  error?: string | null;
}

// ── Audit log ───────────────────────────────────────────────────────────
export interface AuditEntry {
  id: number;
  timestamp: string | null;
  actorType: string;
  actorId?: string | null;
  actorLabel?: string | null;
  action: string;
  objectType?: string | null;
  objectId?: string | null;
  objectLabel?: string | null;
  sourceIp?: string | null;
  status: string;
  detail?: string | null;
}

export interface AuditQuery {
  action?: string;
  actorType?: string;
  objectType?: string;
  objectId?: string;
  status?: string;
  q?: string;
  limit?: number;
  offset?: number;
}
