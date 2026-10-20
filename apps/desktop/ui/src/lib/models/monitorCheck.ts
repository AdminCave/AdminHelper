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

export const INTERVALS: MonitorInterval[] = ['1m', '5m', '15m', '30m', '1h', '6h', '12h', '24h'];

export const SEVERITIES: MonitorSeverity[] = ['critical', 'warning', 'info'];

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
  return {
    name: form.name.trim(),
    server_id: form.serverId || null,
    check_type: form.checkType,
    interval: form.interval,
    severity: form.severity,
    consecutive_fails: form.consecutiveFails || 3,
    consecutive_oks: form.consecutiveOks || 2,
    description: form.description.trim() || null,
    config: { ...form.config },
  };
}

export function validateCheckForm(form: CheckForm): ValidationResult {
  if (!form.name.trim()) return { ok: false, message: tNow('monitoring.checkEdit.nameRequired') };
  return { ok: true };
}
