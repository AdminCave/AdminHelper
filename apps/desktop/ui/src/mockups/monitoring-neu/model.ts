// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Data model of the monitoring re-design mockup (R-1558, ADR 0004). Fictitious data only: the
// mockup shows how the target model would look; nothing here talks to a server. Every status is
// given by the fixtures as the server would deliver it; the UI never rates a value itself.

/** Status of an object as the server delivers it. */
export type Status = 'critical' | 'warning' | 'unknown' | 'stale' | 'info' | 'not-collected' | 'ok';

export type Kind =
  | 'disk'
  | 'pool'
  | 'guest-backup'
  | 'backup-job'
  | 'host'
  | 'cpu'
  | 'memory'
  | 'mount'
  | 'sensor'
  | 'reboot'
  | 'updates'
  | 'clock'
  | 'service'
  | 'container'
  | 'compose-project'
  | 'certificate'
  | 'domain'
  | 'endpoint'
  | 'module';

/** Threshold context of a metric; `below` marks values that are bad when they fall. */
export interface Threshold {
  warn?: number;
  crit?: number;
  below?: boolean;
}

export interface Metric {
  key: string;
  label: string;
  value: number | string;
  unit?: string;
  /** Required on purpose: null states that the metric is shown without a threshold. */
  threshold: Threshold | null;
  /** The metric's own status, if a rule rates it. */
  status?: Status;
  /** Short addition, e.g. the trend ("+2 seit gestern"). */
  note?: string;
  /** The agent does not deliver this value yet (new agent data needed). */
  newData?: boolean;
}

export interface Attribute {
  key: string;
  value: string;
  mono?: boolean;
}

export interface HistoryEvent {
  at: string;
  status: Status;
  text: string;
}

export interface RuleView {
  /** Stable rule key, survives catalog updates. */
  key: string;
  /** The rule in plain words, e.g. "Umgelagerte Sektoren steigen". */
  text: string;
  level: 'warning' | 'critical';
  source: 'Katalog' | 'Katalog, geändert' | 'eigene';
  enabled: boolean;
  /** The rule fires right now. */
  firing?: boolean;
}

/** What an exception does to the objects it covers. */
export type Effect = 'skip' | 'no-rating' | 'no-notify' | 'mute-me';

export interface ExceptionInfo {
  effect: Effect;
  /** Where it applies, in words ("dieses Objekt", "Tag backup-test"). */
  scope: string;
  reason?: string;
  by: string;
  at: string;
  until?: string;
  /** The exception is bound to this value and ends when it changes. */
  boundValue?: string;
}

/** One SMART attribute as smartctl reports it. */
export interface SmartRow {
  id?: number;
  name: string;
  raw: string;
  normalized?: number;
  threshold?: number;
  /** smartctl `WHEN_FAILED` ("FAILING_NOW", "In_the_past"). */
  whenFailed?: string;
  status?: Status;
}

export interface SmartDetail {
  type: 'smart';
  title: string;
  rows: SmartRow[];
  /** Set bits of the smartctl exit status, in plain words. */
  exitBits: { bit: number; text: string }[];
}

export interface VdevNode {
  name: string;
  /** ZFS state as zpool prints it (ONLINE, DEGRADED, FAULTED …). */
  state: string;
  status: Status;
  read: number;
  write: number;
  cksum: number;
  note?: string;
  children?: VdevNode[];
}

export interface VdevDetail {
  type: 'vdev';
  title: string;
  root: VdevNode;
}

export interface BackupEntry {
  at: string;
  size: string;
  storage: string;
  verify: 'ok' | 'failed' | 'none';
  protected?: boolean;
  status?: Status;
}

export interface BackupDetail {
  type: 'backups';
  title: string;
  rows: BackupEntry[];
  retention?: string;
}

export interface TrendPoint {
  at: string;
  value: number;
}

export interface TrendDetail {
  type: 'trend';
  title: string;
  unit?: string;
  points: TrendPoint[];
  threshold?: Threshold;
  /** Projected values after the last point (mount forecast), drawn as a dashed line. */
  forecast?: TrendPoint[];
}

export interface LogLine {
  at: string;
  /** systemd unit or kernel. */
  source: string;
  priority: 'err' | 'warning' | 'notice' | 'info';
  text: string;
}

export interface LogDetail {
  type: 'log';
  title: string;
  lines: LogLine[];
  /** Where the full log is, e.g. the journalctl call. */
  more?: string;
}

export interface ProcessRow {
  pid: number;
  name: string;
  user: string;
  cpu: number;
  memMb: number;
}

export interface ProcessDetail {
  type: 'processes';
  title: string;
  rows: ProcessRow[];
  sortedBy: 'cpu' | 'mem';
  /** The agent does not send the process list yet (R-1389). */
  newData?: boolean;
}

/** Kind-specific blocks of level 3; later tasks add more. */
export type Detail =
  | { type: 'note'; title: string; text: string }
  | SmartDetail
  | VdevDetail
  | BackupDetail
  | TrendDetail
  | LogDetail
  | ProcessDetail;

export interface MonObject {
  /** Stable key, unique across all objects. */
  key: string;
  kind: Kind;
  name: string;
  server: string;
  /** Identity line: model or type, place (server, path, pool). */
  identity: string[];
  status: Status;
  /** One sentence in plain words. */
  reason: string;
  /** Last status change. */
  since: string;
  /** First change away from ok; stays when warning turns critical (Konzept: bad_since). */
  badSince?: string;
  metrics: Metric[];
  attributes?: Attribute[];
  details?: Detail[];
  history?: HistoryEvent[];
  rules?: RuleView[];
  raw?: string;
  exception?: ExceptionInfo;
  /** Catalog family of a module object. */
  family?: string;
  /** Key of the module instance a named part belongs to (offene Frage 7). */
  parent?: string;
}
