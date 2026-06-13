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
  description: string;
  config: MonitorCheckConfig;
}

export interface ValidationResult {
  ok: boolean;
  message?: string;
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
    description: c.description ?? '',
    config: { ...(c.config ?? {}) },
  };
}

export function formToInput(form: CheckForm): MonitorCheckInput {
  return {
    name: form.name.trim(),
    server_id: form.serverId || null,
    check_type: form.checkType,
    interval: form.interval,
    severity: form.severity,
    consecutive_fails: form.consecutiveFails || 3,
    description: form.description.trim() || null,
    config: { ...form.config },
  };
}

export function validateCheckForm(form: CheckForm): ValidationResult {
  if (!form.name.trim()) return { ok: false, message: tNow('monitoring.checkEdit.nameRequired') };
  return { ok: true };
}
