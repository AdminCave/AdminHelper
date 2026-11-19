// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Presentation grammar of the monitoring re-design (ADR 0004): level 1 = status badge, one sentence
// of reason and "seit"; level 2 = at most four metrics, each with its threshold context; level 3 =
// the drawer. Sorting: worst first, hidden objects grey at the end.

import type { Effect, ExceptionInfo, Kind, Metric, MonObject, Status, Threshold } from './model';

export const MAX_METRICS = 4;

// Worst first. Unknown ranks above stale: a check that cannot rate is closer to a problem than an
// old value of a host that went quiet, which has its own host object.
const ORDER: Status[] = ['critical', 'warning', 'unknown', 'stale', 'info', 'not-collected', 'ok'];

export const STATUS_LABEL: Record<Status, string> = {
  critical: 'Kritisch',
  warning: 'Warnung',
  unknown: 'Unbekannt',
  stale: 'Veraltet',
  info: 'Info',
  'not-collected': 'Nicht erhoben',
  ok: 'OK',
};

export type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

export const STATUS_TONE: Record<Status, Tone> = {
  critical: 'danger',
  warning: 'warning',
  unknown: 'neutral',
  stale: 'neutral',
  info: 'info',
  'not-collected': 'neutral',
  ok: 'success',
};

export const KIND_LABEL: Record<Kind, string> = {
  disk: 'Platte',
  pool: 'Pool',
  'guest-backup': 'Gast-Backup',
  'backup-job': 'Backup-Job',
  host: 'Host',
  cpu: 'CPU',
  memory: 'Arbeitsspeicher',
  mount: 'Mount',
  sensor: 'Sensor',
  reboot: 'Neustart',
  updates: 'Updates',
  clock: 'Uhr',
  service: 'Dienst',
  container: 'Container',
  'compose-project': 'Compose-Projekt',
  certificate: 'Zertifikat',
  domain: 'Domain',
  endpoint: 'Endpunkt',
  module: 'Modul',
};

export const EFFECT_LABEL: Record<Effect, string> = {
  skip: 'nicht prüfen',
  'no-rating': 'prüfen, nicht bewerten',
  'no-notify': 'bewerten, nicht melden',
  'mute-me': 'nur für mich still',
};

export function statusRank(s: Status): number {
  return ORDER.indexOf(s);
}

/** Hidden objects are not rated: they show grey at the end of every list. An exception for one
 * rule leaves the object rated by its other rules, an ended one hides nothing any more. */
export function isHidden(o: MonObject): boolean {
  const e = o.exception;
  return !!e && !e.rule && !e.ended && (e.effect === 'skip' || e.effect === 'no-rating');
}

/** Server, then name: the order of a tie. */
export function byPlace(a: MonObject, b: MonObject): number {
  return a.server.localeCompare(b.server, 'de') || a.name.localeCompare(b.name, 'de');
}

export function sortObjects(list: readonly MonObject[]): MonObject[] {
  const shown = list.filter((o) => !isHidden(o));
  const hidden = list.filter(isHidden);
  shown.sort((a, b) => statusRank(a.status) - statusRank(b.status) || byPlace(a, b));
  hidden.sort(byPlace);
  return [...shown, ...hidden];
}

const NUM = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 1 });

export function formatValue(value: number | string, unit?: string): string {
  const v = typeof value === 'number' ? NUM.format(value) : value;
  return unit ? `${v} ${unit}` : v;
}

export function thresholdText(t: Threshold | null): string {
  if (!t) return '';
  const word = t.below ? 'unter' : 'ab';
  const parts: string[] = [];
  if (t.warn !== undefined) parts.push(`Warnung ${word} ${NUM.format(t.warn)}`);
  if (t.crit !== undefined)
    parts.push(`${parts.length ? 'kritisch' : 'Kritisch'} ${word} ${NUM.format(t.crit)}`);
  return parts.join(', ');
}

/** "41 °C (Warnung ab 55, kritisch ab 60)" */
export function metricText(m: Metric): string {
  const value = formatValue(m.value, m.unit);
  const t = thresholdText(m.threshold);
  return t ? `${value} (${t})` : value;
}

const MINUTE = 60_000;

/** "seit 47 min", "seit 5 h", "seit 3 Tagen", older: "seit 12.10.2026". */
export function sinceText(iso: string, now: Date): string {
  const at = new Date(iso);
  const diff = now.getTime() - at.getTime();
  if (diff < MINUTE) return 'seit gerade eben';
  if (diff < 60 * MINUTE) return `seit ${Math.floor(diff / MINUTE)} min`;
  if (diff < 24 * 60 * MINUTE) return `seit ${Math.floor(diff / (60 * MINUTE))} h`;
  const days = Math.floor(diff / (24 * 60 * MINUTE));
  if (days < 30) return days === 1 ? 'seit 1 Tag' : `seit ${days} Tagen`;
  return `seit ${at.toLocaleDateString('de-DE', { timeZone: 'UTC' })}`;
}

export function dateText(iso: string): string {
  return new Date(iso).toLocaleString('de-DE', {
    timeZone: 'UTC',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** "prüfen, nicht bewerten · dieses Objekt · Grund: … · von kevin · dauerhaft · gilt nur bei 8 Sektoren" */
export function exceptionText(e: ExceptionInfo): string {
  const parts = e.ended ? [`erloschen (${e.ended})`] : [];
  parts.push(EFFECT_LABEL[e.effect], e.scope);
  if (e.reason) parts.push(`Grund: ${e.reason}`);
  parts.push(`von ${e.by}`);
  parts.push(e.window ?? (e.until ? `bis ${dateText(e.until)}` : 'dauerhaft'));
  if (e.condition) parts.push(e.condition);
  if (e.boundValue) parts.push(`gilt nur bei ${e.boundValue}`);
  return parts.join(' · ');
}

// The old reason format "field = value (op target)" is what the grammar replaces.
const OLD_REASON = /\b[a-z_]+ = .+\((eq|ne|lt|le|gt|ge|in|max_age|delta_gt|drop_pct_gt) /;
// A sentence end followed by a capitalised word: the reason is more than one sentence
// ("ca. 3 %" and "2.1" stay one sentence; common abbreviations are removed before the test).
const SECOND_SENTENCE = /[.!?]\s+[A-ZÄÖÜ]/;
const ABBREVIATION = /\b(z\.\s?B|d\.\s?h|u\.\s?a|bzw|ca|ggf|inkl|evtl|vgl|Nr)\./g;

/** "nicht ok seit 3 Tagen" when the object turned bad before its last status change, else null. */
export function badSinceText(o: MonObject, now: Date): string | null {
  if (!o.badSince || o.badSince === o.since) return null;
  return `nicht ok ${sinceText(o.badSince, now)}`;
}

/** Grammar violations of one object; empty when it follows the grammar. */
export function grammarViolations(o: MonObject): string[] {
  const out: string[] = [];
  if (!o.key) out.push('kein Schlüssel');
  if (o.identity.length === 0) out.push('keine Identitätszeile');
  if (!o.reason.trim()) out.push('kein Grund');
  if (SECOND_SENTENCE.test(o.reason.trim().replace(ABBREVIATION, '')))
    out.push('Grund hat mehr als einen Satz');
  if (OLD_REASON.test(o.reason)) out.push('Grund im alten Regelformat');
  if (Number.isNaN(new Date(o.since).getTime())) out.push('seit fehlt');
  if (o.badSince !== undefined) {
    if (o.status === 'ok') out.push('schlecht seit bei Status ok');
    if (!(new Date(o.badSince).getTime() <= new Date(o.since).getTime()))
      out.push('schlecht seit nach seit');
  }
  if (o.metrics.length > MAX_METRICS) out.push(`mehr als ${MAX_METRICS} Kennzahlen`);
  for (const m of o.metrics)
    if (m.threshold && m.threshold.warn === undefined && m.threshold.crit === undefined)
      out.push(`Kennzahl ${m.key}: Schwelle ohne Wert`);
  if (isHidden(o) && !o.exception?.by) out.push('Ausnahme ohne wer');
  return out;
}

/** Keys that occur more than once. */
export function duplicateKeys(list: readonly MonObject[]): string[] {
  const seen = new Set<string>();
  const dup = new Set<string>();
  for (const o of list) (seen.has(o.key) ? dup : seen).add(o.key);
  return [...dup];
}

/** Kind and name, without saying the kind twice when the name is the kind ("CPU", not "CPU CPU"). */
export function objectLabel(o: Pick<MonObject, 'kind' | 'name'>): string {
  const kind = KIND_LABEL[o.kind];
  return o.name.toLocaleLowerCase('de') === kind.toLocaleLowerCase('de')
    ? kind
    : `${kind} ${o.name}`;
}

export interface MeterScale {
  /** Positions in percent of the bar: the value, and where warning and critical start. */
  fill: number;
  warn?: number;
  crit?: number;
}

/** Where a numeric metric sits against its threshold; null for values a bar cannot show. A
 * percentage runs to 100, anything else a quarter past the larger of value and threshold. */
export function meterOf(m: Metric): MeterScale | null {
  const t = m.threshold;
  if (typeof m.value !== 'number' || !t || (t.warn === undefined && t.crit === undefined)) {
    return null;
  }
  const max = m.unit === '%' ? 100 : Math.max(m.value, t.warn ?? 0, t.crit ?? 0) * 1.25;
  if (max <= 0) return null;
  const at = (v: number): number => Math.min(100, Math.max(0, (v / max) * 100));
  return {
    fill: at(m.value),
    warn: t.warn === undefined ? undefined : at(t.warn),
    crit: t.crit === undefined ? undefined : at(t.crit),
  };
}
