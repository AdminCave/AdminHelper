// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Pure helpers of the history charts (R-1076, R-1077): scale, statistics over the visible
// window, the linear disk forecast, value formatting and the CSV export. A series is one value
// per grid point of the monitoring history API; a missing sample is null.

export type Value = number | null;
export type ChartUnit = '%' | 'ms' | 'Mbit/s' | '';

export interface ChartSeries {
  key: string;
  label: string;
  color: string;
  data: Value[];
  dash?: string;
  area?: boolean;
  /** Drawn below the zero line (outgoing traffic on the mirrored axis). */
  neg?: boolean;
  hidden?: boolean;
  forecast?: boolean;
  /** The previous period on this period's grid. */
  prev?: Value[] | null;
}

export interface ChartThreshold {
  value: number;
  status: string;
  label: string;
}

/** A status change at `at` (unix seconds). */
export interface ChartEvent {
  at: number;
  status: string;
  label: string;
}

/** A maintenance window from `start` to `end` (unix seconds). */
export interface ChartBand {
  start: number;
  end: number;
  label: string;
}

export interface SeriesStats {
  avg: number;
  p95: number;
  max: number;
  cur: number;
}

/** The axis maximum: m rounded up to 1, 2, 2.5 or 5 times a power of ten. */
export function niceMax(m: number): number {
  if (!(m > 0) || !Number.isFinite(m)) return 1;
  const power = Math.pow(10, Math.floor(Math.log10(m)));
  const f = m / power;
  const step = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return step * power;
}

/** Average, 95th percentile, maximum and the last value of the indexes z0..z1; null without a value. */
export function stats(data: Value[], z0: number, z1: number): SeriesStats | null {
  const values = data
    .slice(Math.max(0, Math.floor(z0)), Math.ceil(z1) + 1)
    .filter((v): v is number => v != null);
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return {
    avg: values.reduce((a, b) => a + b, 0) / values.length,
    p95: sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))],
    max: sorted[sorted.length - 1],
    cur: values[values.length - 1],
  };
}

/** Least-squares slope per grid step over the non-null points; null below two points. */
export function linearSlope(data: Value[]): number | null {
  let n = 0;
  let sx = 0;
  let sy = 0;
  let sxy = 0;
  let sxx = 0;
  data.forEach((v, i) => {
    if (v == null) return;
    n += 1;
    sx += i;
    sy += v;
    sxy += i * v;
    sxx += i * i;
  });
  const denominator = n * sxx - sx * sx;
  if (n < 2 || denominator === 0) return null;
  return (n * sxy - sx * sy) / denominator;
}

/** Days until `current` reaches `full` at `slope` per step of `stepSeconds`; null when it does not grow. */
export function daysUntilFull(
  current: number,
  slope: number | null,
  stepSeconds: number,
  full = 100,
): number | null {
  if (slope == null || !(slope > 0)) return null;
  return (Math.max(0, full - current) / slope) * (stepSeconds / 86400);
}

/** `data`'s grid followed by `steps` forecast points: from the last value of `data`, placed at the
 * last grid point, `slope` per step, capped at `cap`. All null when `data` has no value. */
export function forecast(data: Value[], slope: number, steps: number, cap = 100): Value[] {
  if (data.length === 0) return Array<Value>(steps).fill(null);
  const last = data.length - 1;
  const out: Value[] = Array<Value>(Math.max(0, last)).fill(null);
  let v = [...data].reverse().find((x): x is number => x != null);
  if (v == null) return [...out, null, ...Array<Value>(steps).fill(null)];
  out.push(v);
  for (let i = 0; i < steps; i += 1) {
    v = Math.min(cap, v + Math.max(0, slope));
    out.push(v);
  }
  return out;
}

/** The fractional grid index of the unix time `at` on the uniform grid `times`. */
export function indexOfTime(times: number[], at: number): number {
  if (times.length < 2) return 0;
  return (at - times[0]) / (times[1] - times[0]);
}

export function formatValue(v: Value | undefined, unit: ChartUnit): string {
  if (v == null) return '—';
  if (unit === '%') return `${Math.round(v)} %`;
  if (unit === 'ms') return `${Math.round(v)} ms`;
  if (unit === 'Mbit/s') {
    const abs = Math.abs(v);
    return `${abs >= 100 ? Math.round(abs) : abs.toFixed(1)} Mbit/s`;
  }
  return v.toFixed(2);
}

export function formatAxis(v: number, unit: ChartUnit): string {
  if (unit === '%') return `${Math.round(v)}%`;
  if (unit === 'ms') return String(Math.round(v));
  if (unit === '') return v.toFixed(1);
  const abs = Math.abs(v);
  return abs >= 10 ? String(Math.round(abs)) : abs.toFixed(1);
}

/** An axis label: the date over 20 days, weekday and hour over two days, else the time of day. */
export function formatTick(at: number, spanSeconds: number, locale: string): string {
  const date = new Date(at * 1000);
  if (spanSeconds > 20 * 86400) {
    return date.toLocaleDateString(locale, { day: '2-digit', month: '2-digit' });
  }
  if (spanSeconds > 2 * 86400) {
    return date.toLocaleString(locale, { weekday: 'short', hour: '2-digit', minute: '2-digit' });
  }
  return date.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
}

export function formatTip(at: number, locale: string): string {
  return new Date(at * 1000).toLocaleString(locale, {
    weekday: 'short',
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// A spreadsheet runs a cell that starts with one of these as a formula; labels are check
// names and mount points from the servers, so they are quoted as text.
const FORMULA_START = /^[=+\-@\t\r]/;

function csvCell(text: string): string {
  const safe = FORMULA_START.test(text) ? `'${text}` : text;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

/** One row per grid time (ISO 8601, UTC), one column per series; a missing value is empty. */
export function toCsv(times: number[], columns: { label: string; data: Value[] }[]): string {
  const header = ['time', ...columns.map((c) => csvCell(c.label))].join(',');
  const rows = times.map((at, i) =>
    [
      new Date(at * 1000).toISOString(),
      ...columns.map((c) => {
        const v = c.data[i];
        return v == null ? '' : String(v);
      }),
    ].join(','),
  );
  return [header, ...rows].join('\n') + '\n';
}
