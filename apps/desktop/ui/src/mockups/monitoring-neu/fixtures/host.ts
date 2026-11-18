// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Host and operating-system fixtures (Konzept §4.7–§4.12): agent liveness, CPU, memory, mounts
// with forecast, sensors, reboot, updates, clock and services. Thresholds follow the recommendation
// of open question 5 (CPU 90/95, RAM 90/98, Disk 80/90). While a host is silent its other objects
// are "veraltet"; a value the agent does not collect is "nicht erhoben", never ok.

import type {
  Attribute,
  Detail,
  ExceptionInfo,
  HistoryEvent,
  Kind,
  LogLine,
  Metric,
  MonObject,
  ProcessRow,
  RuleView,
  Status,
  Threshold,
  TrendPoint,
} from '../model';
import { DAY, HOUR, ago } from './time';

function metric(
  key: string,
  label: string,
  value: number | string,
  threshold: Threshold | null,
  extra: Partial<Metric> = {},
): Metric {
  return { key, label, value, threshold, ...extra };
}

function rule(key: string, text: string, level: RuleView['level']): RuleView {
  return { key, text, level, source: 'Katalog', enabled: true };
}

/** One point per hour, oldest first, ending now. */
function hourly(hours: number, value: (i: number) => number): TrendPoint[] {
  return Array.from({ length: hours }, (_, i) => ({
    at: ago((hours - 1 - i) * HOUR),
    value: value(i),
  }));
}

/** One point per day, oldest first, ending today. */
function daily(days: number, value: (i: number) => number): TrendPoint[] {
  return Array.from({ length: days }, (_, i) => ({
    at: ago((days - 1 - i) * DAY),
    value: value(i),
  }));
}

const CPU_LIMIT: Threshold = { warn: 90, crit: 95 };
const RAM_LIMIT: Threshold = { warn: 90, crit: 98 };
const DISK_LIMIT: Threshold = { warn: 80, crit: 90 };
const SILENT: Threshold = { crit: 15 };
const RESTARTS: Threshold = { warn: 5 };
const FORECAST_NOTE = 'Warnung unter 24 h, kritisch unter 8 h';
const STALE_REASON = 'Veraltet: letzte Werte von vor 47 min';

const RULES: Partial<Record<Kind, RuleView[]>> = {
  host: [
    rule('agent.silent', 'Keine Meldung seit 15 min', 'critical'),
    rule('agent.throttled', 'Lastschonung länger als 30 min', 'warning'),
    rule('agent.never', 'Nach der Einrichtung nie gemeldet, nach einer Frist', 'warning'),
  ],
  cpu: [
    rule(
      'cpu.usage',
      'Auslastung ab 90 % (kritisch ab 95 %), Entwarnung 10 Punkte darunter',
      'warning',
    ),
    rule('cpu.load', 'Last je CPU ab 1,5', 'warning'),
  ],
  memory: [
    rule('mem.used', 'Belegt ab 90 % (kritisch ab 98 %), Entwarnung 10 Punkte darunter', 'warning'),
    rule('mem.oom', 'Kernel beendet einen Prozess (OOM), bis zur Quittung', 'warning'),
  ],
  mount: [
    rule('mount.used', 'Belegt ab 80 % (kritisch ab 90 %), zählt erst unter 20 GB frei', 'warning'),
    rule(
      'mount.forecast',
      'Voll in unter 24 h (kritisch unter 8 h), Entwarnung über 36 h',
      'warning',
    ),
  ],
  sensor: [rule('sensor.temp', 'Temperatur ab 80 °C (kritisch ab 95 °C)', 'warning')],
  reboot: [rule('reboot.required', 'Neustart nötig', 'warning')],
  updates: [rule('updates.security', 'Sicherheitsupdates ab 1', 'warning')],
  clock: [rule('clock.sync', 'Uhr nicht synchronisiert (erst ab 15 min Uptime)', 'warning')],
  service: [
    rule('service.failed', 'Dienst fehlgeschlagen', 'critical'),
    rule('service.restarts', 'Neustart-Schleife: ab 5 Neustarts je Stunde', 'warning'),
  ],
};

interface Spec {
  kind: Kind;
  server: string;
  /** Key part after the server; defaults to the kind. */
  id?: string;
  name: string;
  identity: string[];
  status: Status;
  reason: string;
  since: string;
  badSince?: string;
  metrics: Metric[];
  attributes?: Attribute[];
  details?: Detail[];
  history?: HistoryEvent[];
  firing?: string[];
  exception?: ExceptionInfo;
  raw?: string;
}

function obj(s: Spec): MonObject {
  return {
    key: `${s.server}/${s.id ?? s.kind}`,
    kind: s.kind,
    name: s.name,
    server: s.server,
    identity: s.identity,
    status: s.status,
    reason: s.reason,
    since: s.since,
    badSince: s.badSince,
    metrics: s.metrics,
    attributes: s.attributes,
    details: s.details,
    history: s.history,
    rules: (RULES[s.kind] ?? []).map((r) => ({ ...r, firing: (s.firing ?? []).includes(r.key) })),
    exception: s.exception,
    raw: s.raw,
  };
}

const lastReport = (min: number, extra: Partial<Metric> = {}) =>
  metric('last', 'Letzte Meldung', min, SILENT, { unit: 'min', ...extra });
const agentVersion = (v: string) => metric('version', 'Agent-Version', v, null, { newData: true });
const uptime = (days: number, extra: Partial<Metric> = {}) =>
  metric('uptime', 'Uptime', days, null, { unit: days === 1 ? 'Tag' : 'Tage', ...extra });
const usedPct = (v: number, limit: Threshold, extra: Partial<Metric> = {}) =>
  metric('used', 'Belegt', v, limit, { unit: '%', ...extra });

function log(at: number, source: string, priority: LogLine['priority'], text: string): LogLine {
  return { at: ago(at), source, priority, text };
}

const DB_PROCESSES: ProcessRow[] = [
  { pid: 48211, name: 'postgres', user: 'postgres', cpu: 71.4, memMb: 9812 },
  { pid: 48230, name: 'postgres', user: 'postgres', cpu: 18.2, memMb: 1630 },
  { pid: 1022, name: 'pgbouncer', user: 'postgres', cpu: 6.1, memMb: 18 },
  { pid: 877, name: 'adminhelper-agent', user: 'root', cpu: 0.4, memMb: 31 },
  { pid: 1, name: 'systemd', user: 'root', cpu: 0.1, memMb: 12 },
];

// ---------------------------------------------------------------------------------------------
// host (§4.8)

const HOSTS: MonObject[] = [
  obj({
    kind: 'host',
    server: 'web-01',
    name: 'web-01',
    identity: ['Debian 13', '198.51.100.21'],
    status: 'ok',
    reason: 'Meldet sich regelmäßig',
    since: ago(3 * DAY),
    metrics: [
      lastReport(1),
      uptime(41),
      metric('throttle', 'Lastschonung', 0, { warn: 30 }, { unit: 'min' }),
      agentVersion('0.47.0'),
    ],
    attributes: [
      { key: 'Betriebssystem', value: 'Debian 13 (trixie)' },
      { key: 'Kernel', value: '6.12.57+deb13-amd64', mono: true },
      { key: 'Adresse', value: '198.51.100.21', mono: true },
      { key: 'Kerne', value: '4' },
      { key: 'Arbeitsspeicher', value: '16 GB' },
    ],
    details: [
      {
        type: 'trend',
        title: 'Abstand der Meldungen, 24 h',
        unit: 'min',
        threshold: SILENT,
        points: hourly(24, (i) => [1, 1, 2, 1][i % 4]),
      },
    ],
    history: [
      { at: ago(3 * DAY), status: 'ok', text: 'meldet sich wieder nach 22 min' },
      { at: ago(3 * DAY + 7), status: 'critical', text: '15 min ohne Meldung' },
    ],
  }),
  obj({
    kind: 'host',
    server: 'app-01',
    name: 'app-01',
    identity: ['Ubuntu 26.04', '198.51.100.24'],
    status: 'critical',
    reason: 'Meldet sich nicht seit 47 min',
    since: ago(32),
    metrics: [
      lastReport(47, { status: 'critical' }),
      uptime(12, { note: 'Stand vor 47 min' }),
      agentVersion('0.46.2'),
    ],
    details: [
      {
        type: 'trend',
        title: 'Abstand der Meldungen, 24 h',
        unit: 'min',
        threshold: SILENT,
        points: hourly(24, (i) => (i < 23 ? 1 : 47)),
      },
      {
        type: 'note',
        title: 'Folgen für die Objekte des Hosts',
        text: 'Solange der Host still ist, gelten seine übrigen Objekte als veraltet: sie öffnen keine neuen Probleme und melden nichts, bis er sich wieder meldet.',
      },
    ],
    firing: ['agent.silent'],
    history: [{ at: ago(32), status: 'critical', text: '15 min ohne Meldung' }],
  }),
  obj({
    kind: 'host',
    server: 'test-01',
    name: 'test-01',
    identity: ['eingerichtet über Enrollment', '192.0.2.60'],
    status: 'unknown',
    reason: 'Noch nie gemeldet',
    since: ago(20),
    metrics: [
      metric('first', 'Erste Meldung', 'ausstehend', null),
      metric('created', 'Eingerichtet vor', 20, null, {
        unit: 'min',
        note: 'nach einer Frist ein Problem',
      }),
    ],
  }),
  obj({
    kind: 'host',
    server: 'db-01',
    name: 'db-01',
    identity: ['Debian 13', '198.51.100.31'],
    status: 'warning',
    reason: 'Lastschonung aktiv: der Agent sammelt seltener',
    since: ago(12),
    metrics: [
      lastReport(1),
      uptime(12),
      metric('throttle', 'Lastschonung', 42, { warn: 30 }, { unit: 'min', status: 'warning' }),
      agentVersion('0.47.0'),
    ],
    firing: ['agent.throttled'],
    history: [{ at: ago(12), status: 'warning', text: 'Lastschonung länger als 30 min' }],
  }),
];

// ---------------------------------------------------------------------------------------------
// cpu, memory, mount, sensor (§4.9, §4.11)

const RESOURCES: MonObject[] = [
  obj({
    kind: 'cpu',
    server: 'web-01',
    name: 'CPU',
    identity: ['4 Kerne', 'Intel Xeon E-2334'],
    status: 'ok',
    reason: 'Im Rahmen',
    since: ago(9 * DAY),
    metrics: [
      metric('usage', 'Auslastung', 37, CPU_LIMIT, { unit: '%' }),
      metric('load', 'Last', 0.8, { warn: 1.5 }, { unit: 'je CPU' }),
    ],
    details: [
      {
        type: 'trend',
        title: 'Auslastung, 24 h',
        unit: '%',
        threshold: CPU_LIMIT,
        points: hourly(24, (i) => 22 + ((i * 11 + 15) % 23)),
      },
    ],
  }),
  obj({
    kind: 'cpu',
    server: 'db-01',
    name: 'CPU',
    identity: ['8 Kerne', 'AMD EPYC 4244P'],
    status: 'warning',
    reason: 'Hohe Last: 2,1 je CPU',
    since: ago(25),
    metrics: [
      metric('usage', 'Auslastung', 88, CPU_LIMIT, { unit: '%' }),
      metric('load', 'Last', 2.1, { warn: 1.5 }, { unit: 'je CPU', status: 'warning' }),
    ],
    details: [
      {
        type: 'processes',
        title: 'Top-Prozesse',
        sortedBy: 'cpu',
        rows: DB_PROCESSES,
        newData: true,
      },
    ],
    firing: ['cpu.load'],
  }),
  obj({
    kind: 'memory',
    server: 'web-01',
    name: 'Arbeitsspeicher',
    identity: ['16 GB'],
    status: 'ok',
    reason: 'Im Rahmen',
    since: ago(9 * DAY),
    metrics: [
      usedPct(72, RAM_LIMIT, { note: '11,5 von 16 GB' }),
      metric('swap', 'Swap', 0, null, { unit: '%' }),
      metric('oom', 'OOM-Kills (24 h)', 0, { warn: 1 }),
    ],
  }),
  obj({
    kind: 'memory',
    server: 'db-01',
    name: 'Arbeitsspeicher',
    identity: ['32 GB'],
    status: 'warning',
    reason: 'Speicher erschöpft: der Kernel beendete postgres',
    since: ago(3 * HOUR),
    metrics: [
      usedPct(93, RAM_LIMIT, { status: 'warning', note: '29,8 von 32 GB' }),
      metric('swap', 'Swap', 41, null, { unit: '%' }),
      metric('oom', 'OOM-Kills (24 h)', 1, { warn: 1 }, { status: 'warning' }),
    ],
    details: [
      {
        type: 'log',
        title: 'Kernel-Meldungen',
        lines: [
          log(3 * HOUR + 1, 'kernel', 'warning', 'postgres invoked oom-killer: gfp_mask=0x140cca'),
          log(
            3 * HOUR,
            'kernel',
            'err',
            'Out of memory: Killed process 47102 (postgres) total-vm:10412204kB, anon-rss:9940312kB',
          ),
          log(
            3 * HOUR,
            'postgresql@17-main',
            'err',
            'server process (PID 47102) was terminated by signal 9: Killed',
          ),
          log(
            3 * HOUR - 1,
            'postgresql@17-main',
            'notice',
            'all server processes terminated; reinitializing',
          ),
        ],
        more: 'journalctl -k --since "-6h"',
      },
      {
        type: 'processes',
        title: 'Top-Prozesse',
        sortedBy: 'mem',
        rows: [...DB_PROCESSES].sort((a, b) => b.memMb - a.memMb),
        newData: true,
      },
    ],
    firing: ['mem.used', 'mem.oom'],
    history: [{ at: ago(3 * HOUR), status: 'warning', text: 'OOM-Kill: postgres (PID 47102)' }],
  }),
  obj({
    kind: 'mount',
    server: 'web-01',
    id: 'mount/',
    name: '/',
    identity: ['/dev/vda1', 'ext4', '100 GB'],
    status: 'ok',
    reason: 'Genug Platz',
    since: ago(40 * DAY),
    metrics: [
      usedPct(41, DISK_LIMIT, { note: 'zählt erst unter 20 GB frei' }),
      metric('free', 'Frei', 59, null, { unit: 'GB' }),
      metric('inodes', 'Inodes', 12, null, { unit: '%' }),
      metric('forecast', 'Prognose', 'gleichbleibend', null, { note: FORECAST_NOTE }),
    ],
  }),
  obj({
    kind: 'mount',
    server: 'web-01',
    id: 'mount/var/log',
    name: '/var/log',
    identity: ['/dev/vdb1', 'ext4', '8 GB'],
    status: 'critical',
    reason: 'Voll: 0 GB frei',
    since: ago(11 * HOUR),
    badSince: ago(27 * HOUR),
    metrics: [
      usedPct(100, DISK_LIMIT, { status: 'critical' }),
      metric('free', 'Frei', 0, null, { unit: 'GB' }),
      metric('inodes', 'Inodes', 3, null, { unit: '%' }),
      metric('forecast', 'Prognose', 'voll', null, { status: 'critical' }),
    ],
    details: [
      {
        type: 'trend',
        title: 'Belegung, 24 h',
        unit: '%',
        threshold: DISK_LIMIT,
        points: hourly(24, (i) => Math.min(100, 62 + i * 2)),
      },
    ],
    firing: ['mount.used', 'mount.forecast'],
    history: [
      { at: ago(4 * HOUR), status: 'critical', text: 'voll' },
      { at: ago(11 * HOUR), status: 'critical', text: 'Prognose unter 8 h' },
      { at: ago(27 * HOUR), status: 'warning', text: 'Prognose unter 24 h' },
    ],
  }),
  obj({
    kind: 'mount',
    server: 'nas-01',
    id: 'mount/srv/data',
    name: '/srv/data',
    identity: ['tank/data', 'zfs', '13,6 TB'],
    status: 'ok',
    reason: 'Genug Platz: 412 GB frei',
    since: ago(60 * DAY),
    metrics: [
      usedPct(97, DISK_LIMIT, { note: 'zählt nicht: über 20 GB frei' }),
      metric('free', 'Frei', 412, null, { unit: 'GB' }),
      metric('forecast', 'Prognose', 'voll in ~140 Tagen', null, { note: FORECAST_NOTE }),
    ],
  }),
  obj({
    kind: 'mount',
    server: 'mail-01',
    id: 'mount/var',
    name: '/var',
    identity: ['/dev/sda3', 'ext4', '100 GB'],
    status: 'warning',
    reason: 'Wenig Platz: 14 GB frei',
    since: ago(3 * DAY),
    metrics: [
      usedPct(86, DISK_LIMIT, { status: 'warning', note: 'zählt erst unter 20 GB frei' }),
      metric('free', 'Frei', 14, null, { unit: 'GB' }),
      metric('inodes', 'Inodes', 31, null, { unit: '%' }),
      metric('forecast', 'Prognose', 'voll in ~9 Tagen', null, { note: FORECAST_NOTE }),
    ],
    details: [
      {
        type: 'trend',
        title: 'Belegung, 14 Tage, mit Prognose',
        unit: '%',
        threshold: DISK_LIMIT,
        points: daily(14, (i) => Math.round(66 + i * 1.55)),
        forecast: [{ at: ago(-9 * DAY), value: 100 }],
      },
    ],
    firing: ['mount.used'],
  }),
  obj({
    kind: 'mount',
    server: 'build-01',
    id: 'mount/var/lib/docker',
    name: '/var/lib/docker',
    identity: ['/dev/vdb1', 'xfs', '100 GB'],
    status: 'critical',
    reason: 'Voll in ~6 h',
    since: ago(HOUR),
    badSince: ago(17 * HOUR),
    metrics: [
      usedPct(88, DISK_LIMIT, { status: 'warning' }),
      metric('free', 'Frei', 12, null, { unit: 'GB' }),
      metric('inodes', 'Inodes', 9, null, { unit: '%' }),
      metric('forecast', 'Prognose', 'voll in ~6 h', null, {
        status: 'critical',
        note: FORECAST_NOTE,
      }),
    ],
    details: [
      {
        type: 'trend',
        title: 'Belegung, 24 h, mit Prognose',
        unit: '%',
        threshold: DISK_LIMIT,
        points: hourly(24, (i) => 42 + 2 * i),
        forecast: [{ at: ago(-6 * HOUR), value: 100 }],
      },
    ],
    firing: ['mount.used', 'mount.forecast'],
    history: [
      { at: ago(HOUR), status: 'critical', text: 'Prognose unter 8 h' },
      { at: ago(17 * HOUR), status: 'warning', text: 'Prognose unter 24 h' },
    ],
  }),
  obj({
    kind: 'sensor',
    server: 'pve-01',
    id: 'sensor/coretemp-isa-0000/temp1',
    name: 'Package id 0',
    identity: ['coretemp', 'CPU'],
    status: 'ok',
    reason: 'Im Rahmen',
    since: ago(30 * DAY),
    metrics: [
      metric('temp', 'Temperatur', 62, { warn: 80, crit: 95 }, { unit: '°C' }),
      metric('limit', 'Hardware-Grenze', 100, null, { unit: '°C', newData: true }),
    ],
  }),
  obj({
    kind: 'sensor',
    server: 'pve-02',
    id: 'sensor/k10temp-pci-00c3/temp1',
    name: 'Tctl',
    identity: ['k10temp', 'CPU'],
    status: 'warning',
    reason: 'Zu warm: 84 °C',
    since: ago(2 * HOUR),
    metrics: [
      metric(
        'temp',
        'Temperatur',
        84,
        { warn: 80, crit: 95 },
        { unit: '°C', status: 'warning', note: 'Entwarnung unter 70' },
      ),
      metric('limit', 'Hardware-Grenze', 'nicht gemeldet', null, { newData: true }),
    ],
    details: [
      {
        type: 'trend',
        title: 'Temperatur, 24 h',
        unit: '°C',
        threshold: { warn: 80, crit: 95 },
        points: hourly(24, (i) => (i < 20 ? 66 + (i % 5) : [79, 81, 83, 84][i - 20])),
      },
    ],
    firing: ['sensor.temp'],
    history: [{ at: ago(2 * HOUR), status: 'warning', text: '81 °C, ab 80' }],
  }),
];

// Objects of the silent host app-01: last known values, rated "veraltet" until it reports again.
const STALE: MonObject[] = [
  obj({
    kind: 'cpu',
    server: 'app-01',
    name: 'CPU',
    identity: ['4 Kerne'],
    status: 'stale',
    reason: STALE_REASON,
    since: ago(32),
    metrics: [
      metric('usage', 'Auslastung', 12, CPU_LIMIT, { unit: '%' }),
      metric('load', 'Last', 0.3, { warn: 1.5 }, { unit: 'je CPU' }),
    ],
  }),
  obj({
    kind: 'memory',
    server: 'app-01',
    name: 'Arbeitsspeicher',
    identity: ['8 GB'],
    status: 'stale',
    reason: STALE_REASON,
    since: ago(32),
    metrics: [usedPct(54, RAM_LIMIT, { note: '4,3 von 8 GB' })],
  }),
  obj({
    kind: 'mount',
    server: 'app-01',
    id: 'mount/',
    name: '/',
    identity: ['/dev/vda1', 'ext4', '40 GB'],
    status: 'stale',
    reason: STALE_REASON,
    since: ago(32),
    metrics: [
      usedPct(48, DISK_LIMIT, { note: 'zählt erst unter 20 GB frei' }),
      metric('free', 'Frei', 21, null, { unit: 'GB' }),
    ],
  }),
];

// ---------------------------------------------------------------------------------------------
// reboot, updates, clock (§4.10)

const SYSTEM: MonObject[] = [
  obj({
    kind: 'reboot',
    server: 'web-01',
    name: 'Neustart',
    identity: ['Debian 13'],
    status: 'warning',
    reason: 'Neustart nötig: neuer Kernel und libc6',
    since: ago(3 * DAY),
    metrics: [
      metric('since', 'Nötig seit', 3, null, { unit: 'Tagen', newData: true }),
      metric('by', 'Verlangt von', 2, null, {
        unit: 'Paketen',
        note: 'linux-image-amd64, libc6',
      }),
      uptime(41),
    ],
    firing: ['reboot.required'],
  }),
  obj({
    kind: 'reboot',
    server: 'db-01',
    name: 'Neustart',
    identity: ['Debian 13'],
    status: 'ok',
    reason: 'Kein Neustart nötig',
    since: ago(12 * DAY),
    metrics: [uptime(12)],
  }),
  obj({
    kind: 'reboot',
    server: 'dc-01',
    name: 'Neustart',
    identity: ['Windows Server 2025'],
    status: 'not-collected',
    reason: 'Nicht erhoben: der Windows-Agent prüft keinen ausstehenden Neustart',
    since: ago(30 * DAY),
    metrics: [],
  }),
  obj({
    kind: 'updates',
    server: 'web-01',
    name: 'Updates',
    identity: ['apt', 'Quelle: Agent'],
    status: 'warning',
    reason: '4 Sicherheitsupdates ausstehend',
    since: ago(2 * DAY),
    metrics: [
      metric('security', 'Sicherheitsupdates', 4, { warn: 1 }, { status: 'warning' }),
      metric('lists', 'Paketlisten-Alter', 2, null, { unit: 'Tage', newData: true }),
      metric('counted', 'Gezählt vor', 37, null, { unit: 'min' }),
    ],
    details: [
      {
        type: 'note',
        title: 'Ausstehende Pakete',
        text: 'openssl, libssl3t64, linux-image-amd64, libc6',
      },
    ],
    firing: ['updates.security'],
  }),
  obj({
    kind: 'updates',
    server: 'mail-01',
    name: 'Updates',
    identity: ['apt', 'Quelle: Agent'],
    status: 'unknown',
    reason: 'Paketlisten 9 Tage alt, die Zählung ist nicht belastbar',
    since: ago(2 * DAY),
    metrics: [
      metric('security', 'Sicherheitsupdates', 0, { warn: 1 }),
      metric('lists', 'Paketlisten-Alter', 9, null, {
        unit: 'Tage',
        status: 'unknown',
        note: 'über 7 Tage: Zählung unbekannt',
        newData: true,
      }),
      metric('counted', 'Gezählt vor', 41, null, { unit: 'min' }),
    ],
  }),
  obj({
    kind: 'updates',
    server: 'dc-01',
    name: 'Updates',
    identity: ['Windows Update', 'Quelle: Modul windows-host'],
    status: 'warning',
    reason: '2 Updates ausstehend, davon 1 Sicherheitsupdate',
    since: ago(4 * DAY),
    metrics: [
      metric('security', 'Sicherheitsupdates', 1, { warn: 1 }, { status: 'warning' }),
      metric('pending', 'Ausstehend gesamt', 2, null),
      metric('counted', 'Gezählt vor', 3, null, { unit: 'h' }),
    ],
    firing: ['updates.security'],
  }),
  obj({
    kind: 'updates',
    server: 'pve-01',
    name: 'Updates',
    identity: ['apt', 'Quelle: Modul proxmox-ve'],
    status: 'ok',
    reason: '4 Updates ausstehend, keine Sicherheitsupdates',
    since: ago(6 * DAY),
    metrics: [
      metric('security', 'Sicherheitsupdates', 0, { warn: 1 }),
      metric('pending', 'Ausstehend gesamt', 4, null),
      metric('counted', 'Gezählt vor', 52, null, { unit: 'min' }),
    ],
  }),
  obj({
    kind: 'updates',
    server: 'srv-01',
    name: 'Updates',
    identity: ['FreeBSD 14.3', 'Quelle: pkg audit'],
    status: 'ok',
    reason: 'Keine verwundbaren Pakete',
    since: ago(21 * DAY),
    metrics: [
      metric('security', 'Verwundbare Pakete', 0, { warn: 1 }),
      metric('counted', 'Gezählt vor', 44, null, { unit: 'min' }),
    ],
  }),
  obj({
    kind: 'clock',
    server: 'web-01',
    name: 'Uhr',
    identity: ['systemd-timesyncd'],
    status: 'ok',
    reason: 'Synchronisiert',
    since: ago(41 * DAY),
    metrics: [metric('offset', 'Abweichung', '+0,004', null, { unit: 's', newData: true })],
  }),
  obj({
    kind: 'clock',
    server: 'nas-01',
    name: 'Uhr',
    identity: ['chrony'],
    status: 'warning',
    reason: 'Nicht synchronisiert',
    since: ago(2 * HOUR),
    metrics: [
      metric('offset', 'Abweichung', '+4,2', null, { unit: 's', newData: true }),
      metric('source', 'Zeitquelle', 'nicht erreichbar', null),
    ],
    firing: ['clock.sync'],
  }),
  obj({
    kind: 'clock',
    server: 'srv-01',
    name: 'Uhr',
    identity: ['FreeBSD 14.3'],
    status: 'not-collected',
    reason: 'Nicht erhoben: der FreeBSD-Agent prüft die Uhr nicht',
    since: ago(21 * DAY),
    metrics: [],
  }),
];

// ---------------------------------------------------------------------------------------------
// service (§4.12)

const SERVICES: MonObject[] = [
  obj({
    kind: 'service',
    server: 'web-01',
    id: 'service/nginx.service',
    name: 'nginx.service',
    identity: ['systemd', 'A high performance web server and a reverse proxy server'],
    status: 'critical',
    reason: 'Fehlgeschlagen: exit-code, status=1',
    since: ago(45),
    metrics: [
      metric('state', 'Zustand', 'failed', null, { status: 'critical' }),
      metric('restarts', 'Neustarts (1 h)', 0, RESTARTS),
      metric('autostart', 'Autostart', 'aktiviert', null),
    ],
    details: [
      {
        type: 'log',
        title: 'Journal',
        lines: [
          log(
            46,
            'nginx.service',
            'info',
            'Reloading nginx.service - A high performance web server…',
          ),
          log(
            45,
            'nginx',
            'err',
            'nginx: [emerg] open() "/var/log/nginx/access.log" failed (28: No space left on device)',
          ),
          log(
            45,
            'systemd',
            'warning',
            'nginx.service: Control process exited, code=exited, status=1/FAILURE',
          ),
          log(45, 'systemd', 'err', "nginx.service: Failed with result 'exit-code'."),
        ],
        more: 'journalctl -u nginx.service --since "-1h"',
      },
    ],
    firing: ['service.failed'],
    history: [{ at: ago(45), status: 'critical', text: 'fehlgeschlagen (exit-code, status=1)' }],
  }),
  obj({
    kind: 'service',
    server: 'web-01',
    id: 'service/php8.4-fpm.service',
    name: 'php8.4-fpm.service',
    identity: ['systemd', 'The PHP 8.4 FastCGI Process Manager'],
    status: 'ok',
    reason: 'Läuft',
    since: ago(12 * DAY),
    metrics: [
      metric('state', 'Zustand', 'active (running)', null),
      metric('restarts', 'Neustarts (1 h)', 0, RESTARTS),
      metric('mem', 'RAM', 212, null, { unit: 'MB' }),
      metric('autostart', 'Autostart', 'aktiviert', null),
    ],
  }),
  obj({
    kind: 'service',
    server: 'db-01',
    id: 'service/pgbouncer.service',
    name: 'pgbouncer.service',
    identity: ['systemd', 'connection pooler for PostgreSQL'],
    status: 'warning',
    reason: 'Neustart-Schleife: 14 Neustarts in 1 h',
    since: ago(50),
    metrics: [
      metric('state', 'Zustand', 'activating (auto-restart)', null),
      metric('restarts', 'Neustarts (1 h)', 14, RESTARTS, { status: 'warning' }),
      metric('mem', 'RAM', 18, null, { unit: 'MB' }),
      metric('autostart', 'Autostart', 'aktiviert', null),
    ],
    details: [
      {
        type: 'log',
        title: 'Journal',
        lines: [
          log(6, 'pgbouncer', 'err', 'FATAL could not connect to server: connection refused'),
          log(
            6,
            'systemd',
            'warning',
            'pgbouncer.service: Main process exited, code=exited, status=1/FAILURE',
          ),
          log(
            5,
            'systemd',
            'notice',
            'pgbouncer.service: Scheduled restart job, restart counter is at 14.',
          ),
          log(
            5,
            'systemd',
            'info',
            'Started pgbouncer.service - connection pooler for PostgreSQL.',
          ),
        ],
        more: 'journalctl -u pgbouncer.service --since "-1h"',
      },
    ],
    firing: ['service.restarts'],
  }),
  obj({
    kind: 'service',
    server: 'mail-01',
    id: 'service/clamav-freshclam.service',
    name: 'clamav-freshclam.service',
    identity: ['systemd'],
    status: 'info',
    reason: 'Entfernt: die Unit gibt es nicht mehr',
    since: ago(2 * DAY),
    metrics: [],
    history: [
      { at: ago(2 * DAY), status: 'info', text: 'Unit entfernt, Problem geschlossen (entfernt)' },
      { at: ago(5 * DAY), status: 'critical', text: 'fehlgeschlagen (exit-code, status=2)' },
    ],
  }),
  obj({
    kind: 'service',
    server: 'dc-01',
    id: 'service/spooler',
    name: 'spooler',
    identity: ['Windows-Dienst', 'Druckwarteschlange'],
    status: 'critical',
    reason: 'Gestoppt: Exitcode 1067',
    since: ago(5 * HOUR),
    metrics: [
      metric('state', 'Zustand', 'STOPPED', null, { status: 'critical' }),
      metric('exit', 'Exitcode', 1067, null),
      metric('autostart', 'Autostart', 'unbekannt', null, {
        note: 'Windows-Starttyp fehlt',
        newData: true,
      }),
    ],
    firing: ['service.failed'],
  }),
];

export const HOST_OBJECTS: MonObject[] = [...HOSTS, ...RESOURCES, ...STALE, ...SYSTEM, ...SERVICES];
