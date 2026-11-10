// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Plain-text sentences for the monitoring cards (concept §3.14): sensor status, why a
// notification is muted, certificate expiry, age and values with their unit.
// The translator comes from the caller (`$t`), so a language switch re-renders.

import type { MonitorCheck, MonitorMutedReason, MonitorProbeValue } from '$lib/api/types';
import { currentLocale, type TranslateFn } from '$lib/i18n';
import { computeSummary } from '$lib/models/monitoring';
import { timeAgo } from '$lib/utils/timeAgo';

// Spelled out: the i18n "no unused keys" guard only sees quoted keys.
const PROBE_STATUS_KEY = new Map<string, string>([
  ['ok', 'monitoring.probe.ok'],
  ['error', 'monitoring.probe.error'],
  ['denied', 'monitoring.probe.denied'],
  ['no_credential', 'monitoring.probe.noCredential'],
  ['not_allowed', 'monitoring.probe.notAllowed'],
  ['unsupported', 'monitoring.probe.unsupported'],
  ['ambiguous_target', 'monitoring.probe.ambiguousTarget'],
  ['invalid', 'monitoring.probe.invalid'],
]);

const MUTED_KEY = new Map<MonitorMutedReason, string>([
  ['maintenance window', 'monitoring.muted.maintenance'],
  ['host down', 'monitoring.muted.hostDown'],
  ['silent check', 'monitoring.muted.silent'],
]);

/** What a sensor answered, as a sentence; null before its first answer. */
export function probeStatusText(t: TranslateFn, status: string | null | undefined): string | null {
  if (!status) return null;
  // A code of a newer agent still says something.
  const key = PROBE_STATUS_KEY.get(status);
  return key ? t(key) : t('monitoring.probe.other', { code: status });
}

/** Why the check's notifications are held back; null when they are not. */
export function mutedReasonText(
  t: TranslateFn,
  reason: MonitorMutedReason | null | undefined,
): string | null {
  if (!reason) return null;
  const key = MUTED_KEY.get(reason);
  return key ? t(key) : null;
}

/**
 * Why a card's notifications are held back. Host down outranks a maintenance window as
 * soon as one check has it; "silent" only when every check is silent, otherwise the
 * card marks its silent checks one by one. Null when the card alerts as usual.
 */
export function cardNote(t: TranslateFn, checks: MonitorCheck[]): string | null {
  for (const reason of ['host down', 'maintenance window'] as const) {
    if (checks.some((c) => c.mutedReason === reason)) return mutedReasonText(t, reason);
  }
  if (checks.length > 0 && checks.every((c) => c.mutedReason === 'silent check')) {
    return mutedReasonText(t, 'silent check');
  }
  return null;
}

/** A closed card's line: its problems by status, else how many checks it has. */
export function cardSummary(t: TranslateFn, checks: MonitorCheck[]): string {
  const s = computeSummary(checks);
  const parts: string[] = [];
  if (s.critical) parts.push(`${s.critical} ${t('monitoring.status.critical')}`);
  if (s.warning) parts.push(`${s.warning} ${t('monitoring.status.warning')}`);
  if (s.unknown) parts.push(`${s.unknown} ${t('monitoring.status.unknown')}`);
  return parts.length ? parts.join(' · ') : `${checks.length} ${t('monitoring.grid.checks')}`;
}

export type ExpiryLevel = 'expired' | 'critical' | 'warning' | 'ok';

const HOUR_S = 3600;
const DAY_S = 24 * HOUR_S;
// Concept §5: the critical mark never drops below 12 h, however short the lifetime.
const MIN_CRITICAL_S = 12 * HOUR_S;

/**
 * Concept §5, relative to the lifetime L = notAfter − notBefore: warning under 25 % of L
 * left, critical under 10 % (at least 12 h). Without notBefore (sensor rows carry only
 * not_after) there is no L: null, the check's own status counts. Display only, no alert.
 * All times in Unix seconds.
 */
export function expiryLevel(
  notAfter: number,
  notBefore: number | null | undefined,
  now: number,
): ExpiryLevel | null {
  const left = notAfter - now;
  if (left <= 0) return 'expired';
  if (notBefore == null) return null;
  const lifetime = notAfter - notBefore;
  if (lifetime <= 0) return null;
  if (left < Math.max(lifetime * 0.1, MIN_CRITICAL_S)) return 'critical';
  if (left < lifetime * 0.25) return 'warning';
  return 'ok';
}

/** "Expires in 9 days" / "Expired 3 days ago"; whole days from two days on, else hours. */
export function expiryText(t: TranslateFn, notAfter: number, now: number): string {
  const left = notAfter - now;
  if (left > 0) {
    if (left >= 2 * DAY_S)
      return t('monitoring.expiry.inDays', { count: Math.floor(left / DAY_S) });
    const hours = Math.floor(left / HOUR_S);
    if (hours >= 2) return t('monitoring.expiry.inHours', { count: hours });
    return t(hours === 1 ? 'monitoring.expiry.inOneHour' : 'monitoring.expiry.inUnderHour');
  }
  const past = -left;
  if (past >= 2 * DAY_S) return t('monitoring.expiry.agoDays', { count: Math.floor(past / DAY_S) });
  if (past >= 2 * HOUR_S)
    return t('monitoring.expiry.agoHours', { count: Math.floor(past / HOUR_S) });
  return t('monitoring.expiry.justNow');
}

/**
 * "5 min ago" for a monitoring timestamp. Services before R-0202 send them without a
 * zone; they are UTC, which Date.parse would read as local time.
 */
export function ageText(t: TranslateFn, iso: string | null | undefined): string {
  if (!iso) return timeAgo(iso, t);
  const zoned = /(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`;
  return timeAgo(zoned, t);
}

function daysText(t: TranslateFn, days: number): string {
  return days === 1 ? t('monitoring.unit.oneDay') : t('monitoring.unit.days', { count: days });
}

/** A span of seconds in its largest whole unit: "45 s", "12 min", "3 h", "4 days". */
export function spanText(t: TranslateFn, seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return t('monitoring.unit.seconds', { count: s });
  if (s < HOUR_S) return t('monitoring.unit.minutes', { count: Math.floor(s / 60) });
  if (s < DAY_S) return t('monitoring.unit.hours', { count: Math.floor(s / HOUR_S) });
  return daysText(t, Math.floor(s / DAY_S));
}

const BYTE_UNITS = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];

function number(n: number, digits = 0): string {
  return n.toLocaleString(currentLocale(), { maximumFractionDigits: digits });
}

export function bytesText(bytes: number): string {
  let value = bytes;
  let unit = 0;
  while (Math.abs(value) >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${number(value, unit === 0 ? 0 : 1)} ${BYTE_UNITS[unit]}`;
}

/**
 * A sensor field's value with its unit. The unit comes from the field name the catalog
 * uses (`*_bytes`, `*_ms`, `*_s`, `days_left`, `not_after`); others are plain numbers.
 */
export function valueText(
  t: TranslateFn,
  field: string,
  value: MonitorProbeValue | undefined,
): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return t(value ? 'monitoring.value.yes' : 'monitoring.value.no');
  if (typeof value === 'string') return value;
  const name = field.split('.').pop() ?? field;
  if (name === 'not_after') {
    return new Date(value * 1000).toLocaleDateString(currentLocale(), {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  }
  if (name === 'days_left') return daysText(t, Math.floor(value));
  if (name.endsWith('_bytes')) return bytesText(value);
  if (name.endsWith('_ms')) return `${number(value)} ms`;
  if (name.endsWith('_s')) return spanText(t, value);
  return number(value, 2);
}

/**
 * What identifies a found instance, from the finding's summary (discovery.py): its image,
 * the compose services, the unit or process, or what matched a package install.
 */
export function findingDetail(summary: Record<string, unknown>): string | null {
  const { image, services, unit, process: proc, matched_by: matchedBy } = summary;
  if (typeof image === 'string' && image) return image;
  if (services && typeof services === 'object' && !Array.isArray(services)) {
    const names = Object.keys(services);
    if (names.length) return names.join(', ');
  }
  if (typeof unit === 'string' && unit) return unit;
  if (typeof proc === 'string' && proc) return proc;
  if (Array.isArray(matchedBy) && matchedBy.length) return matchedBy.join(', ');
  return null;
}
