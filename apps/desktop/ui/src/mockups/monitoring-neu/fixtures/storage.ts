// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Storage and backup fixtures (Konzept §4.1–§4.3): the states of disks, pools, guest backups and
// backup jobs, each as the server of the target model would deliver it. Fictitious data only.

import type {
  Detail,
  HistoryEvent,
  Metric,
  MonObject,
  RuleView,
  SmartRow,
  Status,
  Threshold,
  TrendPoint,
  VdevNode,
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

function withFiring(list: RuleView[], firing: string[] = []): RuleView[] {
  return list.map((r) => ({ ...r, firing: firing.includes(r.key) }));
}

/** One point per day, oldest first, ending today. */
function daily(days: number, value: (i: number) => number): TrendPoint[] {
  return Array.from({ length: days }, (_, i) => ({
    at: ago((days - 1 - i) * DAY),
    value: value(i),
  }));
}

// ---------------------------------------------------------------------------------------------
// disk (§4.1)

type DiskClass = 'HDD' | 'SATA-SSD' | 'NVMe' | 'SAS';

const TEMP: Record<DiskClass, Threshold> = {
  HDD: { warn: 55, crit: 60 },
  'SATA-SSD': { warn: 60, crit: 70 },
  NVMe: { warn: 65, crit: 75 },
  SAS: { warn: 55, crit: 60 },
};

/** smartctl exit status bits (man smartctl, EXIT STATUS) in plain words. */
const EXIT_BITS: Record<number, string> = {
  1: 'Gerät nicht lesbar oder im Energiesparmodus',
  2: 'Ein SMART-Befehl schlug fehl oder eine Prüfsumme stimmte nicht',
  3: 'SMART meldet: Platte fällt aus (DISK FAILING)',
  4: 'Ein Vorausfall-Attribut liegt an oder unter seiner Schwelle',
  5: 'Ein Attribut lag früher an oder unter seiner Schwelle',
  6: 'Das Fehlerprotokoll der Platte enthält Einträge',
  7: 'Das Selbsttest-Protokoll enthält Fehler',
};

const temp = (v: number, cls: DiskClass, extra: Partial<Metric> = {}) =>
  metric('temp', 'Temperatur', v, TEMP[cls], { unit: '°C', ...extra });
const hours = (h: number, extra: Partial<Metric> = {}) =>
  metric('hours', 'Betriebsstunden', h, null, {
    unit: 'h',
    note: `≈ ${(h / 8766).toLocaleString('de-DE', { maximumFractionDigits: 1 })} J.`,
    ...extra,
  });
const realloc = (v: number, extra: Partial<Metric> = {}) =>
  metric('realloc', 'Umgelagert', v, { warn: 1, crit: 10 }, extra);
const pending = (v: number, extra: Partial<Metric> = {}) =>
  metric('pending', 'Schwebend', v, { warn: 1, crit: 5 }, extra);
const wear = (v: number, extra: Partial<Metric> = {}) =>
  metric('wear', 'Verschleiß', v, { warn: 90, crit: 100 }, { unit: '%', ...extra });

const DISK_RULES: Record<DiskClass, RuleView[]> = {
  HDD: [
    {
      key: 'smart.passed',
      text: 'SMART meldet Defekt',
      level: 'critical',
      source: 'Katalog',
      enabled: true,
    },
    {
      key: 'smart.realloc',
      text: 'Umgelagerte Sektoren ab 1 (kritisch ab 10)',
      level: 'warning',
      source: 'Katalog',
      enabled: true,
    },
    {
      key: 'smart.realloc.rising',
      text: 'Umgelagerte Sektoren steigen',
      level: 'warning',
      source: 'Katalog',
      enabled: true,
    },
    {
      key: 'smart.pending',
      text: 'Schwebende Sektoren ab 1 (kritisch ab 5)',
      level: 'warning',
      source: 'Katalog',
      enabled: true,
    },
    {
      key: 'smart.uncorrectable',
      text: 'Nicht korrigierbare Sektoren ab 1',
      level: 'critical',
      source: 'Katalog',
      enabled: true,
    },
    {
      key: 'smart.temp',
      text: 'Temperatur ab 55 °C (kritisch ab 60 °C), Entwarnung unter 52 °C',
      level: 'warning',
      source: 'Katalog',
      enabled: true,
    },
    {
      key: 'smart.crc.rising',
      text: 'Übertragungsfehler (199) steigen',
      level: 'warning',
      source: 'Katalog',
      enabled: true,
    },
  ],
  'SATA-SSD': [
    {
      key: 'smart.passed',
      text: 'SMART meldet Defekt',
      level: 'critical',
      source: 'Katalog',
      enabled: true,
    },
    {
      key: 'smart.wear',
      text: 'Verschleiß ab 90 % (kritisch ab 100 %)',
      level: 'warning',
      source: 'Katalog',
      enabled: true,
    },
    {
      key: 'smart.realloc',
      text: 'Umgelagerte Blöcke ab 1 (kritisch ab 10)',
      level: 'warning',
      source: 'Katalog',
      enabled: true,
    },
    {
      key: 'smart.temp',
      text: 'Temperatur ab 60 °C (kritisch ab 70 °C), Entwarnung unter 57 °C',
      level: 'warning',
      source: 'Katalog',
      enabled: true,
    },
  ],
  NVMe: [
    {
      key: 'nvme.critical_warning',
      text: 'NVMe meldet eine kritische Warnung',
      level: 'critical',
      source: 'Katalog',
      enabled: true,
    },
    {
      key: 'nvme.spare',
      text: 'Reserve unter 20 % (kritisch unter 10 %)',
      level: 'warning',
      source: 'Katalog',
      enabled: true,
    },
    {
      key: 'nvme.media_errors',
      text: 'Medienfehler ab 1',
      level: 'critical',
      source: 'Katalog',
      enabled: true,
    },
    {
      key: 'smart.wear',
      text: 'Verschleiß ab 90 % (kritisch ab 100 %)',
      level: 'warning',
      source: 'Katalog',
      enabled: true,
    },
    {
      key: 'smart.temp',
      text: 'Temperatur ab 65 °C (kritisch ab 75 °C), Entwarnung unter 62 °C',
      level: 'warning',
      source: 'Katalog',
      enabled: true,
    },
  ],
  SAS: [
    {
      key: 'sas.health',
      text: 'SCSI-Gesundheit nicht OK',
      level: 'critical',
      source: 'Katalog',
      enabled: true,
    },
    {
      key: 'sas.grown_defects.rising',
      text: 'Grown defects steigen',
      level: 'warning',
      source: 'Katalog',
      enabled: true,
    },
    {
      key: 'sas.uncorrected',
      text: 'Unkorrigierte Fehler ab 1',
      level: 'critical',
      source: 'Katalog',
      enabled: true,
    },
    {
      key: 'smart.temp',
      text: 'Temperatur ab 55 °C (kritisch ab 60 °C), Entwarnung unter 52 °C',
      level: 'warning',
      source: 'Katalog',
      enabled: true,
    },
  ],
};

interface AtaValues {
  realloc: number;
  pending: number;
  uncorrectable?: number;
  crc?: number;
  hours: number;
  temp: number;
}

function ataRows(
  v: AtaValues,
  status: Partial<Record<string, Status>> = {},
  past = false,
): SmartRow[] {
  const row = (id: number, name: string, raw: number, normalized: number, threshold: number) => ({
    id,
    name,
    raw: String(raw),
    normalized,
    threshold,
    whenFailed: past && id === 5 ? 'In_the_past' : undefined,
    status: status[name],
  });
  return [
    row(5, 'Reallocated_Sector_Ct', v.realloc, v.realloc > 0 ? 97 : 100, 10),
    row(9, 'Power_On_Hours', v.hours, 57, 0),
    row(194, 'Temperature_Celsius', v.temp, 100 - v.temp, 0),
    row(197, 'Current_Pending_Sector', v.pending, 100, 0),
    row(198, 'Offline_Uncorrectable', v.uncorrectable ?? 0, 100, 0),
    row(199, 'UDMA_CRC_Error_Count', v.crc ?? 0, 200, 0),
  ];
}

interface DiskSpec {
  server: string;
  dev: string;
  /** WWN, else model+serial; host+device only with `unstableKey`. */
  id: string;
  unstableKey?: boolean;
  model: string;
  serial: string;
  size: string;
  cls: DiskClass;
  pool?: string;
  status: Status;
  reason: string;
  since: string;
  badSince?: string;
  metrics: Metric[];
  firing?: string[];
  smart?: SmartRow[];
  exitBits?: number[];
  details?: Detail[];
  history?: HistoryEvent[];
  raw?: string;
}

function disk(s: DiskSpec): MonObject {
  const details: Detail[] = [];
  if (s.smart) {
    details.push({
      type: 'smart',
      title: 'SMART-Attribute',
      rows: s.smart,
      exitBits: (s.exitBits ?? []).map((bit) => ({ bit, text: EXIT_BITS[bit] })),
    });
  }
  return {
    key: `${s.server}/disk/${s.id}`,
    kind: 'disk',
    name: s.dev.replace('/dev/', ''),
    server: s.server,
    identity: [
      s.model,
      `S/N ${s.serial}`,
      `${s.size} ${s.cls}`,
      s.dev,
      ...(s.pool ? [`Pool ${s.pool}`] : []),
    ],
    status: s.status,
    reason: s.reason,
    since: s.since,
    badSince: s.badSince,
    metrics: s.metrics,
    attributes: [
      { key: 'Modell', value: s.model },
      { key: 'Seriennummer', value: s.serial, mono: true },
      { key: 'Kapazität', value: s.size },
      { key: 'Klasse', value: s.cls },
      { key: 'Gerät', value: s.dev, mono: true },
      {
        key: 'Schlüssel',
        value: s.unstableKey ? `${s.id} (Host + Gerät, instabil)` : s.id,
        mono: true,
      },
    ],
    details: [...details, ...(s.details ?? [])],
    history: s.history,
    rules: withFiring(DISK_RULES[s.cls], s.firing),
    raw: s.raw,
  };
}

const DISKS: MonObject[] = [
  disk({
    server: 'nas-01',
    dev: '/dev/sda',
    id: 'wwn-0x50014ee2b1a2c301',
    model: 'WDC WD40EFZX',
    serial: 'WD-WX12A3456701',
    size: '4 TB',
    cls: 'HDD',
    pool: 'tank',
    status: 'ok',
    reason: 'Gesund',
    since: ago(40 * DAY),
    metrics: [temp(38, 'HDD'), realloc(0), pending(0), hours(38211)],
    smart: ataRows({ realloc: 0, pending: 0, hours: 38211, temp: 38 }),
    details: [
      {
        type: 'trend',
        title: 'Temperatur, 30 Tage',
        unit: '°C',
        threshold: TEMP.HDD,
        points: daily(30, (i) => 36 + ((i * 7) % 5)),
      },
    ],
    raw: '{ "smart_status": { "passed": true }, "temperature": { "current": 38 }, "power_on_time": { "hours": 38211 } }',
  }),
  disk({
    server: 'nas-01',
    dev: '/dev/sdb',
    id: 'wwn-0x50014ee2b1a2c302',
    model: 'WDC WD40EFZX',
    serial: 'WD-WX12A3456702',
    size: '4 TB',
    cls: 'HDD',
    pool: 'tank',
    status: 'warning',
    reason: '8 umgelagerte Sektoren, steigend',
    since: ago(40 * DAY),
    metrics: [
      temp(41, 'HDD'),
      realloc(8, { status: 'warning', note: '+2 seit gestern' }),
      pending(0),
      hours(38190),
    ],
    firing: ['smart.realloc', 'smart.realloc.rising'],
    smart: ataRows(
      { realloc: 8, pending: 0, hours: 38190, temp: 41 },
      { Reallocated_Sector_Ct: 'warning' },
    ),
    details: [
      {
        type: 'trend',
        title: 'Umgelagerte Sektoren, 30 Tage',
        threshold: { warn: 1, crit: 10 },
        points: daily(30, (i) => (i < 9 ? 2 : i < 29 ? 6 : 8)),
      },
    ],
    history: [
      { at: ago(40 * DAY), status: 'warning', text: 'Umgelagert 0 → 2' },
      { at: ago(20 * DAY), status: 'warning', text: 'Umgelagert 2 → 6' },
      { at: ago(6 * HOUR), status: 'warning', text: 'Umgelagert 6 → 8' },
    ],
  }),
  disk({
    server: 'pve-01',
    dev: '/dev/sda',
    id: 'wwn-0x5000c500a1b2c303',
    model: 'ST2000VN004',
    serial: 'ZA1B2C03',
    size: '2 TB',
    cls: 'HDD',
    status: 'warning',
    reason: '8 umgelagerte Sektoren, seit 40 Tagen unverändert',
    since: ago(40 * DAY),
    metrics: [temp(36, 'HDD'), realloc(8, { status: 'warning' }), pending(0), hours(51022)],
    firing: ['smart.realloc'],
    smart: ataRows(
      { realloc: 8, pending: 0, hours: 51022, temp: 36 },
      { Reallocated_Sector_Ct: 'warning' },
    ),
    history: [{ at: ago(40 * DAY), status: 'warning', text: 'Umgelagert 5 → 8' }],
  }),
  disk({
    server: 'nas-01',
    dev: '/dev/sdd',
    id: 'wwn-0x50014ee2b1a2c304',
    model: 'WDC WD40EFZX',
    serial: 'WD-WX12A3456704',
    size: '4 TB',
    cls: 'HDD',
    pool: 'tank',
    status: 'warning',
    reason: '3 umgelagerte Sektoren, seit 90 Tagen unverändert',
    since: ago(90 * DAY),
    metrics: [temp(39, 'HDD'), realloc(3, { status: 'warning' }), pending(0), hours(38205)],
    firing: ['smart.realloc'],
    smart: ataRows(
      { realloc: 3, pending: 0, hours: 38205, temp: 39 },
      { Reallocated_Sector_Ct: 'warning' },
    ),
  }),
  disk({
    server: 'pve-01',
    dev: '/dev/sdb',
    id: 'wwn-0x5000c500a1b2c305',
    model: 'ST2000VN004',
    serial: 'ZA1B2C05',
    size: '2 TB',
    cls: 'HDD',
    status: 'warning',
    reason: 'Zu heiß: 58 °C',
    since: ago(5 * HOUR),
    metrics: [
      temp(58, 'HDD', { status: 'warning', note: 'Entwarnung unter 52' }),
      realloc(0),
      pending(0),
      hours(50980),
    ],
    firing: ['smart.temp'],
    smart: ataRows({ realloc: 0, pending: 0, hours: 50980, temp: 58 }),
    details: [
      {
        type: 'trend',
        title: 'Temperatur, 7 Tage',
        unit: '°C',
        threshold: TEMP.HDD,
        points: daily(7, (i) => [49, 55, 51, 48, 50, 53, 58][i]),
      },
    ],
    history: [
      { at: ago(5 * HOUR), status: 'warning', text: '56 °C, ab 55' },
      { at: ago(4 * DAY), status: 'ok', text: '51 °C, unter 52, entwarnt' },
      { at: ago(5 * DAY), status: 'warning', text: '55 °C, ab 55' },
    ],
  }),
  disk({
    server: 'pve-01',
    dev: '/dev/sdc',
    id: 'wwn-0x5002538f4a1b2c06',
    model: 'Samsung SSD 870 EVO 1TB',
    serial: 'S6PNNX0T100006',
    size: '1 TB',
    cls: 'SATA-SSD',
    status: 'ok',
    reason: 'Gesund',
    since: ago(200 * DAY),
    metrics: [
      temp(34, 'SATA-SSD'),
      wear(12, { newData: true }),
      metric('realloc', 'Umgelagerte Blöcke', 0, { warn: 1, crit: 10 }),
      hours(21034),
    ],
  }),
  disk({
    server: 'web-01',
    dev: '/dev/sda',
    id: 'wwn-0x5002538f4a1b2c07',
    model: 'Samsung SSD 860 EVO 500GB',
    serial: 'S3Z1NB0K100007',
    size: '500 GB',
    cls: 'SATA-SSD',
    status: 'warning',
    reason: 'Verschleiß 92 %',
    since: ago(9 * DAY),
    metrics: [
      temp(31, 'SATA-SSD'),
      wear(92, { status: 'warning', newData: true, note: '+1 % im Monat' }),
      metric('realloc', 'Umgelagerte Blöcke', 0, { warn: 1, crit: 10 }),
      hours(43890),
    ],
    firing: ['smart.wear'],
  }),
  disk({
    server: 'pve-01',
    dev: '/dev/nvme0n1',
    id: 'eui.0025385b71a2c308',
    model: 'Samsung SSD 980 PRO 1TB',
    serial: 'S5GXNF0R100008',
    size: '1 TB',
    cls: 'NVMe',
    status: 'ok',
    reason: 'Gesund',
    since: ago(120 * DAY),
    metrics: [
      temp(46, 'NVMe'),
      wear(12),
      metric(
        'spare',
        'Reserve',
        100,
        { warn: 20, crit: 10, below: true },
        { unit: '%', note: 'Hersteller 10' },
      ),
      metric('media', 'Medienfehler', 0, { crit: 1 }),
    ],
  }),
  disk({
    server: 'pve-02',
    dev: '/dev/nvme0n1',
    id: 'eui.0025385b71a2c309',
    model: 'Samsung SSD 970 EVO Plus 500GB',
    serial: 'S4EVNF0M100009',
    size: '500 GB',
    cls: 'NVMe',
    status: 'critical',
    reason: 'NVMe-Warnung: Reserve erschöpft',
    since: ago(2 * HOUR),
    badSince: ago(9 * DAY),
    metrics: [
      temp(52, 'NVMe'),
      wear(97, { status: 'warning' }),
      metric(
        'spare',
        'Reserve',
        4,
        { warn: 20, crit: 10, below: true },
        { unit: '%', status: 'critical', note: 'Hersteller 10' },
      ),
      metric('media', 'Medienfehler', 0, { crit: 1 }),
    ],
    firing: ['nvme.critical_warning', 'nvme.spare', 'smart.wear'],
    history: [
      { at: ago(9 * DAY), status: 'warning', text: 'Verschleiß 90 %, Reserve 18 %' },
      { at: ago(2 * HOUR), status: 'critical', text: 'Reserve 4 %, NVMe-Warnung Bit 0' },
    ],
    details: [
      {
        type: 'note',
        title: 'NVMe critical_warning',
        text: 'Bit 0 gesetzt: Die Reserve liegt unter der Herstellergrenze von 10 %.',
      },
    ],
  }),
  disk({
    server: 'db-01',
    dev: '/dev/nvme0n1',
    id: 'eui.0025385b71a2c310',
    model: 'WD Red SN700 1TB',
    serial: '22301A800010',
    size: '1 TB',
    cls: 'NVMe',
    status: 'critical',
    reason: '3 Medienfehler',
    since: ago(30),
    metrics: [
      temp(49, 'NVMe'),
      wear(31),
      metric('spare', 'Reserve', 100, { warn: 20, crit: 10, below: true }, { unit: '%' }),
      metric(
        'media',
        'Medienfehler',
        3,
        { crit: 1 },
        { status: 'critical', note: '+3 seit 30 min' },
      ),
    ],
    firing: ['nvme.media_errors'],
  }),
  disk({
    server: 'nas-01',
    dev: '/dev/sde',
    id: 'wwn-0x50014ee2b1a2c311',
    model: 'WDC WD40EFZX',
    serial: 'WD-WX12A3456711',
    size: '4 TB',
    cls: 'HDD',
    pool: 'archive',
    status: 'critical',
    reason: '2 nicht korrigierbare Sektoren',
    since: ago(3 * HOUR),
    metrics: [
      temp(40, 'HDD'),
      realloc(0),
      pending(2, { status: 'warning' }),
      metric('uncorrectable', 'Nicht korrigierbar', 2, { crit: 1 }, { status: 'critical' }),
    ],
    firing: ['smart.pending', 'smart.uncorrectable'],
    smart: ataRows(
      { realloc: 0, pending: 2, uncorrectable: 2, hours: 29411, temp: 40 },
      { Current_Pending_Sector: 'warning', Offline_Uncorrectable: 'critical' },
    ),
    exitBits: [6],
  }),
  disk({
    server: 'backup-01',
    dev: '/dev/sda',
    id: 'wwn-0x5000c500a1b2c312',
    model: 'SEAGATE ST8000NM0075',
    serial: 'ZA1B2C12',
    size: '8 TB',
    cls: 'SAS',
    status: 'ok',
    reason: 'Gesund',
    since: ago(300 * DAY),
    metrics: [
      temp(36, 'SAS', { newData: true }),
      metric('grown', 'Grown defects', 0, { warn: 1 }, { newData: true }),
      metric('uncorrected', 'Unkorrigierte Fehler', 0, { crit: 1 }, { newData: true }),
      hours(33870, { newData: true }),
    ],
  }),
  disk({
    server: 'nas-01',
    dev: '/dev/sdf',
    id: 'wwn-0x50014ee2b1a2c313',
    model: 'WDC WD80EFZZ',
    serial: 'WD-CA12B3456713',
    size: '8 TB',
    cls: 'HDD',
    pool: 'archive',
    status: 'info',
    reason: 'Schläft, Werte von vor 3 h',
    since: ago(3 * HOUR),
    metrics: [temp(33, 'HDD', { note: 'vor 3 h' }), realloc(0), pending(0), hours(12044)],
    details: [
      {
        type: 'note',
        title: 'Standby',
        text: 'Der Agent liest schlafende Platten nicht (smartctl -n standby) und weckt sie damit nicht; die Werte stammen vom letzten Lesen im Betrieb.',
      },
    ],
  }),
  disk({
    server: 'web-01',
    dev: '/dev/sdb',
    id: 'web-01:/dev/sdb',
    unstableKey: true,
    model: 'USB-Brücke JMicron JMS578',
    serial: 'unbekannt',
    size: '2 TB',
    cls: 'HDD',
    status: 'unknown',
    reason: 'SMART nicht lesbar',
    since: ago(14 * DAY),
    metrics: [],
    exitBits: [2],
    smart: [],
    details: [
      {
        type: 'note',
        title: 'Warum unbekannt',
        text: 'Die USB-Brücke reicht SMART nicht durch. Das ist kein Defekt der Platte, aber ihr Zustand ist nicht bekannt.',
      },
    ],
  }),
  disk({
    server: 'db-01',
    dev: '/dev/sda',
    id: 'wwn-0x5000c500a1b2c315',
    model: 'ST1000NM0055',
    serial: 'ZA1B2C15',
    size: '1 TB',
    cls: 'HDD',
    status: 'critical',
    reason: 'SMART meldet Defekt',
    since: ago(6 * HOUR),
    badSince: ago(12 * DAY),
    metrics: [
      temp(44, 'HDD'),
      realloc(14, { status: 'critical' }),
      pending(6, { status: 'critical' }),
      hours(61200),
    ],
    firing: ['smart.passed', 'smart.realloc', 'smart.pending'],
    smart: ataRows(
      { realloc: 14, pending: 6, hours: 61200, temp: 44 },
      { Reallocated_Sector_Ct: 'critical', Current_Pending_Sector: 'critical' },
    ),
    exitBits: [3, 4, 6],
    history: [
      { at: ago(12 * DAY), status: 'warning', text: 'Umgelagert 0 → 3' },
      { at: ago(6 * HOUR), status: 'critical', text: 'SMART-Selbstbewertung FAILED' },
    ],
  }),
  disk({
    server: 'pve-02',
    dev: '/dev/sda',
    id: 'wwn-0x5000c500a1b2c316',
    model: 'ST2000VN004',
    serial: 'ZA1B2C16',
    size: '2 TB',
    cls: 'HDD',
    status: 'info',
    reason: 'Gesund, frühere Fehler im Protokoll',
    since: ago(25 * DAY),
    metrics: [temp(37, 'HDD'), realloc(0), pending(0), hours(44120)],
    smart: ataRows({ realloc: 0, pending: 0, hours: 44120, temp: 37 }, {}, true),
    exitBits: [5, 6],
  }),
  disk({
    server: 'backup-01',
    dev: '/dev/sdb',
    id: 'wwn-0x50014ee2b1a2c317',
    model: 'WDC WD20SPZX (USB)',
    serial: 'WD-WX22A3456717',
    size: '2 TB',
    cls: 'HDD',
    status: 'not-collected',
    reason: 'Nicht geprüft',
    since: ago(70 * DAY),
    metrics: [],
  }),
];

// ---------------------------------------------------------------------------------------------
// pool (§4.2)

const POOL_RULES: RuleView[] = [
  {
    key: 'zfs.state',
    text: 'Zustand nicht ONLINE',
    level: 'critical',
    source: 'Katalog',
    enabled: true,
  },
  {
    key: 'zfs.used',
    text: 'Belegung ab 80 % (kritisch ab 90 %), Entwarnung unter 78 %',
    level: 'warning',
    source: 'Katalog',
    enabled: true,
  },
  {
    key: 'zfs.scrub_age',
    text: 'Letzter Scrub älter als 35 Tage (kritisch ab 60)',
    level: 'warning',
    source: 'Katalog',
    enabled: true,
  },
  {
    key: 'zfs.errors.rising',
    text: 'Gerätefehler steigen',
    level: 'warning',
    source: 'Katalog',
    enabled: true,
  },
];

const dev = (
  name: string,
  status: Status = 'ok',
  state = 'ONLINE',
  cksum = 0,
  note?: string,
): VdevNode => ({
  name,
  state,
  status,
  read: 0,
  write: 0,
  cksum,
  note,
});

interface PoolSpec {
  server: string;
  name: string;
  layout: string;
  size: string;
  status: Status;
  reason: string;
  since: string;
  used: number;
  free: string;
  scrubDays: number;
  scrubErrors?: number;
  errors: number;
  /** zpool list frag; absent where zpool prints "-" (the agent leaves it out). */
  frag?: number;
  metricStatus?: Partial<Record<'used' | 'scrub' | 'errors', Status>>;
  errorsNote?: string;
  root: VdevNode;
  firing?: string[];
  details?: Detail[];
  raw?: string;
}

function pool(s: PoolSpec): MonObject {
  const st = s.metricStatus ?? {};
  return {
    key: `${s.server}/pool/${s.name}`,
    kind: 'pool',
    name: s.name,
    server: s.server,
    identity: [s.layout, s.size],
    status: s.status,
    reason: s.reason,
    since: s.since,
    metrics: [
      metric(
        'used',
        'Belegung',
        s.used,
        { warn: 80, crit: 90 },
        { unit: '%', note: `${s.free} frei`, status: st.used },
      ),
      metric(
        'scrub',
        'Letzter Scrub',
        s.scrubDays,
        { warn: 35, crit: 60 },
        { unit: 'Tage', note: `${s.scrubErrors ?? 0} Fehler`, status: st.scrub },
      ),
      metric(
        'errors',
        'Gerätefehler',
        s.errors,
        { warn: 1 },
        { status: st.errors, note: s.errorsNote },
      ),
      metric('layout', 'Redundanz', s.layout, null),
    ],
    attributes: [
      { key: 'Layout', value: s.layout },
      { key: 'Größe', value: s.size },
      { key: 'Fragmentierung', value: s.frag === undefined ? 'unbekannt' : `${s.frag} %` },
      { key: 'Schlüssel', value: `${s.server}/${s.name} (später Pool-GUID)`, mono: true },
    ],
    details: [{ type: 'vdev', title: 'Aufbau', root: s.root }, ...(s.details ?? [])],
    rules: withFiring(POOL_RULES, s.firing),
    raw: s.raw,
  };
}

const POOLS: MonObject[] = [
  pool({
    server: 'nas-01',
    name: 'tank',
    frag: 12,
    layout: 'raidz2, 6 Platten',
    size: '21,8 TB',
    status: 'ok',
    reason: 'Gesund',
    since: ago(90 * DAY),
    used: 72,
    free: '6,1 TB',
    scrubDays: 12,
    errors: 0,
    root: {
      ...dev('tank'),
      children: [
        {
          ...dev('raidz2-0'),
          children: ['sda', 'sdb', 'sdc', 'sdd', 'sdg', 'sdh'].map((d) => dev(d)),
        },
      ],
    },
    details: [
      {
        type: 'trend',
        title: 'Belegung, 90 Tage',
        unit: '%',
        threshold: { warn: 80, crit: 90 },
        points: daily(90, (i) => 61 + Math.round(i / 8)),
      },
    ],
  }),
  pool({
    server: 'pve-01',
    name: 'rpool',
    frag: 8,
    layout: 'mirror, 2 Platten',
    size: '1,8 TB',
    status: 'critical',
    reason: 'Beeinträchtigt: 1 Platte ausgefallen, keine Redundanz',
    since: ago(50),
    used: 41,
    free: '1,1 TB',
    scrubDays: 9,
    errors: 0,
    firing: ['zfs.state'],
    root: {
      ...dev('rpool', 'critical', 'DEGRADED'),
      children: [
        {
          ...dev('mirror-0', 'critical', 'DEGRADED'),
          children: [dev('sda3'), dev('sdd3', 'critical', 'FAULTED', 37, 'zu viele Fehler')],
        },
      ],
    },
    raw: "  pool: rpool\n state: DEGRADED\nstatus: One or more devices are faulted in response to persistent errors.\naction: Replace the faulted device, or use 'zpool clear' to mark the device repaired.",
  }),
  pool({
    server: 'nas-01',
    name: 'archive',
    frag: 31,
    layout: 'mirror, 2 Platten',
    size: '7,3 TB',
    status: 'warning',
    reason: '12 Prüfsummenfehler auf sde',
    since: ago(1 * DAY),
    used: 64,
    free: '2,6 TB',
    scrubDays: 1,
    scrubErrors: 12,
    errors: 12,
    errorsNote: '+12 seit gestern',
    metricStatus: { errors: 'warning' },
    firing: ['zfs.errors.rising'],
    root: {
      ...dev('archive'),
      children: [
        {
          ...dev('mirror-0'),
          children: [dev('sde', 'warning', 'ONLINE', 12), dev('sdf')],
        },
      ],
    },
  }),
  pool({
    server: 'pve-02',
    name: 'data',
    frag: 19,
    layout: 'mirror, 2 Platten',
    size: '3,6 TB',
    status: 'critical',
    reason: 'Fast voll: 91 %',
    since: ago(2 * DAY),
    used: 91,
    free: '0,3 TB',
    scrubDays: 20,
    errors: 0,
    metricStatus: { used: 'critical' },
    firing: ['zfs.used'],
    root: {
      ...dev('data'),
      children: [{ ...dev('mirror-0'), children: [dev('sdb'), dev('sdc')] }],
    },
    details: [
      {
        type: 'trend',
        title: 'Belegung, 30 Tage',
        unit: '%',
        threshold: { warn: 80, crit: 90 },
        points: daily(30, (i) => 74 + Math.round(i * 0.6)),
      },
    ],
  }),
  pool({
    server: 'backup-01',
    name: 'store',
    layout: 'raidz1, 4 Platten',
    size: '21,8 TB',
    status: 'warning',
    reason: 'Scrub überfällig (vor 41 Tagen)',
    since: ago(6 * DAY),
    used: 58,
    free: '9,2 TB',
    scrubDays: 41,
    errors: 0,
    metricStatus: { scrub: 'warning' },
    firing: ['zfs.scrub_age'],
    root: {
      ...dev('store'),
      children: [{ ...dev('raidz1-0'), children: ['sda', 'sdc', 'sdd', 'sde'].map((d) => dev(d)) }],
    },
  }),
  pool({
    server: 'srv-01',
    name: 'zroot',
    frag: 4,
    layout: 'einzelne Platte',
    size: '460 GB',
    status: 'critical',
    reason: 'Angehalten (SUSPENDED)',
    since: ago(12),
    used: 37,
    free: '290 GB',
    scrubDays: 30,
    errors: 3,
    metricStatus: { errors: 'warning' },
    firing: ['zfs.state', 'zfs.errors.rising'],
    root: {
      ...dev('zroot', 'critical', 'SUSPENDED'),
      children: [dev('ada0p3', 'critical', 'UNAVAIL')],
    },
  }),
];

// ---------------------------------------------------------------------------------------------
// guest-backup and backup-job (§4.3)

const BACKUP_RULES: RuleView[] = [
  {
    key: 'backup.age',
    text: 'Älter als der Job-Zeitplan erlaubt (täglich: 26 h)',
    level: 'warning',
    source: 'Katalog',
    enabled: true,
  },
  {
    key: 'backup.never',
    text: 'Nie gesichert',
    level: 'critical',
    source: 'Katalog',
    enabled: true,
  },
  {
    key: 'backup.failed',
    text: 'Letzter Lauf fehlgeschlagen',
    level: 'critical',
    source: 'Katalog',
    enabled: true,
  },
  {
    key: 'backup.no_job',
    text: 'Kein Job erfasst den Gast',
    level: 'warning',
    source: 'Katalog',
    enabled: true,
  },
  {
    key: 'backup.verify',
    text: 'Verifizierung fehlgeschlagen',
    level: 'warning',
    source: 'Katalog',
    enabled: true,
  },
];

const CLUSTER = 'cl-a';

interface GuestSpec {
  vmid: number;
  name: string;
  type: 'VM' | 'CT';
  node: string;
  status: Status;
  reason: string;
  since: string;
  ageHours: number | null;
  ageStatus?: Status;
  last?: string;
  size?: string;
  sizeNote?: string;
  storage?: string;
  verify?: 'ok' | 'failed' | 'none';
  job?: string;
  firing?: string[];
  backups?: {
    hoursAgo: number;
    size: string;
    verify: 'ok' | 'failed' | 'none';
    protected?: boolean;
  }[];
  details?: Detail[];
  history?: HistoryEvent[];
}

function guest(s: GuestSpec): MonObject {
  const verifyText = {
    ok: 'verifiziert',
    failed: 'Verifizierung fehlgeschlagen',
    none: 'nicht verifiziert',
  };
  return {
    key: `${CLUSTER}/guest-backup/${s.vmid}`,
    kind: 'guest-backup',
    name: `${s.vmid} ${s.name}`,
    server: s.node,
    identity: [`${s.type} ${s.vmid}`, `Cluster ${CLUSTER}`, s.storage ?? 'keine Ablage'],
    status: s.status,
    reason: s.reason,
    since: s.since,
    metrics: [
      metric(
        'age',
        'Letztes Backup',
        s.ageHours ?? 'nie',
        { warn: 26 },
        {
          unit: s.ageHours === null ? undefined : 'h',
          note: s.last,
          status: s.ageStatus,
        },
      ),
      metric('size', 'Größe', s.size ?? '—', null, { note: s.sizeNote }),
      metric('storage', 'Ablage', s.storage ?? '—', null, {
        note: s.verify ? verifyText[s.verify] : undefined,
        status: s.verify === 'failed' ? 'warning' : undefined,
      }),
      metric('job', 'Job', s.job ?? 'keiner', null),
    ],
    attributes: [
      { key: 'Cluster', value: CLUSTER },
      { key: 'Node', value: s.node },
      { key: 'Typ', value: s.type },
      { key: 'Schlüssel', value: `${CLUSTER} + VMID ${s.vmid}`, mono: true },
    ],
    details: [
      ...(s.backups
        ? [
            {
              type: 'backups' as const,
              title: 'Backups',
              retention: 'keep-daily 7, keep-weekly 4',
              rows: s.backups.map((b) => ({
                at: ago(b.hoursAgo * HOUR),
                size: b.size,
                storage: s.storage ?? '—',
                verify: b.verify,
                protected: b.protected,
                status: b.verify === 'failed' ? ('warning' as const) : undefined,
              })),
            },
          ]
        : []),
      ...(s.details ?? []),
    ],
    history: s.history,
    rules: withFiring(BACKUP_RULES, s.firing),
  };
}

const GUESTS: MonObject[] = [
  guest({
    vmid: 101,
    name: 'web-01',
    type: 'VM',
    node: 'pve-01',
    status: 'ok',
    reason: 'Gesichert vor 5 h',
    since: ago(5 * HOUR),
    ageHours: 5,
    last: 'heute 04:00',
    size: '38,2 GB',
    sizeNote: '+3 %',
    storage: 'pbs-store',
    verify: 'ok',
    job: 'täglich 02:00',
    backups: [
      { hoursAgo: 5, size: '38,2 GB', verify: 'ok' },
      { hoursAgo: 29, size: '37,1 GB', verify: 'ok' },
      { hoursAgo: 53, size: '37,0 GB', verify: 'ok' },
      { hoursAgo: 173, size: '36,4 GB', verify: 'ok', protected: true },
    ],
    details: [
      {
        type: 'trend',
        title: 'Größe, 30 Tage',
        unit: 'GB',
        points: daily(30, (i) => [37.0, 37.1, 38.2][i - 27] ?? 33 + i * 0.14),
      },
    ],
  }),
  guest({
    vmid: 102,
    name: 'db-01',
    type: 'VM',
    node: 'pve-01',
    status: 'warning',
    reason: 'Kein Backup seit 3 Tagen (Grenze 26 h)',
    since: ago(2 * DAY),
    ageHours: 74,
    ageStatus: 'warning',
    last: 'Sonntag 07:00',
    size: '112 GB',
    storage: 'pbs-store',
    verify: 'ok',
    job: 'täglich 02:00',
    firing: ['backup.age'],
    backups: [
      { hoursAgo: 74, size: '112 GB', verify: 'ok' },
      { hoursAgo: 98, size: '111 GB', verify: 'ok' },
    ],
  }),
  guest({
    vmid: 103,
    name: 'test-01',
    type: 'VM',
    node: 'pve-02',
    status: 'critical',
    reason: 'Nie gesichert',
    since: ago(12 * DAY),
    ageHours: null,
    ageStatus: 'critical',
    job: 'täglich 02:00',
    storage: 'pbs-store',
    firing: ['backup.never'],
  }),
  guest({
    vmid: 104,
    name: 'mail-01',
    type: 'VM',
    node: 'pve-02',
    status: 'critical',
    reason: 'Letzter Lauf fehlgeschlagen: Zielspeicher voll',
    since: ago(7 * HOUR),
    history: [{ at: ago(7 * HOUR), status: 'critical', text: 'Lauf 02:00: Zielspeicher voll' }],
    ageHours: 31,
    ageStatus: 'warning',
    last: 'gestern 02:00',
    size: '64,0 GB',
    storage: 'pbs-store',
    verify: 'ok',
    job: 'täglich 02:00',
    firing: ['backup.failed', 'backup.age'],
    details: [
      {
        type: 'note',
        title: 'Task-Log (Auszug)',
        text: 'ERROR: backup write data failed: command error: No space left on device (os error 28)',
      },
    ],
  }),
  guest({
    vmid: 105,
    name: 'dc-01',
    type: 'VM',
    node: 'pve-01',
    status: 'warning',
    reason: 'Kein Job erfasst diesen Gast',
    since: ago(4 * DAY),
    ageHours: 120,
    ageStatus: 'warning',
    last: 'vor 5 Tagen, von Hand',
    size: '41,7 GB',
    storage: 'pbs-store',
    verify: 'ok',
    firing: ['backup.no_job', 'backup.age'],
  }),
  guest({
    vmid: 106,
    name: 'app-01',
    type: 'CT',
    node: 'pve-02',
    status: 'warning',
    reason: 'Verifizierung fehlgeschlagen',
    since: ago(5 * HOUR),
    ageHours: 6,
    last: 'heute 03:00',
    size: '6,2 GB',
    storage: 'pbs-store',
    verify: 'failed',
    job: 'täglich 02:00',
    firing: ['backup.verify'],
    backups: [
      { hoursAgo: 6, size: '6,2 GB', verify: 'failed' },
      { hoursAgo: 30, size: '6,2 GB', verify: 'ok' },
    ],
  }),
  guest({
    vmid: 107,
    name: 'build-01',
    type: 'VM',
    node: 'pve-02',
    status: 'warning',
    reason: 'Kein Backup seit 12 Tagen (Grenze 26 h)',
    since: ago(11 * DAY),
    ageHours: 288,
    ageStatus: 'warning',
    last: 'vor 12 Tagen',
    size: '22,0 GB',
    storage: 'pbs-store',
    verify: 'ok',
    job: 'täglich 02:00',
    firing: ['backup.age'],
  }),
  guest({
    vmid: 9000,
    name: 'debian-vorlage',
    type: 'VM',
    node: 'pve-01',
    status: 'not-collected',
    reason: 'Nicht geprüft',
    since: ago(60 * DAY),
    ageHours: null,
  }),
];

const JOB_RULES: RuleView[] = [
  {
    key: 'job.errors',
    text: 'Lauf mit Fehlern',
    level: 'critical',
    source: 'Katalog',
    enabled: true,
  },
  {
    key: 'job.missed',
    text: 'Geplanter Lauf ausgeblieben',
    level: 'warning',
    source: 'Katalog',
    enabled: true,
  },
];

const JOBS: MonObject[] = [
  {
    key: `${CLUSTER}/backup-job/backup-3f9a1c`,
    kind: 'backup-job',
    name: 'Täglich alle VMs',
    server: 'pve-01',
    identity: ['Job backup-3f9a1c', `Cluster ${CLUSTER}`, 'täglich 02:00 → pbs-store'],
    status: 'ok',
    reason: 'Letzter Lauf erfolgreich vor 7 h',
    since: ago(7 * HOUR),
    metrics: [
      metric('guests', 'Gäste', 6, null),
      metric('duration', 'Dauer', 42, null, { unit: 'min' }),
      metric('errors', 'Fehler', 0, { crit: 1 }),
      metric('next', 'Nächster Lauf', 'morgen 02:00', null),
    ],
    rules: withFiring(JOB_RULES),
  },
  {
    key: `${CLUSTER}/backup-job/backup-7d2e4b`,
    kind: 'backup-job',
    name: 'Mail und Container',
    server: 'pve-02',
    identity: ['Job backup-7d2e4b', `Cluster ${CLUSTER}`, 'täglich 02:00 → pbs-store'],
    status: 'critical',
    reason: 'Letzter Lauf mit 1 Fehler',
    since: ago(7 * HOUR),
    metrics: [
      metric('guests', 'Gäste', 3, null),
      metric('duration', 'Dauer', 18, null, { unit: 'min' }),
      metric('errors', 'Fehler', 1, { crit: 1 }, { status: 'critical', note: '104 mail-01' }),
      metric('next', 'Nächster Lauf', 'morgen 02:00', null),
    ],
    rules: withFiring(JOB_RULES, ['job.errors']),
  },
];

export const STORAGE_OBJECTS: MonObject[] = [...DISKS, ...POOLS, ...GUESTS, ...JOBS];
