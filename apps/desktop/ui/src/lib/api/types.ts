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

// ── Monitoring (full payloads from the monitoring service) ──────────────
export type MonitorCheckType =
  | 'ping'
  | 'tcp'
  | 'http'
  | 'agent_ping'
  | 'agent_resources'
  | 'service_process'
  | 'proxmox_backup'
  | 'zfs_health'
  | 'docker_health'
  | 'smart_health';

export type MonitorSeverity = 'critical' | 'warning' | 'info';
export type MonitorInterval = '1m' | '5m' | '15m' | '30m' | '1h' | '6h' | '12h' | '24h';
export type AlertChannel = 'webhook' | 'email';

export interface MonitorCheckConfig {
  // ping / tcp / http
  target?: string;
  port?: number;
  timeout?: number;
  url?: string;
  method?: string;
  expected_status?: number;
  verify_ssl?: boolean;
  search_string?: string;

  // agent_ping
  stale_minutes?: number;
  server_id?: string;

  // agent_resources
  cpu_warn?: number;
  cpu_crit?: number;
  memory_warn?: number;
  memory_crit?: number;
  disk_warn?: number;
  disk_crit?: number;
  temp_warn?: number;
  temp_crit?: number;
  temp_overrides?: Record<string, { warn?: number; crit?: number }>;

  // service_process
  mode?: 'auto' | 'list';
  services?: string[];
  ignore?: string[];

  // proxmox_backup
  max_backup_age_hours?: number;
  exclude_vmids?: number[];
  exclude_stopped?: boolean;

  // zfs_health
  capacity_warn?: number;
  capacity_crit?: number;

  // docker_health
  ignore_containers?: string[];
  check_restarts?: boolean;

  // smart_health
  reallocated_warn?: number;
  reallocated_crit?: number;
  pending_warn?: number;
  pending_crit?: number;
  nvme_spare_warn?: number;
  nvme_spare_crit?: number;
  nvme_used_warn?: number;
  nvme_used_crit?: number;
  temp_hdd_warn?: number;
  temp_hdd_crit?: number;
  temp_ssd_warn?: number;
  temp_ssd_crit?: number;
  temp_nvme_warn?: number;
  temp_nvme_crit?: number;
  ignore_devices?: string[];

  [key: string]: unknown;
}

export interface MonitorResourceDisk {
  mount: string;
  percent: number;
  used_gb?: number;
  total_gb?: number;
}

export interface MonitorResourceTemp {
  sensor: string;
  temp_c: number;
  high: number;
  critical: number;
}

export interface MonitorResourceDetails {
  cpu?: number | null;
  memory?: number | null;
  memory_used_mb?: number;
  memory_total_mb?: number;
  disks?: MonitorResourceDisk[];
  temperatures?: MonitorResourceTemp[];
}

export interface MonitorServiceDetails {
  mode?: 'auto' | 'list';
  failed?: string[];
  enabled_inactive?: string[];
  watched?: { name: string; running: boolean }[];
}

export interface MonitorContainerDetails {
  containers?: {
    name: string;
    image?: string;
    state: string;
    category: 'ok' | 'warning' | 'critical';
  }[];
}

export interface MonitorBackupDetails {
  vms?: {
    vmid: number;
    name: string;
    type?: string;
    backupStatus: 'ok' | 'outdated' | 'missing';
    ageHours?: number;
  }[];
}

export interface MonitorZfsDetails {
  pools?: {
    name: string;
    health: string;
    capacityPercent: number;
  }[];
}

export interface MonitorSmartDetails {
  disks?: {
    device: string;
    kind?: string;
    protocol?: string;
    model?: string;
    category?: 'ok' | 'warning' | 'critical';
    temp_c?: number;
    temp_warn?: number;
    temp_crit?: number;
    power_on_hours?: number;
    available_spare_pct?: number;
    percentage_used?: number;
    reallocated_sectors?: number;
    pending_sectors?: number;
    critical_warning_bits?: string[];
  }[];
}

export type MonitorCheckDetails =
  | MonitorResourceDetails
  | MonitorServiceDetails
  | MonitorContainerDetails
  | MonitorBackupDetails
  | MonitorZfsDetails
  | MonitorSmartDetails
  | Record<string, unknown>;

export interface MonitorCheckState {
  status?: MonStatus;
  message?: string;
  lastCheck?: string;
  details?: MonitorCheckDetails;
}

export interface MonitorCheck {
  id: string;
  name: string;
  serverId?: string | null;
  checkType: MonitorCheckType;
  interval: MonitorInterval;
  severity: MonitorSeverity;
  consecutiveFails?: number;
  description?: string | null;
  enabled: boolean;
  config?: MonitorCheckConfig;
  state?: MonitorCheckState | null;
  templateId?: string | null;
}

export interface MonitorCheckInput {
  name: string;
  server_id: string | null;
  check_type: MonitorCheckType;
  interval: MonitorInterval;
  severity: MonitorSeverity;
  consecutive_fails: number;
  description: string | null;
  config: MonitorCheckConfig;
}

export interface MonitoringMetricSeries {
  metric?: { __name__?: string; mount?: string; sensor?: string; [k: string]: string | undefined };
  values: [number, string][];
}

export interface MonitoringMetricsResponse {
  data?: MonitoringMetricSeries[];
  statusHistory?: MonitoringMetricSeries[];
}

export interface AlertChannelConfig {
  url?: string;
  recipients?: string[];
  to?: string;
  smtp_host?: string;
  smtp_port?: number;
  [key: string]: unknown;
}

export interface AlertRule {
  id: string;
  name: string;
  channel: AlertChannel;
  matchSeverity?: MonitorSeverity | null;
  matchServerId?: string | null;
  cooldownMinutes: number;
  channelConfig?: AlertChannelConfig;
  enabled: boolean;
}

export interface AlertRuleInput {
  name: string;
  channel: AlertChannel;
  match_severity: MonitorSeverity | null;
  match_server_id: string | null;
  cooldown_minutes: number;
  channel_config: AlertChannelConfig;
}

export interface AlertLogEntry {
  id: string;
  sentAt: string;
  checkId: string;
  oldStatus: MonStatus;
  newStatus: MonStatus;
  success: boolean;
  error?: string | null;
}

export interface TemplateCheckDef {
  def_id?: string;
  name: string;
  check_type: MonitorCheckType;
  config: MonitorCheckConfig;
  interval: MonitorInterval;
  severity: MonitorSeverity;
  consecutive_fails?: number;
}

export interface TemplateAlertDef {
  def_id?: string;
  name: string;
  channel: AlertChannel;
  channel_config: AlertChannelConfig;
  match_severity?: MonitorSeverity | null;
  cooldown_minutes: number;
  enabled?: boolean;
}

export interface MonitoringTemplateAssignment {
  serverId: string;
  serverName?: string;
}

export interface MonitoringTemplateFull {
  id: string;
  name: string;
  description?: string | null;
  checkDefinitions?: TemplateCheckDef[];
  alertDefinitions?: TemplateAlertDef[];
  assignments?: MonitoringTemplateAssignment[];
}

export interface MonitoringTemplateInput {
  name: string;
  description: string | null;
  check_definitions: TemplateCheckDef[];
  alert_definitions: TemplateAlertDef[];
}
