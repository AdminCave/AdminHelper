// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Form model for per-server monitoring checks. Mirrors the serverConnection
// model's shape (id|null carries new-vs-edit, formToInput builds the snake_case
// API payload). Pure logic so the mapping and validation stay unit-testable; the
// per-type config fields are rendered by CheckConfigFields and stored in
// `config` as the raw MonitorCheckConfig the API round-trips unchanged.

import type {
  MonitorCheck,
  MonitorCheckConfig,
  MonitorCheckInput,
  MonitorCheckType,
  MonitorInterval,
  MonitorSeverity,
} from '$lib/api/types';
import { tNow } from '$lib/i18n';
import type { ValidationResult } from './shared';

export const CHECK_TYPES: MonitorCheckType[] = [
  'ping',
  'tcp',
  'http',
  'agent_ping',
  'agent_resources',
  'service_process',
  'proxmox_backup',
  'zfs_health',
  'docker_health',
  'smart_health',
  'disk_forecast',
  'system_state',
];

// A template never carries a central check (the server refuses one), so only the
// check form offers it.
export const SERVER_CHECK_TYPES: MonitorCheckType[] = [...CHECK_TYPES, 'central'];

export const INTERVALS: MonitorInterval[] = ['1m', '5m', '15m', '30m', '1h', '6h', '12h', '24h'];

export const SEVERITIES: MonitorSeverity[] = ['critical', 'warning', 'info'];

// ── Central checks (R-1224) ──────────────────────────────────────────────────
// The monitoring service probes a public endpoint itself. The table mirrors
// CENTRAL_SENSORS in apps/monitoring/app/check_configs.py; the server refuses what
// does not fit anyway, the form only keeps to what can pass.

export type CentralSensorName = 'tls' | 'dns' | 'rdap' | 'smtp' | 'imap' | 'mail_dns' | 'dnsbl';

export interface CentralSensorSpec {
  minInterval: MonitorInterval;
  defaultInterval: MonitorInterval;
  /** The port a config without one uses; null: the sensor takes no port. */
  defaultPort: number | null;
  /** The only ports the sensor takes; null: any but the refused ones. */
  ports: number[] | null;
  /** The host must be a name, not an IP address. */
  needsName: boolean;
}

export const CENTRAL_SENSORS: Record<CentralSensorName, CentralSensorSpec> = {
  tls: {
    minInterval: '15m',
    defaultInterval: '1h',
    defaultPort: 443,
    ports: null,
    needsName: false,
  },
  dns: {
    minInterval: '5m',
    defaultInterval: '15m',
    defaultPort: null,
    ports: null,
    needsName: true,
  },
  rdap: {
    minInterval: '24h',
    defaultInterval: '24h',
    defaultPort: null,
    ports: null,
    needsName: true,
  },
  smtp: {
    minInterval: '15m',
    defaultInterval: '15m',
    defaultPort: 25,
    ports: [25, 465, 587],
    needsName: false,
  },
  imap: {
    minInterval: '15m',
    defaultInterval: '15m',
    defaultPort: 993,
    ports: [143, 993, 995],
    needsName: false,
  },
  mail_dns: {
    minInterval: '1h',
    defaultInterval: '1h',
    defaultPort: null,
    ports: null,
    needsName: true,
  },
  dnsbl: {
    minInterval: '24h',
    defaultInterval: '24h',
    defaultPort: null,
    ports: null,
    needsName: true,
  },
};

export const CENTRAL_SENSOR_NAMES = Object.keys(CENTRAL_SENSORS) as CentralSensorName[];

// The sensors whose red result the agent's own probe of the service explains
// (path or service); the others ignore a partner.
const PAIRED_SENSORS: readonly CentralSensorName[] = ['tls', 'dns', 'smtp', 'imap'];

export const DNSBL_LISTS = [
  { key: 'psbl', label: 'PSBL' },
  { key: 'spamcop', label: 'SpamCop' },
  { key: 'uceprotect1', label: 'UCEPROTECT Level 1' },
  { key: 'spamhaus_zen', label: 'Spamhaus ZEN (DQS)' },
] as const;

export function centralSensorOf(config: MonitorCheckConfig | undefined): CentralSensorName | null {
  const name = config?.sensor;
  return typeof name === 'string' && Object.hasOwn(CENTRAL_SENSORS, name)
    ? (name as CentralSensorName)
    : null;
}

export function sensorTakesPartner(sensor: CentralSensorName): boolean {
  return PAIRED_SENSORS.includes(sensor);
}

/** A central dns check learns a baseline only without expected addresses; only then
 * can it learn it again. */
export function learnsBaseline(check: MonitorCheck | null): boolean {
  if (check?.checkType !== 'central' || centralSensorOf(check.config) !== 'dns') return false;
  const params: unknown = check.config?.params;
  return !(typeof params === 'object' && params !== null && 'expected' in params);
}

/** The intervals the form offers: a central sensor's from its shortest on. */
export function intervalsFor(
  checkType: MonitorCheckType,
  config: MonitorCheckConfig,
): MonitorInterval[] {
  const sensor = checkType === 'central' ? centralSensorOf(config) : null;
  if (sensor === null) return INTERVALS;
  return INTERVALS.slice(INTERVALS.indexOf(CENTRAL_SENSORS[sensor].minInterval));
}

/** The config of a central check switched to `sensor`: the host stays, the port goes
 * to the sensor's default, params and partner go (each sensor has its own). */
export function centralConfigFor(
  sensor: CentralSensorName,
  from: MonitorCheckConfig,
): MonitorCheckConfig {
  const out: MonitorCheckConfig = { sensor, host: typeof from.host === 'string' ? from.host : '' };
  const port = CENTRAL_SENSORS[sensor].defaultPort;
  if (port !== null) out.port = port;
  return out;
}

/** The checks `sensor` may take as partner: the agent's probes of the same service
 * (tls or http), and a certfile probe that stores not_after for the sensor tls,
 * as the server's checks router allows. `checks` are the server's own. */
export function partnersFor(sensor: CentralSensorName, checks: MonitorCheck[]): MonitorCheck[] {
  if (!sensorTakesPartner(sensor)) return [];
  return checks.filter((c) => {
    if (c.checkType !== 'probe') return false;
    const probeSensor = c.config?.sensor;
    if (probeSensor === 'tls' || probeSensor === 'http') return true;
    const fields = c.config?.fields;
    return (
      sensor === 'tls' &&
      probeSensor === 'certfile' &&
      Array.isArray(fields) &&
      fields.includes('not_after')
    );
  });
}

export interface CheckForm {
  id: string | null;
  serverId: string;
  name: string;
  checkType: MonitorCheckType;
  interval: MonitorInterval;
  severity: MonitorSeverity;
  consecutiveFails: number;
  consecutiveOks: number;
  description: string;
  config: MonitorCheckConfig;
}

export function emptyCheckForm(serverId: string): CheckForm {
  return {
    id: null,
    serverId,
    name: '',
    checkType: 'ping',
    interval: '5m',
    severity: 'critical',
    consecutiveFails: 3,
    consecutiveOks: 2,
    description: '',
    config: {},
  };
}

export function checkToForm(c: MonitorCheck): CheckForm {
  return {
    id: c.id,
    serverId: c.serverId ?? '',
    name: c.name,
    checkType: c.checkType,
    interval: c.interval,
    severity: c.severity,
    consecutiveFails: c.consecutiveFails ?? 3,
    consecutiveOks: c.consecutiveOks ?? 2,
    description: c.description ?? '',
    config: { ...(c.config ?? {}) },
  };
}

// An OOM kill is in the one report after it only (the agent sends the growth
// since its last report), so a system_state check reports it only with one
// fail in a row; the built-in template uses 1 for the same reason.
const SYSTEM_STATE_FAILS = 1;

/** Fails in a row once the form's type changes from `from` to `to`: picking
 * system_state suggests 1, and leaving it with that 1 untouched goes back to
 * `before`, the value the caller remembered when system_state was picked (the
 * form's default 3 without one, e.g. for a check stored as system_state), so
 * passing through the type leaves no 1 on another check. Otherwise the value
 * entered stays. */
export function failsAfterTypeChange(
  from: MonitorCheckType,
  to: MonitorCheckType,
  current: number,
  before = 3,
): number {
  if (to === 'system_state') return SYSTEM_STATE_FAILS;
  if (from === 'system_state' && current === SYSTEM_STATE_FAILS) return before;
  return current;
}

export function formToInput(form: CheckForm): MonitorCheckInput {
  const config = { ...form.config };
  if (form.checkType === 'central' && typeof config.host === 'string') {
    config.host = config.host.trim();
  }
  return {
    name: form.name.trim(),
    server_id: form.serverId || null,
    check_type: form.checkType,
    interval: form.interval,
    severity: form.severity,
    consecutive_fails: form.consecutiveFails || 3,
    consecutive_oks: form.consecutiveOks || 2,
    description: form.description.trim() || null,
    config,
  };
}

export function validateCheckForm(form: CheckForm): ValidationResult {
  if (!form.name.trim()) return { ok: false, message: tNow('monitoring.checkEdit.nameRequired') };
  const host = form.config.host;
  if (form.checkType === 'central' && (typeof host !== 'string' || !host.trim())) {
    return { ok: false, message: tNow('monitoring.checkEdit.hostRequired') };
  }
  return { ok: true };
}
