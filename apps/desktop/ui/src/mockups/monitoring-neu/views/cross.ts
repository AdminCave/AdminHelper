// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The cross views of Konzept §5: tables over all servers, built from the same object list as every
// other view. The first column (Zustand with reason and since) is the CrossView's own; the columns
// here only pick values the objects already carry, they never rate anything.

import type { Metric, MonObject, Status } from '../model';
import { byPlace, formatValue, isHidden, metricText, sortObjects, statusRank } from '../grammar';
import {
  BY_STATE,
  type Dir,
  type Sort,
  type SortValue,
  forecastValue,
  percentValue,
  sameSort,
  sizeValue,
  sortBy,
} from './sorting';

export interface Cell {
  text: string;
  sub?: string;
  status?: Status;
  mono?: boolean;
  /** The agent does not deliver this value yet. */
  newData?: boolean;
  /** What the column sorts by, where the text alone would sort wrong (a number, a size). */
  sort?: SortValue;
}

export interface Column {
  key: string;
  title: string;
  /** The direction of the first click: numbers where more is worse start with the largest. */
  first?: Dir;
}

export interface CrossRow {
  /** The object a click opens, and whose status the Zustand column shows. */
  object: MonObject;
  cells: Cell[];
}

export interface CrossView {
  id: string;
  title: string;
  /** What the view lists and how it sorts, one line above the table. */
  hint: string;
  columns: Column[];
  rows: (all: readonly MonObject[]) => CrossRow[];
  /** The order `rows` delivers, when it is not worst first. */
  defaultSort?: Sort;
}

export const NONE: Cell = { text: '–' };

function metric(o: MonObject, key: string): Metric | undefined {
  return o.metrics.find((m) => m.key === key);
}

function attr(o: MonObject, key: string): string | undefined {
  return o.attributes?.find((a) => a.key === key)?.value;
}

/** A metric as a cell: value (with its threshold where the view shows it), note below. */
function mcell(o: MonObject, key: string, withThreshold = false): Cell {
  const m = metric(o, key);
  if (!m) return NONE;
  return {
    text: withThreshold ? metricText(m) : formatValue(m.value, m.unit),
    sub: m.note,
    status: m.status,
    newData: m.newData,
    sort: typeof m.value === 'number' ? m.value : sizeValue(m.value),
  };
}

function acell(o: MonObject, key: string, mono = false): Cell {
  const v = attr(o, key);
  return v === undefined ? NONE : { text: v, mono };
}

function worst(statuses: (Status | undefined)[]): Status | undefined {
  const set = statuses.filter((s): s is Status => s !== undefined);
  return set.length ? set.sort((a, b) => statusRank(a) - statusRank(b))[0] : undefined;
}

/** The newest problem in the object's history. */
function lastError(o: MonObject): Cell {
  const h = o.history?.find((e) => e.status === 'critical' || e.status === 'warning');
  return h ? { text: h.text, status: h.status } : NONE;
}

/** Rows in the order of their objects: worst first, hidden ones at the end. */
function sortRows(rows: CrossRow[]): CrossRow[] {
  const order = new Map(sortObjects(rows.map((r) => r.object)).map((o, i) => [o.key, i]));
  return [...rows].sort((a, b) => order.get(a.object.key)! - order.get(b.object.key)!);
}

/** The value a column sorts by: the cell's own sort value, else its text. */
export function cellValue(c: Cell): SortValue {
  return 'sort' in c ? c.sort : c.text;
}

export function defaultSort(v: CrossView): Sort {
  return v.defaultSort ?? BY_STATE;
}

/** The rows of a view in the chosen order; the view's default keeps the order `rows` delivers.
 * The Zustand column sorts by status, every other one by its cells. */
export function orderRows(v: CrossView, rows: CrossRow[], sort: Sort): CrossRow[] {
  if (sameSort(sort, defaultSort(v))) return rows;
  const i = v.columns.findIndex((c) => c.key === sort.col);
  return sortBy(
    rows,
    (r) => (i < 0 ? statusRank(r.object.status) : cellValue(r.cells[i])),
    sort.dir,
    { hidden: (r) => isHidden(r.object), tie: (a, b) => byPlace(a.object, b.object) },
  );
}

function rowsOf(
  all: readonly MonObject[],
  pick: (o: MonObject) => boolean,
  cells: (o: MonObject) => Cell[],
): CrossRow[] {
  return sortObjects(all.filter(pick)).map((o) => ({ object: o, cells: cells(o) }));
}

const DEFECTS = ['realloc', 'pending', 'media', 'uncorrectable', 'grown', 'uncorrected'];

const disks: CrossView = {
  id: 'disks',
  title: 'Platten',
  hint: 'Alle Platten mit SMART-Werten, schlechteste zuerst',
  columns: [
    { key: 'place', title: 'Server / Ort / Pool' },
    { key: 'model', title: 'Modell' },
    { key: 'serial', title: 'Seriennummer' },
    { key: 'class', title: 'Klasse' },
    { key: 'capacity', title: 'Kapazität', first: 'desc' },
    { key: 'temp', title: 'Temperatur', first: 'desc' },
    { key: 'wear', title: 'Verschleiß', first: 'desc' },
    { key: 'defects', title: 'Defektzähler', first: 'desc' },
    { key: 'age', title: 'Betriebsalter', first: 'desc' },
  ],
  rows: (all) =>
    rowsOf(
      all,
      (o) => o.kind === 'disk',
      (o) => {
        const pool = o.identity.find((s) => s.startsWith('Pool '));
        const defects = o.metrics.filter((m) => DEFECTS.includes(m.key));
        const hours = metric(o, 'hours');
        const spare = metric(o, 'spare');
        return [
          {
            text: o.server,
            sub: [pool, attr(o, 'Gerät')].filter(Boolean).join(' · ') || undefined,
          },
          acell(o, 'Modell'),
          acell(o, 'Seriennummer', true),
          acell(o, 'Klasse'),
          attr(o, 'Kapazität')
            ? { ...acell(o, 'Kapazität'), sort: sizeValue(attr(o, 'Kapazität')) }
            : NONE,
          mcell(o, 'temp', true),
          metric(o, 'wear')
            ? {
                ...mcell(o, 'wear'),
                sub: spare ? `Reserve ${formatValue(spare.value, spare.unit)}` : undefined,
              }
            : NONE,
          defects.length
            ? {
                text: defects.map((m) => `${m.label} ${formatValue(m.value, m.unit)}`).join(' · '),
                sub: defects.find((m) => m.note)?.note,
                status: worst(defects.map((m) => m.status)),
                sort: defects.reduce((n, m) => n + (typeof m.value === 'number' ? m.value : 0), 0),
              }
            : NONE,
          hours
            ? {
                text: hours.note ?? formatValue(hours.value, hours.unit),
                sub: formatValue(hours.value, hours.unit),
                sort: hours.value,
              }
            : NONE,
        ];
      },
    ),
};

// A backup job names schedule and target in one identity line ("täglich 02:00 → pbs-store").
function jobPlan(o: MonObject): [string, string] | undefined {
  const line = o.identity.find((s) => s.includes(' → '));
  const [when, where] = line?.split(' → ') ?? [];
  return when && where ? [when, where] : undefined;
}

function backupCells(o: MonObject): Cell[] {
  if (o.kind === 'guest-backup') {
    const storage = metric(o, 'storage');
    return [
      { text: `${attr(o, 'Cluster')} / ${attr(o, 'Node')}` },
      { text: o.name, sub: o.identity[0] },
      // Never backed up is the oldest backup there is.
      metric(o, 'age')?.value === 'nie'
        ? { ...mcell(o, 'age', true), sort: Infinity }
        : mcell(o, 'age', true),
      mcell(o, 'size'),
      { text: storage ? formatValue(storage.value) : '–' },
      mcell(o, 'job'),
      storage?.note ? { text: storage.note, status: storage.status } : NONE,
      lastError(o),
    ];
  }
  if (o.kind === 'backup-job') {
    const plan = jobPlan(o);
    const errors = metric(o, 'errors');
    const cluster = o.identity.find((s) => s.startsWith('Cluster '))?.slice('Cluster '.length);
    return [
      { text: `${cluster ?? '–'} / ${o.server}` },
      { text: o.name, sub: o.identity[0] },
      NONE,
      NONE,
      plan ? { text: plan[1] } : NONE,
      plan ? { text: plan[0] } : NONE,
      NONE,
      errors && typeof errors.value === 'number' && errors.value > 0
        ? { text: `${errors.value} Fehler`, sub: errors.note, status: errors.status }
        : lastError(o),
    ];
  }
  // A backup module: its instance or one of its named parts (a client, a repository).
  const storage = metric(o, 'storage');
  return [
    { text: o.server },
    { text: o.name, sub: o.identity[0] },
    mcell(o, 'age', true),
    NONE,
    storage ? { text: formatValue(storage.value, storage.unit), sub: storage.label } : NONE,
    NONE,
    NONE,
    lastError(o),
  ];
}

const backups: CrossView = {
  id: 'backups',
  title: 'Backups',
  hint: 'Proxmox-Gäste, Backup-Jobs und Backup-Module zusammen, schlechteste zuerst',
  columns: [
    { key: 'place', title: 'Cluster / Node' },
    { key: 'what', title: 'Gast bzw. Job' },
    { key: 'last', title: 'Letztes Backup', first: 'desc' },
    { key: 'size', title: 'Größe + Trend', first: 'desc' },
    { key: 'storage', title: 'Ablage' },
    { key: 'schedule', title: 'Zeitplan' },
    { key: 'verify', title: 'Verifizierung' },
    { key: 'error', title: 'Letzter Fehler' },
  ],
  rows: (all) =>
    rowsOf(
      all,
      (o) => o.kind === 'guest-backup' || o.kind === 'backup-job' || o.family === 'Backup-Module',
      backupCells,
    ),
};

const pools: CrossView = {
  id: 'pools',
  title: 'Pools',
  hint: 'Alle ZFS-Pools, schlechteste zuerst',
  columns: [
    { key: 'server', title: 'Server' },
    { key: 'pool', title: 'Pool' },
    { key: 'used', title: 'Belegung', first: 'desc' },
    { key: 'scrub', title: 'Letzter Scrub', first: 'desc' },
    { key: 'errors', title: 'Gerätefehler', first: 'desc' },
    { key: 'layout', title: 'Layout' },
    { key: 'frag', title: 'Fragmentierung', first: 'desc' },
  ],
  rows: (all) =>
    rowsOf(
      all,
      (o) => o.kind === 'pool',
      (o) => [
        { text: o.server },
        { text: o.name, mono: true },
        mcell(o, 'used', true),
        mcell(o, 'scrub', true),
        mcell(o, 'errors'),
        acell(o, 'Layout'),
        { ...acell(o, 'Fragmentierung'), sort: percentValue(attr(o, 'Fragmentierung')) },
      ],
    ),
};

const containers: CrossView = {
  id: 'containers',
  title: 'Container',
  hint: 'Alle Container, schlechteste zuerst; seit steht beim Zustand',
  columns: [
    { key: 'server', title: 'Server' },
    { key: 'project', title: 'Projekt / Dienst' },
    { key: 'image', title: 'Image' },
    { key: 'health', title: 'Health' },
    { key: 'restarts', title: 'Neustarts 24 h', first: 'desc' },
    { key: 'ports', title: 'Ports' },
  ],
  rows: (all) =>
    rowsOf(
      all,
      (o) => o.kind === 'container',
      (o) => {
        const compose = o.identity.find((s) => s.startsWith('Compose '));
        return [
          { text: o.server },
          compose
            ? { text: compose.slice('Compose '.length), sub: o.name }
            : { text: o.name, sub: 'ohne Compose' },
          { ...mcell(o, 'image'), mono: true },
          mcell(o, 'health'),
          mcell(o, 'restarts'),
          acell(o, 'Ports', true),
        ];
      },
    ),
};

const certificates: CrossView = {
  id: 'certificates',
  title: 'Zertifikate',
  hint: 'Ein Zertifikat je Fingerabdruck, mit allen Stellen, an denen es gefunden wurde',
  columns: [
    { key: 'name', title: 'Name / SAN' },
    { key: 'expiry', title: 'Ablauf' },
    { key: 'issuer', title: 'Aussteller' },
    { key: 'sources', title: 'Quellen' },
  ],
  rows: (all) =>
    rowsOf(
      all,
      (o) => o.kind === 'certificate',
      (o) => {
        const name = metric(o, 'name');
        return [
          { text: o.name, sub: name ? String(name.value) : undefined, status: name?.status },
          mcell(o, 'days'),
          mcell(o, 'issuer'),
          acell(o, 'Quellen'),
        ];
      },
    ),
};

function updateRow(server: string, objects: MonObject[], host?: MonObject): CrossRow {
  const updates = objects.find((o) => o.kind === 'updates');
  const reboot = objects.find((o) => o.kind === 'reboot');
  const security = updates ? metric(updates, 'security') : undefined;
  const pending = updates ? metric(updates, 'pending') : undefined;
  let rebootCell: Cell = NONE;
  if (reboot?.status === 'not-collected') rebootCell = { text: 'nicht erhoben', sort: undefined };
  else if (reboot && metric(reboot, 'since'))
    rebootCell = { ...mcell(reboot, 'since'), text: `seit ${mcell(reboot, 'since').text}` };
  else if (reboot) rebootCell = { text: 'nicht nötig', sort: 0 };
  const uptimeOf = [reboot, host].find((o) => o && metric(o, 'uptime'));
  return {
    object: sortObjects(objects)[0],
    cells: [
      { text: server },
      security
        ? {
            text: formatValue(security.value, security.unit),
            sub: pending ? `${formatValue(pending.value)} ausstehend gesamt` : security.label,
            status: security.status,
            sort: security.value,
          }
        : NONE,
      updates ? mcell(updates, 'lists') : NONE,
      rebootCell,
      uptimeOf ? mcell(uptimeOf, 'uptime') : NONE,
    ],
  };
}

const updates: CrossView = {
  id: 'updates',
  title: 'Updates & Neustart',
  hint: 'Eine Zeile je Server; Quellen Agent, windows-host, proxmox-ve und pkg audit',
  columns: [
    { key: 'server', title: 'Server' },
    { key: 'security', title: 'Sicherheitsupdates', first: 'desc' },
    { key: 'lists', title: 'Paketlisten-Alter', first: 'desc' },
    { key: 'reboot', title: 'Neustart nötig seit', first: 'desc' },
    { key: 'uptime', title: 'Uptime', first: 'desc' },
  ],
  rows: (all) => {
    const byServer = new Map<string, MonObject[]>();
    for (const o of all)
      if (o.kind === 'updates' || o.kind === 'reboot')
        byServer.set(o.server, [...(byServer.get(o.server) ?? []), o]);
    const hosts = new Map(all.filter((o) => o.kind === 'host').map((o) => [o.server, o]));
    return sortRows(
      [...byServer].map(([server, objects]) => updateRow(server, objects, hosts.get(server))),
    );
  },
};

function usedPct(o: MonObject): number {
  const v = metric(o, 'used')?.value;
  return typeof v === 'number' ? v : -1;
}

const mounts: CrossView = {
  id: 'mounts',
  title: 'Mounts',
  hint: 'Vollste zuerst; die Schwelle in Prozent zählt erst unter 20 GB frei',
  columns: [
    { key: 'server', title: 'Server' },
    { key: 'path', title: 'Pfad' },
    { key: 'used', title: 'Belegt / frei', first: 'desc' },
    { key: 'forecast', title: 'Prognose' },
  ],
  defaultSort: { col: 'used', dir: 'desc' },
  rows: (all) => {
    const list = all.filter((o) => o.kind === 'mount');
    const shown = list.filter((o) => !isHidden(o)).sort((a, b) => usedPct(b) - usedPct(a));
    return [...shown, ...list.filter(isHidden)].map((o) => {
      const free = metric(o, 'free');
      const used = mcell(o, 'used', true);
      const freeText = free ? `${formatValue(free.value, free.unit)} frei` : undefined;
      return {
        object: o,
        cells: [
          { text: o.server },
          { text: o.name, mono: true, sub: o.identity[0] },
          { ...used, sub: [freeText, used.sub].filter(Boolean).join(' · ') || undefined },
          { ...mcell(o, 'forecast'), sort: forecastValue(metric(o, 'forecast')?.value as string) },
        ],
      };
    });
  },
};

const services: CrossView = {
  id: 'services',
  title: 'Dienste',
  hint: 'Nur Dienste, die nicht laufen wie erwartet, über alle Server',
  columns: [
    { key: 'server', title: 'Server' },
    { key: 'service', title: 'Dienst' },
    { key: 'restarts', title: 'Neustarts', first: 'desc' },
  ],
  rows: (all) =>
    rowsOf(
      all,
      (o) => o.kind === 'service' && o.status !== 'ok',
      (o) => [{ text: o.server }, { text: o.name, mono: true }, mcell(o, 'restarts')],
    ),
};

export const CROSS_VIEWS: CrossView[] = [
  disks,
  backups,
  pools,
  containers,
  certificates,
  updates,
  mounts,
  services,
];
