// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

export type ConnectionKind = 'ssh' | 'rdp' | 'web';

export interface Connection {
  id: string;
  /** The display name the server derives (R-1210); without a server the name itself. */
  name: string;
  /** The stored own text of the display name; without a server the name itself. */
  label?: string;
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
  options?: ConnectionOptions | null;
}

export type SshForwardKind = 'L' | 'R' | 'D';
export type SshAuthMethod = 'key' | 'agent' | 'password';

export interface SshForward {
  type: SshForwardKind;
  listen: string;
  target?: string | null;
}

export interface SshOptions {
  jumpHost?: string | null;
  forwards?: SshForward[];
  agentForwarding?: boolean | null;
  compression?: boolean | null;
  keepalive?: number | null;
  authMethod?: SshAuthMethod | null;
}

export type RdpAudio = 'local' | 'remote' | 'off';

export interface RdpConnectionOptions {
  scalingMode?: 'auto' | 'normal' | 'hdpi' | null;
  windowMode?: 'fit' | 'fullscreen' | 'multimon' | 'custom' | null;
  customSize?: string | null;
  performanceProfile?: 'auto' | 'lan' | 'broadband' | 'low' | null;
  drives?: boolean | null;
  audio?: RdpAudio | null;
  printers?: boolean | null;
  gateway?: string | null;
  nla?: boolean | null;
}

// `options` of the server API (R-1066), the same shape as the desktop model.
export interface ConnectionOptions {
  ssh?: SshOptions | null;
  rdp?: RdpConnectionOptions | null;
}

export interface Server {
  id: string;
  name: string;
  /** Where the server is reached: its own hostname, else its name (R-1210). */
  hostname: string;
  /** True when an own hostname is stored, false when the address follows the name. */
  customHostname?: boolean;
  osType?: string | null;
  tags?: string[];
  notes?: string | null;
  connections?: Connection[];
  frpTunnels?: FrpTunnel[];
  createdAt?: string | null;
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

export interface TemplateAssignment {
  templateId: string;
  serverId: string;
  id?: string;
  serverHostname?: string;
  serverName?: string;
  templateName?: string | null;
  // 'manual' = user-created, 'tag' = materialized by the monitoring tag-sync.
  source?: 'manual' | 'tag';
  // Template checks deleted on this server; the template sync leaves them deleted.
  removedChecks?: number;
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

export type FrpTunnelType = 'stcp' | 'https';
export type FrpProtocol = 'ssh' | 'rdp' | 'web';

export interface FrpTunnel {
  id: string;
  serverId: string;
  frpConfigId: string;
  /** The display name the server derives (R-1210): "{server} · {label|SSH|RDP|Web} (FRP)". */
  name: string;
  /** The stored own text of the display name, '' for none. */
  label?: string;
  tunnelType: FrpTunnelType;
  protocol: FrpProtocol;
  localIp: string | null;
  localPort: number;
  secretKey?: string | null;
  customDomains?: string | null;
  visitorPort?: number | null;
  connectionId?: string | null;
  enabled: boolean | null;
  tags?: string[];
  createdAt?: string | null;
}

export interface FrpTunnelInput {
  server_id: string;
  frp_config_id: string;
  name: string;
  /** The own text of the display name (R-1210); a server from before ignores it. */
  label?: string;
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
  /** The tunnel the proxy belongs to; its `name` is the display name the server derives (R-1210). */
  tunnel?: { id: string; name: string } | null;
}

export interface FrpStatus {
  proxies: FrpStatusProxy[];
  total?: number;
  error?: string | null;
}

export interface FrpProvisionToken {
  id: string;
  serverId: string;
  expiresAt: string | null;
  usedAt?: string | null;
  isValid: boolean;
  createdAt?: string | null;
}

export interface FrpProvisionTokenCreateResult {
  token: string;
  expiresAt: string | null;
  serverId: string;
  serverName: string;
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
  | 'smart_health'
  | 'disk_forecast'
  | 'system_state'
  | 'probe';

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
  // A disk's percentage alarm counts only below this many GB free; 0 turns it off.
  disk_min_free_gb?: number;
  // ignore_mounts and disk_overrides name exact mount paths.
  ignore_mounts?: string[];
  disk_overrides?: Record<string, { warn?: number; crit?: number; min_free_gb?: number }>;
  swap_warn?: number;
  swap_crit?: number;
  inode_warn?: number;
  inode_crit?: number;
  // Per CPU (load_5m / cpu_count), not a percentage.
  load_warn?: number;
  load_crit?: number;
  temp_warn?: number;
  temp_crit?: number;
  hysteresis_pp?: number;
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

  // zfs_health, docker_health and proxmox_backup; absent means true.
  alert_on_unavailable?: boolean;

  // docker_health
  ignore_containers?: string[];
  check_restarts?: boolean;

  // disk_forecast
  window_hours?: number;
  min_history_hours?: number;
  warn_hours?: number;
  crit_hours?: number;

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

  // system_state; absent means true.
  check_reboot?: boolean;
  check_time_sync?: boolean;
  check_security_updates?: boolean;
  check_oom?: boolean;

  [key: string]: unknown;
}

export interface MonitorResourceDisk {
  mount: string;
  percent: number;
  used_gb?: number;
  total_gb?: number;
  // From agent v3 (R-0423) on; inodes_percent only on Linux for a filesystem with inodes.
  free_gb?: number | null;
  inodes_percent?: number | null;
  // A mount from ignore_mounts: listed with its usage, but not rated.
  ignored?: boolean;
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
  // From agent v3 (R-0423) on, Linux only; swap_total_mb 0 is a host without a swap device.
  swap?: number | null;
  swap_total_mb?: number | null;
  swap_used_mb?: number | null;
  cpu_count?: number | null;
  load_per_cpu?: number | null;
  // false in a container, whose load_5m is the host's: the checker leaves the
  // load unrated. Missing on a host or a VM.
  load_rated?: boolean;
  // The checker's rating per metric (cpu, memory, swap, load, disk:<mount>,
  // inode:<mount>, temp:<sensor>); a metric it does not name is ok. Details
  // written before the per-metric hysteresis carry none.
  problems?: Record<string, 'warning' | 'critical'>;
  disks?: MonitorResourceDisk[];
  temperatures?: MonitorResourceTemp[];
}

export interface MonitorServiceDetails {
  mode?: 'auto' | 'list';
  failed?: string[];
  enabled_inactive?: string[];
  // Only with the agent's service counts; agents before R-0418 send none.
  active_count?: number;
  total?: number;
  // Details written before R-0418 carry running alone, without state.
  watched?: { name: string; state?: 'running' | 'down' | 'nodata'; running?: boolean }[];
}

export interface MonitorContainerDetails {
  // Details written before R-0419 carry neither. available false: the agent could
  // not read docker (error is the code), and containers is empty.
  available?: boolean;
  error?: string | null;
  containers?: {
    // id, reason, exit_code and restart_count also come with R-0419.
    id?: string | null;
    name: string;
    image?: string;
    state: string;
    // stopped: ended on purpose; the server counts it as ok.
    category: 'ok' | 'warning' | 'critical' | 'stopped';
    reason?: string | null;
    exit_code?: number | null;
    restart_count?: number | null;
  }[];
}

export interface MonitorBackupDetails {
  // Details written before R-0492 carry neither. available false: the agent could
  // not read Proxmox (error is the code), and vms is empty.
  available?: boolean;
  error?: string | null;
  vms?: {
    vmid: number;
    name: string;
    type?: string;
    backupStatus: 'ok' | 'outdated' | 'missing';
    ageHours?: number;
  }[];
}

export interface MonitorZfsDetails {
  // Details written before R-0419 carry neither. available false: the agent could
  // not read zpool (error is the code), and pools is empty.
  available?: boolean;
  error?: string | null;
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

export interface MonitorForecastDetails {
  // Field names match the disk_forecast checker's _details verbatim.
  mounts?: {
    mount: string;
    percent?: number;
    rate_pp_per_hour?: number;
    hours_left?: number | null;
    note?: string;
  }[];
}

export interface MonitorSystemStateDetails {
  // Field names match the system_state checker's _details verbatim. null: the
  // agent could not determine the point; all null without the block (agent
  // before report version 3, Windows).
  reboot_required?: boolean | null;
  time_synchronized?: boolean | null;
  security_updates?: number | null;
  oom_kills?: number | null;
  // The checker's rating (reboot, time_sync, security_updates, oom): a point it
  // does not name is no problem, even with a bad value (switched off, or the
  // clock in the first 15 minutes of uptime).
  problems?: string[];
}

export type MonitorCheckDetails =
  | MonitorResourceDetails
  | MonitorServiceDetails
  | MonitorContainerDetails
  | MonitorBackupDetails
  | MonitorZfsDetails
  | MonitorSmartDetails
  | MonitorForecastDetails
  | MonitorSystemStateDetails
  | Record<string, unknown>;

export interface MonitorCheckState {
  checkId?: string;
  status?: MonStatus;
  message?: string | null;
  lastCheck?: string | null;
  since?: string | null;
  failCount?: number | null;
  notifiedStatus?: string | null;
  details?: MonitorCheckDetails | null;
}

export interface MonitorCheck {
  id: string;
  name: string;
  serverId?: string | null;
  checkType: MonitorCheckType;
  interval: MonitorInterval;
  severity: MonitorSeverity;
  consecutiveFails?: number | null;
  consecutiveOks?: number;
  description?: string | null;
  enabled: boolean | null;
  config?: MonitorCheckConfig;
  state?: MonitorCheckState | null;
  templateId?: string | null;
  templateDefId?: string | null;
  // Template fields the user changed, which the template sync keeps; named as in
  // the request body (snake_case, e.g. 'check_type'), not as the fields above.
  overriddenFields?: string[];
  moduleId?: string | null;
  moduleInstance?: string | null;
  silent?: boolean;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface MonitorCheckInput {
  name: string;
  server_id: string | null;
  check_type: MonitorCheckType;
  interval: MonitorInterval;
  severity: MonitorSeverity;
  consecutive_fails: number;
  consecutive_oks: number;
  description: string | null;
  config: MonitorCheckConfig;
}

export interface MonitoringMetricSeries {
  metric?: { __name__?: string; mount?: string; sensor?: string; [k: string]: string | undefined };
  values: [number, string][];
}

export interface MaintenanceWindow {
  id: string;
  serverId?: string | null;
  note?: string | null;
  kind: 'once' | 'weekly';
  startsAt?: string | null;
  endsAt?: string | null;
  weekdays?: number[];
  startTime?: string | null;
  durationMinutes?: number | null;
  timezone: string;
  enabled: boolean | null;
  createdAt?: string | null;
}

export interface MaintenanceInput {
  server_id: string | null;
  note: string | null;
  kind: 'once' | 'weekly';
  starts_at: string | null;
  ends_at: string | null;
  weekdays: number[];
  start_time: string | null;
  duration_minutes: number | null;
  timezone: string;
  enabled: boolean;
}

export interface MonitoringMetricsResponse {
  checkId?: string;
  checkType?: string;
  period?: string;
  data?: MonitoringMetricSeries[];
  statusHistory?: MonitoringMetricSeries[];
}

/** [unix seconds, value]; value null where the history grid point has no sample. */
export type HistoryPoint = [number, number | null];

export interface HistorySeries {
  cpu: HistoryPoint[];
  ram: HistoryPoint[];
  swap: HistoryPoint[];
  loadPerCpu: HistoryPoint[];
  /** Mbit/s from the agent's byte counters; empty without network data. */
  netIn: HistoryPoint[];
  netOut: HistoryPoint[];
  disks: Record<string, HistoryPoint[]>;
}

/** One metric of every server with agent data on one grid (`GET /status/compare`). */
export interface ServerCompare {
  metric: string;
  period: string;
  step: number;
  start: number;
  end: number;
  servers: { serverId: string; points: HistoryPoint[] }[];
}

export interface ServerHistory {
  serverId: string;
  period: string;
  step: number;
  start: number;
  end: number;
  series: HistorySeries;
  previous: HistorySeries | null;
  thresholds: Record<string, { warn: number; crit: number }>;
  events: { at: number; checkId: string; checkName: string; status: string }[];
  maintenance: { start: number; end: number; note: string | null }[];
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
  cooldownMinutes: number | null;
  channelConfig?: AlertChannelConfig;
  enabled: boolean | null;
  templateId?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
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
  id: number;
  sentAt: string;
  alertRuleId: string;
  checkId: string;
  oldStatus: MonStatus;
  newStatus: MonStatus;
  success: boolean;
  error?: string | null;
}

// ── Notifications (server-side notification hub) ─────────────────────────────

export type NotificationSeverity = 'info' | 'warning' | 'critical';
export type NotificationScopeType = 'all' | 'tag' | 'server';
export type IncidentState = 'open' | 'acked' | 'resolved';

// One bell-feed entry (mirrors the server's incidents.feed_rows). The incident fields are
// optional because a server before R-1079 sends none of them; they are null for a row without
// an incident and for one whose servers the reader no longer sees.
export interface NotificationItem {
  id: number;
  createdAt: string | null;
  severity: NotificationSeverity;
  category: string;
  eventType: string;
  title: string;
  body?: string | null;
  sourceType?: string | null;
  sourceId?: string | null;
  read: boolean;
  readAt?: string | null;
  incidentId?: number | null;
  state?: IncidentState | null;
  count?: number | null;
  ackedBy?: string | null;
  resolvedBy?: string | null;
  // The last ping of the row: a ping moves it up and sets it unread again.
  notifiedAt?: string | null;
  muted?: boolean;
  mutedUntil?: string | null;
  muteSource?: 'incident' | 'server' | null;
}

export type IncidentEntryKind =
  'triggered' | 'notified' | 'escalated' | 'acked' | 'resolved' | 'reopened' | 'note';

export interface IncidentEntry {
  id: number;
  at: string;
  kind: IncidentEntryKind;
  // The username; null: done by the hub itself, or a deleted user.
  actor: string | null;
  text: string | null;
  // 'ok' is written by the hub for a recovery entry.
  severity: NotificationSeverity | 'ok' | null;
  serverId: string | null;
}

export interface IncidentServer {
  id: string;
  name: string;
  // A bundle member's recovery; null while it is down, and for a single incident.
  recoveredAt: string | null;
}

// What one alert rule of the monitoring service did with the incident's last event.
export interface IncidentRule {
  name: string;
  channel: string;
  ok: boolean;
}

// An incident as its reader may see it: only the servers they see, the history without
// entries of the others.
export interface IncidentDetail {
  id: number;
  state: IncidentState;
  severity: NotificationSeverity;
  category: string;
  eventType: string;
  title: string;
  body: string | null;
  sourceType: string | null;
  sourceId: string | null;
  count: number;
  firstAt: string;
  lastAt: string;
  ackedBy: string | null;
  ackedAt: string | null;
  resolvedBy: string | null;
  resolvedAt: string | null;
  bundle: boolean;
  servers: IncidentServer[];
  // null: the sender reports no rules (only the monitoring service does).
  rules: IncidentRule[] | null;
  channels: ('bell' | 'email' | 'ntfy' | 'telegram' | 'webhook')[];
  history: IncidentEntry[];
  // The reader sees every server of it: acknowledge, resolve, reopen, note.
  canAct: boolean;
  row: NotificationItem;
}

export interface IncidentAckResult {
  updated: number;
  // Not acknowledged: not the caller's, not seen in full, or not open.
  skipped: number[];
}

export interface NotificationServerMute {
  serverId: string;
  until: string;
}

// One per-user subscription rule (mirrors NotificationSubscription.to_dict()). It decides what
// reaches the bell; which channels a ping goes to is the matrix of NotificationPrefs (R-1080).
export interface NotificationSubscription {
  id: number;
  userId: number;
  scopeType: NotificationScopeType;
  scopeRef?: string | null;
  minSeverity: NotificationSeverity;
  categories?: string | null; // JSON array string, or null = every category
  enabled: boolean;
}

export type NotificationChannel = 'desktop' | 'email' | 'ntfy' | 'telegram' | 'webhook';
// The row of the matrix: the severity of the ping, ok for the all-clear.
export type NotificationMatrixRow = NotificationSeverity | 'ok';
export type NotificationMatrix = Record<NotificationMatrixRow, NotificationChannel[]>;

// Which channels the server can deliver (e-mail only with SMTP, Telegram only with a bot token).
export interface NotificationAvailableChannels {
  desktop: boolean;
  email: boolean;
  ntfy: boolean;
  telegram: boolean;
  webhook: boolean;
}

// Quiet hours in the person's zone, across midnight when end is earlier (R-1081).
export interface NotificationQuiet {
  enabled: boolean;
  start: string; // HH:MM
  end: string; // HH:MM
  critical: boolean; // critical pings pass the quiet hours and do not disturb
}

export interface NotificationEscalation {
  enabled: boolean;
  minutes: 5 | 10 | 30;
  channel: NotificationTestChannel | null;
}

export type NotificationDigest = 'off' | 'daily' | 'weekly';

// The fields of R-1080 and R-1081 are optional: a server before them sends none of them.
export interface NotificationPrefs {
  email: string | null;
  telegramChatId: string | null;
  ntfyUrl?: string | null;
  webhookUrl?: string | null;
  matrix?: NotificationMatrix;
  disabledChannels?: NotificationChannel[];
  mutedCategories?: string[];
  available?: NotificationAvailableChannels;
  timezone?: string;
  quiet?: NotificationQuiet;
  escalation?: NotificationEscalation;
  digest?: NotificationDigest;
  soundCritical?: boolean;
  subscriptions: NotificationSubscription[];
}

// PUT payload (snake_case — the server schema). categories is a string array
// here; the server stores it as a JSON string.
export interface NotificationSubscriptionInput {
  scope_type: NotificationScopeType;
  scope_ref?: string | null;
  min_severity: NotificationSeverity;
  categories?: string[] | null;
  enabled: boolean;
}

// A field of the channel settings that is not sent keeps its stored value; a URL sent as
// null is cleared.
export interface NotificationPrefsUpdate {
  email?: string | null;
  telegram_chat_id?: string | null;
  ntfy_url?: string | null;
  webhook_url?: string | null;
  matrix?: NotificationMatrix;
  disabled_channels?: NotificationChannel[];
  muted_categories?: string[];
  timezone?: string;
  quiet?: NotificationQuiet;
  escalation?: NotificationEscalation;
  digest?: NotificationDigest;
  sound_critical?: boolean;
  subscriptions: NotificationSubscriptionInput[];
}

// The channels the server tests; the desktop tests itself.
export type NotificationTestChannel = Exclude<NotificationChannel, 'desktop'>;

export interface NotificationTestResult {
  channel: string;
}

export interface TemplateCheckDef {
  def_id?: string;
  name: string;
  check_type: MonitorCheckType;
  config: MonitorCheckConfig;
  interval: MonitorInterval;
  severity: MonitorSeverity;
  consecutive_fails?: number;
  consecutive_oks?: number;
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
  id: string;
  templateId: string;
  serverId: string;
  serverName?: string;
  serverHostname?: string;
  source?: 'manual' | 'tag';
}

export interface MonitoringTemplateTagAssignment {
  id: string;
  templateId: string;
  tag: string;
}

export interface MonitoringTemplateFull {
  id: string;
  name: string;
  description?: string | null;
  // Set on shipped standard templates (seeded at monitoring startup).
  builtinSlug?: string | null;
  // Shipped version last rolled out to this standard template; null on user templates.
  builtinVersion?: number | null;
  // Definitions changed since that rollout: a newer shipped version is then only
  // offered (builtinUpdateAvailable), not taken automatically.
  builtinEdited?: boolean;
  builtinUpdateAvailable?: boolean;
  checkDefinitions?: TemplateCheckDef[];
  alertDefinitions?: TemplateAlertDef[];
  assignments?: MonitoringTemplateAssignment[] | null;
  tagAssignments?: MonitoringTemplateTagAssignment[] | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

// A definition as GET /templates/{id}/builtin-update shows it: every key at its
// schema default is left out (the form the server hashes), so two definitions are
// the same exactly when their keys and values are.
export type MonitoringBuiltinCheckDef = Pick<TemplateCheckDef, 'name' | 'check_type'> &
  Partial<TemplateCheckDef> & { enabled?: boolean; description?: string | null };
export type MonitoringBuiltinAlertDef = Pick<TemplateAlertDef, 'name' | 'channel'> &
  Partial<TemplateAlertDef>;

export interface MonitoringBuiltinDefinitions {
  checkDefinitions: MonitoringBuiltinCheckDef[];
  alertDefinitions: MonitoringBuiltinAlertDef[];
}

// Current definitions of a standard template next to those of its shipped version.
export interface MonitoringBuiltinUpdate {
  currentVersion: number | null;
  shippedVersion: number;
  current: MonitoringBuiltinDefinitions;
  shipped: MonitoringBuiltinDefinitions;
}

// A standard template the server's host facts suggest; `reason` is `os:<os>` or
// `subsystem:<name>`.
export interface TemplateSuggestion {
  slug: string;
  templateId: string;
  templateName: string;
  reason: string;
}

export interface MonitoringTemplateInput {
  name: string;
  description: string | null;
  check_definitions: TemplateCheckDef[];
  alert_definitions: TemplateAlertDef[];
}
