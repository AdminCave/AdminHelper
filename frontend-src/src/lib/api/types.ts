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

export interface PlaybookContent {
  content: string;
}

export interface PlaybookInput {
  name: string;
  filename: string;
  description: string;
  tags: string[];
  content: string;
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

export type FrpTunnelType = 'stcp' | 'https';
export type FrpProtocol = 'ssh' | 'rdp' | 'web';

export interface FrpTunnel {
  id: string;
  serverId: string;
  frpConfigId: string;
  name: string;
  tunnelType: FrpTunnelType;
  protocol: FrpProtocol;
  localIp: string;
  localPort: number;
  secretKey?: string | null;
  customDomains?: string | null;
  visitorPort?: number | null;
  connectionId?: string | null;
  enabled: boolean;
  tags?: string[];
  createdAt?: string | null;
}

export interface FrpTunnelInput {
  server_id: string;
  frp_config_id: string;
  name: string;
  tunnel_type: FrpTunnelType;
  protocol: FrpProtocol;
  local_ip: string;
  local_port: number;
  secret_key?: string | null;
  custom_domains?: string | null;
  visitor_port?: number | null;
  auto_create_connection: boolean;
  auto_connection_username?: string | null;
  tags: string[];
}

export interface FrpPkiClientCert {
  name: string;
  expiry: string;
}

export interface FrpPkiStatus {
  pkiDir: string;
  caExists: boolean;
  serverCertExists: boolean;
  caExpiry?: string | null;
  serverCertExpiry?: string | null;
  clientCerts: FrpPkiClientCert[];
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

export interface FrpProvisionToken {
  id: string;
  serverId: string;
  expiresAt: string;
  usedAt?: string | null;
  isValid: boolean;
  createdAt?: string | null;
}

export interface FrpProvisionTokenCreateResult {
  token: string;
  expiresAt: string;
  serverId: string;
  serverName: string;
}

export interface MonitoringAgentKeyResult {
  apiKey: string;
  serverId: string;
}
