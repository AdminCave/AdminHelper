// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

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
  id: number;
  username: string;
  is_admin: boolean;
  created_at?: string;
  server_ids?: string[];
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

export type ApiKeyPermission = 'read' | 'read_write';

export interface ApiKey {
  id: number;
  name: string;
  permission: ApiKeyPermission;
  created_at?: string;
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

export type ConnectionKind = 'ssh' | 'rdp' | 'web';

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

export interface Server {
  id: string;
  name: string;
  hostname: string;
  osType?: string | null;
  tags?: string[];
  notes?: string | null;
  connections?: Connection[];
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
  success?: boolean;
  output?: string;
  error?: string;
  exit_code?: number;
  duration_ms?: number;
  [key: string]: unknown;
}

export interface HookTokenResult {
  token: string;
}

export interface Playbook {
  id: string;
  name: string;
  filename: string;
  description?: string | null;
  tags?: string[];
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface FrpConfig {
  id: string;
  name: string;
  serverAddr: string;
  bindPort: number;
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
  error?: string;
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
