// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Narrowing for a check's state.details: the monitoring service stores what the
// checker wrote, and a check switched to another type keeps the details of its
// old type until the next push. Each function reads the form of one checker; a
// field of the wrong type counts as missing, a list item without its required
// fields is dropped, valid data comes back unchanged.

import type {
  MonitorContainerDetails,
  MonitorForecastDetails,
  MonitorResourceDetails,
  MonitorResourceDisk,
  MonitorResourceTemp,
  MonitorServiceDetails,
  MonitorSmartDetails,
  MonitorZfsDetails,
} from '$lib/api/types';

type Reader<T> = (v: unknown) => T | undefined;
type Shape<T> = { [K in keyof T]-?: Reader<Exclude<T[K], undefined>> };

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

const str: Reader<string> = (v) => (typeof v === 'string' ? v : undefined);
const num: Reader<number> = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : undefined);
const bool: Reader<boolean> = (v) => (typeof v === 'boolean' ? v : undefined);

// A value set (category, state, mode) passes as any string: a newer server may
// send a value this UI does not know yet, and the sections show it neutrally.
function label<T extends string>(): Reader<T> {
  return str as Reader<T>;
}

function nullable<T>(read: Reader<T>): Reader<T | null> {
  return (v) => (v === null ? null : read(v));
}

function listOf<T>(read: Reader<T>): Reader<T[]> {
  return (v) => (Array.isArray(v) ? v.map(read).filter((x): x is T => x !== undefined) : undefined);
}

function recordOf<T>(read: Reader<T>): Reader<Record<string, T>> {
  return (v) => {
    if (!isObject(v)) return undefined;
    const out: Record<string, T> = {};
    for (const [k, x] of Object.entries(v)) {
      const r = read(x);
      if (r !== undefined) out[k] = r;
    }
    return out;
  };
}

function shape<T>(fields: Shape<T>, required: (keyof T)[] = []): Reader<T> {
  return (v) => {
    if (!isObject(v)) return undefined;
    const out: Partial<T> = {};
    for (const k of Object.keys(fields) as (keyof T)[]) {
      const r = fields[k](v[k as string]);
      if (r !== undefined) out[k] = r as T[keyof T];
      else if (required.includes(k)) return undefined;
    }
    return out as T;
  };
}

function details<T>(read: Reader<T>): (v: unknown) => T | null {
  return (v) => read(v) ?? null;
}

export const resourceDetails = details(
  shape<MonitorResourceDetails>({
    cpu: nullable(num),
    memory: nullable(num),
    memory_used_mb: num,
    memory_total_mb: num,
    swap: nullable(num),
    swap_total_mb: nullable(num),
    swap_used_mb: nullable(num),
    cpu_count: nullable(num),
    load_per_cpu: nullable(num),
    load_rated: bool,
    problems: recordOf(label<'warning' | 'critical'>()),
    disks: listOf(
      shape<MonitorResourceDisk>(
        {
          mount: str,
          percent: num,
          used_gb: num,
          total_gb: num,
          free_gb: nullable(num),
          inodes_percent: nullable(num),
          ignored: bool,
        },
        ['mount', 'percent'],
      ),
    ),
    temperatures: listOf(
      shape<MonitorResourceTemp>({ sensor: str, temp_c: num, high: num, critical: num }, [
        'sensor',
        'temp_c',
        'high',
        'critical',
      ]),
    ),
  }),
);

type Watched = NonNullable<MonitorServiceDetails['watched']>[number];

export const serviceDetails = details(
  shape<MonitorServiceDetails>({
    mode: label<'auto' | 'list'>(),
    failed: listOf(str),
    enabled_inactive: listOf(str),
    active_count: num,
    total: num,
    watched: listOf(
      shape<Watched>({ name: str, state: label<NonNullable<Watched['state']>>(), running: bool }, [
        'name',
      ]),
    ),
  }),
);

type Container = NonNullable<MonitorContainerDetails['containers']>[number];

export const containerDetails = details(
  shape<MonitorContainerDetails>({
    available: bool,
    error: nullable(str),
    containers: listOf(
      shape<Container>(
        {
          id: nullable(str),
          name: str,
          image: str,
          state: str,
          category: label<Container['category']>(),
          reason: nullable(str),
          exit_code: nullable(num),
          restart_count: nullable(num),
        },
        ['name', 'state', 'category'],
      ),
    ),
  }),
);

type Pool = NonNullable<MonitorZfsDetails['pools']>[number];

export const zfsDetails = details(
  shape<MonitorZfsDetails>({
    available: bool,
    error: nullable(str),
    pools: listOf(
      shape<Pool>({ name: str, health: str, capacityPercent: num }, [
        'name',
        'health',
        'capacityPercent',
      ]),
    ),
  }),
);

type Disk = NonNullable<MonitorSmartDetails['disks']>[number];

// Without a disk the checker writes {absent: <reason code>} instead of disks.
export type SmartDetails = MonitorSmartDetails & { absent?: string };

export const smartDetails = details(
  shape<SmartDetails>({
    absent: str,
    disks: listOf(
      shape<Disk>(
        {
          device: str,
          kind: str,
          protocol: str,
          model: str,
          category: label<NonNullable<Disk['category']>>(),
          temp_c: num,
          temp_warn: num,
          temp_crit: num,
          power_on_hours: num,
          available_spare_pct: num,
          percentage_used: num,
          reallocated_sectors: num,
          pending_sectors: num,
          critical_warning_bits: listOf(str),
        },
        ['device'],
      ),
    ),
  }),
);

type Mount = NonNullable<MonitorForecastDetails['mounts']>[number];

export const forecastDetails = details(
  shape<MonitorForecastDetails>({
    mounts: listOf(
      shape<Mount>(
        {
          mount: str,
          percent: num,
          rate_pp_per_hour: num,
          hours_left: nullable(num),
          note: str,
        },
        ['mount'],
      ),
    ),
  }),
);
