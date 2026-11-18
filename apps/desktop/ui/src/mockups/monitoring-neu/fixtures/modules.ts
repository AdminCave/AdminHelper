// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Catalog modules (Konzept §4.5): one object per module instance, keyed by host, module and
// instance. Level 1 is a sentence in plain words instead of `field = value (op target)`, every
// module shows its metrics with their thresholds. Each family appears twice (offene Frage 7):
// without names, the module only reports counts for the whole instance; with names, every named
// part (database, client, scope, vhost …) is an object of its own, linked by `parent`, and needs
// new agent data: a bounded object list per sensor instead of at most 32 scalars.

import type {
  Detail,
  HistoryEvent,
  Metric,
  MonObject,
  RuleView,
  Status,
  Threshold,
} from '../model';
import { DAY, HOUR, ago } from './time';

export const FAMILIES = [
  'Web/Proxy',
  'Apps',
  'Datenbanken',
  'Mail',
  'Backup-Module',
  'Windows-Rollen',
  'Verzeichnis',
  'Virtualisierung',
  'Netz',
  'Host-Hardware',
  'Generisch',
] as const;
export type Family = (typeof FAMILIES)[number];

function m(
  key: string,
  label: string,
  value: number | string,
  threshold: Threshold | null,
  extra: Partial<Metric> = {},
): Metric {
  return { key, label, value, threshold, ...extra };
}

function rule(
  key: string,
  text: string,
  level: RuleView['level'],
  source: RuleView['source'] = 'Katalog',
  enabled = true,
): RuleView {
  return { key, text, level, source, enabled };
}

interface PartSpec {
  name: string;
  status: Status;
  reason: string;
  since: string;
  badSince?: string;
  metrics: Metric[];
  history?: HistoryEvent[];
}

interface ModuleSpec {
  family: Family;
  module: string;
  /** Compose project, unit, vhost, tcp-<port> or the module id as placeholder. */
  instance: string;
  server: string;
  version?: string;
  status: Status;
  reason: string;
  since: string;
  badSince?: string;
  metrics: Metric[];
  rules: RuleView[];
  firing?: string[];
  details?: Detail[];
  history?: HistoryEvent[];
  raw?: string;
  /** Without names: what the module counts but does not name. */
  counts?: string;
  /** With names: the named parts as objects of their own. */
  parts?: { label: string; items: PartSpec[] };
  /** The names may already leave the agent (vhost names, OPNsense); only the object list is new. */
  namesAllowed?: boolean;
}

function module(s: ModuleSpec): MonObject[] {
  const key = `${s.server}/module/${s.module}/${s.instance}`;
  // The unit or id of the module itself adds nothing: "nginx.service" under nginx reads "nginx".
  const name =
    s.instance.replace(/\.service$/, '') === s.module ? s.module : `${s.module} ${s.instance}`;
  const variant: Detail = s.parts
    ? {
        type: 'note',
        title: 'Mit Namen (offene Frage 7)',
        text: `Jeder Eintrag unter ${s.parts.label} ist ein eigenes Objekt mit eigenem Status, seit und Verlauf. Dafür braucht der Agent eine begrenzte Objektliste je Sensor, heute gibt er höchstens 32 Werte frei${s.namesAllowed ? '; die Namen selbst darf er hier schon melden.' : ', und die Namen dürfen den Agent heute nicht verlassen.'}`,
      }
    : {
        type: 'note',
        title: 'Ohne Namen (offene Frage 7)',
        text: `Der Agent meldet nur Werte für die ganze Instanz: welche ${s.counts} betroffen sind, steht nicht im Objekt.`,
      };
  const parent: MonObject = {
    key,
    kind: 'module',
    name,
    server: s.server,
    identity: [
      `Modul ${s.module}${s.version ? ` ${s.version}` : ''}`,
      s.family,
      `Instanz ${s.instance}`,
    ],
    status: s.status,
    reason: s.reason,
    since: s.since,
    badSince: s.badSince,
    metrics: s.metrics,
    details: [...(s.details ?? []), variant],
    history: s.history,
    rules: s.rules.map((r) => ({ ...r, firing: (s.firing ?? []).includes(r.key) })),
    raw: s.raw,
    family: s.family,
  };
  const parts: MonObject[] = (s.parts?.items ?? []).map((p) => ({
    key: `${key}/${p.name}`,
    kind: 'module',
    name: p.name,
    server: s.server,
    identity: [`${s.parts!.label} in ${name}`, s.family],
    status: p.status,
    reason: p.reason,
    since: p.since,
    badSince: p.badSince,
    metrics: p.metrics.map((x) => ({ ...x, newData: true })),
    history: p.history,
    family: s.family,
    parent: key,
  }));
  return [parent, ...parts];
}

const LATENCY: Threshold = { warn: 500, crit: 2000 };
const PCT_80_95: Threshold = { warn: 80, crit: 95 };

export const MODULE_OBJECTS: MonObject[] = [
  // Web/Proxy -------------------------------------------------------------------------------
  ...module({
    family: 'Web/Proxy',
    module: 'nginx',
    instance: 'nginx.service',
    server: 'web-01',
    version: '1.26.3',
    status: 'critical',
    reason: 'Webserver läuft nicht: nginx.service ist fehlgeschlagen',
    since: ago(45),
    metrics: [
      m('active', 'Aktive Verbindungen', 0, null),
      m('dropped', 'Verworfen seit letztem Lauf', 0, { warn: 1 }),
      m('config', 'Konfiguration', 'nicht prüfbar', null, {
        status: 'unknown',
        note: 'nginx -t: kein Platz auf /var/log',
      }),
      m('vhosts', 'vhosts', 5, null),
    ],
    firing: ['nginx.running'],
    history: [{ at: ago(45), status: 'critical', text: 'nginx.service fehlgeschlagen' }],
    rules: [
      rule('nginx.running', 'Webserver läuft nicht', 'critical'),
      rule('nginx.config', 'Konfiguration lädt nicht (nginx -t)', 'critical'),
      rule('nginx.dropped', 'Verworfene Verbindungen ab 1', 'warning'),
    ],
    counts: 'vhosts',
  }),
  ...module({
    family: 'Web/Proxy',
    module: 'nginx',
    instance: 'nginx.service',
    server: 'web-02',
    version: '1.26.3',
    status: 'warning',
    reason: 'vhost wiki.example.org antwortet mit 502',
    since: ago(40),
    metrics: [
      m('active', 'Aktive Verbindungen', 57, null),
      m('dropped', 'Verworfen seit letztem Lauf', 0, { warn: 1 }),
      m('config', 'Konfiguration', 'lädt (nginx -t)', null),
      m('vhosts', 'vhosts mit Fehler', 1, { warn: 1 }, { status: 'warning' }),
    ],
    rules: [
      rule('nginx.running', 'Webserver läuft nicht', 'critical'),
      rule('nginx.config', 'Konfiguration lädt nicht (nginx -t)', 'critical'),
      rule('nginx.vhost', 'vhost antwortet nicht mit 2xx oder 3xx', 'warning'),
    ],
    firing: ['nginx.vhost'],
    history: [{ at: ago(40), status: 'warning', text: 'wiki.example.org: HTTP 502' }],
    namesAllowed: true,
    parts: {
      label: 'vhosts',
      items: [
        {
          name: 'intranet.example.org',
          status: 'ok',
          reason: 'Antwortet mit 200',
          since: ago(9 * DAY),
          metrics: [
            m('code', 'Antwort', 'HTTP 200', null),
            m('latency', 'Antwortzeit', 240, LATENCY, { unit: 'ms' }),
          ],
        },
        {
          name: 'legacy.example.net',
          status: 'ok',
          reason: 'Antwortet mit 301',
          since: ago(9 * DAY),
          metrics: [
            m('code', 'Antwort', 'HTTP 301', null),
            m('latency', 'Antwortzeit', 31, LATENCY, { unit: 'ms' }),
          ],
        },
        {
          name: 'wiki.example.org',
          status: 'warning',
          reason: 'Antwortet mit 502: das Backend fehlt',
          since: ago(40),
          metrics: [
            m('code', 'Antwort', 'HTTP 502', null, { status: 'warning' }),
            m('latency', 'Antwortzeit', 12, LATENCY, { unit: 'ms' }),
          ],
          history: [{ at: ago(40), status: 'warning', text: 'HTTP 502' }],
        },
      ],
    },
  }),

  // Apps ------------------------------------------------------------------------------------
  ...module({
    family: 'Apps',
    module: 'nextcloud',
    instance: 'nextcloud',
    server: 'app-02',
    version: '31.0.4',
    status: 'warning',
    reason: 'Hintergrundjobs: letzter Lauf vor 14 min',
    since: ago(4),
    metrics: [
      m('status', 'status.php', 'HTTP 200', null),
      m('maintenance', 'Wartungsmodus', 'aus', null),
      m('dbupgrade', 'Datenbank-Upgrade nötig', 'nein', null),
      m(
        'cron',
        'Letzter Cron-Lauf',
        14,
        { warn: 10, crit: 60 },
        { unit: 'min', status: 'warning' },
      ),
    ],
    rules: [
      rule('nextcloud.status', 'status.php antwortet nicht mit 200', 'critical'),
      rule('nextcloud.maintenance', 'Wartungsmodus an', 'warning'),
      rule(
        'nextcloud.cron',
        'Letzter Cron-Lauf: Warnung ab 10 min, kritisch ab 60',
        'warning',
        'eigene',
      ),
    ],
    firing: ['nextcloud.cron'],
    history: [{ at: ago(4), status: 'warning', text: 'Cron-Lauf älter als 10 min' }],
    counts: 'Apps',
  }),
  ...module({
    family: 'Apps',
    module: 'wordpress',
    instance: 'wordpress',
    server: 'web-02',
    version: '6.8.1',
    status: 'warning',
    reason: 'Seite shop.example.org: ein Plugin braucht ein Sicherheitsupdate',
    since: ago(2 * DAY),
    metrics: [
      m('sites', 'Seiten', 3, null),
      m('security', 'Sicherheitsupdates', 1, { warn: 1 }, { status: 'warning' }),
      m('reach', 'Erreichbar', 'HTTP 200', null),
    ],
    rules: [
      rule('wordpress.security', 'Sicherheitsupdate offen', 'warning'),
      rule('wordpress.version', 'Neue Version verfügbar', 'warning', 'Katalog', false),
    ],
    firing: ['wordpress.security'],
    history: [{ at: ago(2 * DAY), status: 'warning', text: 'Sicherheitsupdate für ein Plugin' }],
    parts: {
      label: 'Seiten',
      items: [
        {
          name: 'blog.example.com',
          status: 'ok',
          reason: 'Plugins aktuell',
          since: ago(20 * DAY),
          metrics: [
            m('security', 'Sicherheitsupdates', 0, { warn: 1 }),
            m('plugins', 'Plugins', 14, null),
          ],
        },
        {
          name: 'news.example.net',
          status: 'ok',
          reason: 'Plugins aktuell',
          since: ago(6 * DAY),
          metrics: [
            m('security', 'Sicherheitsupdates', 0, { warn: 1 }),
            m('plugins', 'Plugins', 9, null),
          ],
        },
        {
          name: 'shop.example.org',
          status: 'warning',
          reason: 'Ein Plugin braucht ein Sicherheitsupdate',
          since: ago(2 * DAY),
          metrics: [
            m('security', 'Sicherheitsupdates', 1, { warn: 1 }, { status: 'warning' }),
            m('plugins', 'Plugins', 22, null),
          ],
        },
      ],
    },
  }),

  // Datenbanken -----------------------------------------------------------------------------
  ...module({
    family: 'Datenbanken',
    module: 'postgres',
    instance: 'postgres',
    server: 'db-01',
    version: '17.2',
    status: 'ok',
    reason: 'Antwortet, 62 % der Verbindungen belegt',
    since: ago(3 * HOUR - 3),
    metrics: [
      m('connections', 'Verbindungen', 62, PCT_80_95, { unit: '%' }),
      m('xid', 'Transaktions-ID-Alter', 210, { warn: 1000, crit: 1500 }, { unit: 'Mio' }),
      m('longtx', 'Lange Transaktionen', 0, { warn: 1 }),
      m('databases', 'Datenbanken', 7, null),
    ],
    rules: [
      rule('postgres.up', 'Antwortet nicht', 'critical'),
      rule('postgres.connections', 'Verbindungen: Warnung ab 80 %, kritisch ab 95 %', 'critical'),
      rule(
        'postgres.xid',
        'Transaktions-ID-Alter: Warnung ab 1.000 Mio, kritisch ab 1.500 Mio',
        'critical',
      ),
      rule(
        'postgres.longtx',
        'Transaktionen länger als 15 min (Katalog: 5 min)',
        'warning',
        'Katalog, geändert',
      ),
    ],
    history: [
      { at: ago(3 * HOUR - 3), status: 'ok', text: 'antwortet wieder' },
      { at: ago(3 * HOUR), status: 'critical', text: 'antwortet nicht (OOM-Kill von postgres)' },
    ],
    counts: 'Datenbanken',
  }),
  ...module({
    family: 'Datenbanken',
    module: 'postgres',
    instance: 'postgres',
    server: 'db-02',
    version: '16.6',
    status: 'warning',
    reason: 'Datenbank crm braucht ein VACUUM',
    since: ago(6 * HOUR),
    metrics: [
      m('connections', 'Verbindungen', 38, PCT_80_95, { unit: '%' }),
      m(
        'xid',
        'Transaktions-ID-Alter (höchstes)',
        1210,
        { warn: 1000, crit: 1500 },
        {
          unit: 'Mio',
          status: 'warning',
        },
      ),
      m('longtx', 'Lange Transaktionen', 0, { warn: 1 }),
      m('databases', 'Datenbanken', 3, null),
    ],
    rules: [
      rule('postgres.up', 'Antwortet nicht', 'critical'),
      rule('postgres.connections', 'Verbindungen: Warnung ab 80 %, kritisch ab 95 %', 'critical'),
      rule(
        'postgres.xid',
        'Transaktions-ID-Alter: Warnung ab 1.000 Mio, kritisch ab 1.500 Mio',
        'critical',
      ),
    ],
    firing: ['postgres.xid'],
    history: [
      { at: ago(6 * HOUR), status: 'warning', text: 'crm: Transaktions-ID-Alter über 1.000 Mio' },
    ],
    parts: {
      label: 'Datenbanken',
      items: [
        {
          name: 'analytics',
          status: 'ok',
          reason: 'Größe 4 GB, 2 Verbindungen',
          since: ago(30 * DAY),
          metrics: [
            m('size', 'Größe', 4, null, { unit: 'GB' }),
            m('xid', 'Transaktions-ID-Alter', 95, { warn: 1000, crit: 1500 }, { unit: 'Mio' }),
          ],
        },
        {
          name: 'crm',
          status: 'warning',
          reason: 'Braucht ein VACUUM: Transaktions-ID-Alter 1.210 Mio',
          since: ago(6 * HOUR),
          metrics: [
            m('size', 'Größe', 31, null, { unit: 'GB' }),
            m(
              'xid',
              'Transaktions-ID-Alter',
              1210,
              { warn: 1000, crit: 1500 },
              {
                unit: 'Mio',
                status: 'warning',
              },
            ),
          ],
          history: [{ at: ago(6 * HOUR), status: 'warning', text: 'über 1.000 Mio' }],
        },
        {
          name: 'shop',
          status: 'ok',
          reason: 'Größe 18 GB, 12 Verbindungen',
          since: ago(30 * DAY),
          metrics: [
            m('size', 'Größe', 18, null, { unit: 'GB' }),
            m('xid', 'Transaktions-ID-Alter', 180, { warn: 1000, crit: 1500 }, { unit: 'Mio' }),
          ],
        },
      ],
    },
  }),

  // Mail ------------------------------------------------------------------------------------
  ...module({
    family: 'Mail',
    module: 'postfix',
    instance: 'postfix.service',
    server: 'mail-01',
    version: '3.9.1',
    status: 'warning',
    reason: 'Queue staut: 120 verzögert',
    since: ago(2 * HOUR),
    metrics: [
      m('deferred', 'Verzögert', 120, { warn: 100, crit: 1000 }, { status: 'warning' }),
      m(
        'oldest',
        'Älteste verzögerte',
        26,
        { warn: 24, crit: 96 },
        { unit: 'h', status: 'warning' },
      ),
      m('active', 'Aktiv', 3, null),
      m('smtp', 'SMTP-Antwort', '220', null),
    ],
    rules: [
      rule('postfix.deferred', 'Verzögert: Warnung ab 100, kritisch ab 1.000', 'critical'),
      rule(
        'postfix.oldest',
        'Älteste verzögerte: Warnung ab 1 Tag, kritisch ab 4 Tagen',
        'critical',
      ),
      rule('postfix.smtp', 'SMTP antwortet nicht mit 220', 'critical'),
    ],
    firing: ['postfix.deferred', 'postfix.oldest'],
    history: [{ at: ago(2 * HOUR), status: 'warning', text: 'über 100 verzögert' }],
    details: [
      {
        type: 'note',
        title: 'Heute stünde hier',
        text: 'deferred = 120 (gt 100)',
      },
    ],
    raw: JSON.stringify(
      { deferred: 120, active: 3, oldest_deferred_s: 93600, smtp_banner: '220 mail-01 ESMTP' },
      null,
      2,
    ),
    counts: 'Ziel-Domains',
  }),
  ...module({
    family: 'Mail',
    module: 'postfix',
    instance: 'postfix.service',
    server: 'mail-02',
    version: '3.9.1',
    status: 'warning',
    reason: 'Queue staut zu example.net: 84 verzögert',
    since: ago(5 * HOUR),
    metrics: [
      m('deferred', 'Verzögert', 84, { warn: 50, crit: 500 }, { status: 'warning' }),
      m('oldest', 'Älteste verzögerte', 5, { warn: 24, crit: 96 }, { unit: 'h' }),
      m('active', 'Aktiv', 0, null),
      m('smtp', 'SMTP-Antwort', '220', null),
    ],
    rules: [
      rule(
        'postfix.deferred',
        'Verzögert: Warnung ab 50, kritisch ab 500 (Katalog: 100/1.000)',
        'critical',
        'Katalog, geändert',
      ),
      rule(
        'postfix.oldest',
        'Älteste verzögerte: Warnung ab 1 Tag, kritisch ab 4 Tagen',
        'critical',
      ),
    ],
    firing: ['postfix.deferred'],
    history: [{ at: ago(5 * HOUR), status: 'warning', text: 'example.net: über 50 verzögert' }],
    parts: {
      label: 'Ziel-Domains',
      items: [
        {
          name: 'example.com',
          status: 'ok',
          reason: 'Keine verzögert',
          since: ago(14 * DAY),
          metrics: [m('deferred', 'Verzögert', 0, { warn: 50, crit: 500 })],
        },
        {
          name: 'example.net',
          status: 'warning',
          reason: '84 verzögert, die älteste seit 5 h',
          since: ago(5 * HOUR),
          metrics: [
            m('deferred', 'Verzögert', 84, { warn: 50, crit: 500 }, { status: 'warning' }),
            m('answer', 'Letzte Antwort', '451 4.7.1 Try again later', null),
          ],
        },
        {
          name: 'example.org',
          status: 'ok',
          reason: 'Keine verzögert',
          since: ago(14 * DAY),
          metrics: [m('deferred', 'Verzögert', 0, { warn: 50, crit: 500 })],
        },
      ],
    },
  }),

  // Backup-Module ---------------------------------------------------------------------------
  ...module({
    family: 'Backup-Module',
    module: 'restic',
    instance: 'restic-backup.service',
    server: 'backup-01',
    version: '0.17.3',
    status: 'warning',
    reason: 'Letzte Sicherung vor 27 h (Soll höchstens 26 h)',
    since: ago(HOUR),
    metrics: [
      m('age', 'Alter letzter Lauf', 27, { warn: 26, crit: 50 }, { unit: 'h', status: 'warning' }),
      m('result', 'Laufergebnis', 'erfolgreich', null),
      m('snapshot', 'Alter Snapshot', 27, { warn: 26, crit: 50 }, { unit: 'h', status: 'warning' }),
      m('snapshots', 'Snapshots', 412, null),
    ],
    rules: [
      rule(
        'restic.age',
        'Letzter Lauf: Warnung ab 26 h, kritisch ab 50 h (Katalog: 24 h)',
        'warning',
        'Katalog, geändert',
      ),
      rule('restic.result', 'Lauf fehlgeschlagen', 'critical'),
    ],
    firing: ['restic.age'],
    history: [{ at: ago(HOUR), status: 'warning', text: 'kein Lauf seit 26 h' }],
    counts: 'Quellen',
  }),
  ...module({
    family: 'Backup-Module',
    module: 'urbackup',
    instance: 'urbackupsrv.service',
    server: 'backup-02',
    version: '2.5.33',
    status: 'critical',
    reason: 'Client laptop-03 seit 9 Tagen ohne Sicherung',
    since: ago(6 * DAY),
    badSince: ago(9 * DAY - 26 * HOUR),
    metrics: [
      m('clients', 'Clients', 3, null),
      m('overdue', 'Überfällig', 1, { crit: 1 }, { status: 'critical' }),
      m('storage', 'Speicher belegt', 64, { warn: 80, crit: 90 }, { unit: '%' }),
    ],
    rules: [
      rule(
        'urbackup.overdue',
        'Client ohne Sicherung: Warnung ab 26 h, kritisch ab 3 Tagen',
        'critical',
      ),
      rule('urbackup.storage', 'Speicher: Warnung ab 80 %, kritisch ab 90 %', 'critical'),
    ],
    firing: ['urbackup.overdue'],
    history: [
      { at: ago(6 * DAY), status: 'critical', text: 'laptop-03: 3 Tage ohne Sicherung' },
      { at: ago(9 * DAY - 26 * HOUR), status: 'warning', text: 'laptop-03: 26 h ohne Sicherung' },
    ],
    parts: {
      label: 'Clients',
      items: [
        {
          name: 'buero-pc-01',
          status: 'ok',
          reason: 'Letzte Sicherung vor 5 h',
          since: ago(40 * DAY),
          metrics: [m('age', 'Letzte Sicherung', 5, { warn: 26, crit: 72 }, { unit: 'h' })],
        },
        {
          name: 'buero-pc-02',
          status: 'ok',
          reason: 'Letzte Sicherung vor 7 h',
          since: ago(40 * DAY),
          metrics: [m('age', 'Letzte Sicherung', 7, { warn: 26, crit: 72 }, { unit: 'h' })],
        },
        {
          name: 'laptop-03',
          status: 'critical',
          reason: 'Seit 9 Tagen ohne Sicherung',
          since: ago(6 * DAY),
          badSince: ago(9 * DAY - 26 * HOUR),
          metrics: [
            m(
              'age',
              'Letzte Sicherung',
              216,
              { warn: 26, crit: 72 },
              { unit: 'h', status: 'critical' },
            ),
            m('seen', 'Zuletzt online', 'vor 9 Tagen', null),
          ],
        },
      ],
    },
  }),

  // Windows-Rollen --------------------------------------------------------------------------
  ...module({
    family: 'Windows-Rollen',
    module: 'windows-dhcp',
    instance: 'windows-dhcp',
    server: 'dc-01',
    status: 'warning',
    reason: '1 von 4 Bereichen zu 92 % belegt',
    since: ago(3 * HOUR),
    metrics: [
      m('scopes', 'Bereiche', 4, null),
      m('full', 'Bereiche ab 85 %', 1, { warn: 1 }, { status: 'warning' }),
      m('max', 'Höchste Belegung', 92, { warn: 85, crit: 95 }, { unit: '%', status: 'warning' }),
    ],
    rules: [
      rule('dhcp.usage', 'Belegung eines Bereichs: Warnung ab 85 %, kritisch ab 95 %', 'critical'),
      rule('dhcp.empty', 'Keine Bereiche gemeldet', 'warning', 'eigene'),
    ],
    firing: ['dhcp.usage'],
    history: [{ at: ago(3 * HOUR), status: 'warning', text: 'ein Bereich über 85 %' }],
    counts: 'Bereiche',
  }),
  ...module({
    family: 'Windows-Rollen',
    module: 'windows-dhcp',
    instance: 'windows-dhcp',
    server: 'dc-02',
    status: 'warning',
    reason: 'Bereich 192.0.2.0/24 zu 92 % belegt',
    since: ago(3 * HOUR),
    metrics: [
      m('scopes', 'Bereiche', 3, null),
      m('full', 'Bereiche ab 85 %', 1, { warn: 1 }, { status: 'warning' }),
      m('max', 'Höchste Belegung', 92, { warn: 85, crit: 95 }, { unit: '%', status: 'warning' }),
    ],
    rules: [
      rule('dhcp.usage', 'Belegung eines Bereichs: Warnung ab 85 %, kritisch ab 95 %', 'critical'),
    ],
    firing: ['dhcp.usage'],
    history: [{ at: ago(3 * HOUR), status: 'warning', text: '192.0.2.0/24 über 85 %' }],
    parts: {
      label: 'Bereiche',
      items: [
        {
          name: '192.0.2.0/24',
          status: 'warning',
          reason: 'Zu 92 % belegt, 19 Adressen frei',
          since: ago(3 * HOUR),
          metrics: [
            m('usage', 'Belegung', 92, { warn: 85, crit: 95 }, { unit: '%', status: 'warning' }),
            m('free', 'Frei', 19, null),
          ],
        },
        {
          name: '198.51.100.0/24',
          status: 'ok',
          reason: 'Zu 40 % belegt',
          since: ago(30 * DAY),
          metrics: [
            m('usage', 'Belegung', 40, { warn: 85, crit: 95 }, { unit: '%' }),
            m('free', 'Frei', 151, null),
          ],
        },
        {
          name: '203.0.113.0/24',
          status: 'ok',
          reason: 'Zu 12 % belegt',
          since: ago(30 * DAY),
          metrics: [
            m('usage', 'Belegung', 12, { warn: 85, crit: 95 }, { unit: '%' }),
            m('free', 'Frei', 223, null),
          ],
        },
      ],
    },
  }),

  // Verzeichnis -----------------------------------------------------------------------------
  ...module({
    family: 'Verzeichnis',
    module: 'samba-ad-dc',
    instance: 'samba-ad-dc.service',
    server: 'dc-03',
    version: '4.21.4',
    status: 'critical',
    reason: 'Replikation seit 13 h ohne Erfolg',
    since: ago(HOUR),
    badSince: ago(11 * HOUR),
    metrics: [
      m('links', 'Fehlerhafte Links', 2, { crit: 1 }, { status: 'critical' }),
      m('success', 'Letzter Erfolg', 13, { warn: 2, crit: 12 }, { unit: 'h', status: 'critical' }),
      m('fsmo', 'FSMO-Rollen', '5 auf diesem Server', null),
    ],
    rules: [
      rule(
        'samba.repl',
        'Letzte erfolgreiche Replikation: Warnung ab 2 h, kritisch ab 12 h',
        'critical',
      ),
      rule('samba.links', 'Fehlerhafte Replikations-Links ab 1', 'critical'),
    ],
    firing: ['samba.repl', 'samba.links'],
    history: [
      { at: ago(HOUR), status: 'critical', text: '12 h ohne Erfolg' },
      { at: ago(11 * HOUR), status: 'warning', text: '2 h ohne Erfolg' },
    ],
    counts: 'Replikationspartner',
  }),
  ...module({
    family: 'Verzeichnis',
    module: 'samba-ad-dc',
    instance: 'samba-ad-dc.service',
    server: 'dc-04',
    version: '4.21.4',
    status: 'critical',
    reason: 'Replikation mit dc-03 seit 13 h ohne Erfolg',
    since: ago(HOUR),
    badSince: ago(11 * HOUR),
    metrics: [
      m('links', 'Fehlerhafte Links', 1, { crit: 1 }, { status: 'critical' }),
      m(
        'success',
        'Letzter Erfolg (ältester)',
        13,
        { warn: 2, crit: 12 },
        { unit: 'h', status: 'critical' },
      ),
      m('fsmo', 'FSMO-Rollen', 'keine', null),
    ],
    rules: [
      rule(
        'samba.repl',
        'Letzte erfolgreiche Replikation: Warnung ab 2 h, kritisch ab 12 h',
        'critical',
      ),
      rule('samba.links', 'Fehlerhafte Replikations-Links ab 1', 'critical'),
    ],
    firing: ['samba.repl', 'samba.links'],
    history: [
      { at: ago(HOUR), status: 'critical', text: 'dc-03: 12 h ohne Erfolg' },
      { at: ago(11 * HOUR), status: 'warning', text: 'dc-03: 2 h ohne Erfolg' },
    ],
    parts: {
      label: 'Replikationspartner',
      items: [
        {
          name: 'dc-03',
          status: 'critical',
          reason: 'Seit 13 h ohne Erfolg',
          since: ago(HOUR),
          badSince: ago(11 * HOUR),
          metrics: [
            m(
              'success',
              'Letzter Erfolg',
              13,
              { warn: 2, crit: 12 },
              { unit: 'h', status: 'critical' },
            ),
            m('fails', 'Fehlschläge in Folge', 52, null),
          ],
        },
        {
          name: 'dc-05',
          status: 'ok',
          reason: 'Letzter Erfolg vor 4 min',
          since: ago(20 * DAY),
          metrics: [
            m('success', 'Letzter Erfolg', 0.1, { warn: 2, crit: 12 }, { unit: 'h' }),
            m('fails', 'Fehlschläge in Folge', 0, null),
          ],
        },
      ],
    },
  }),

  // Virtualisierung -------------------------------------------------------------------------
  ...module({
    family: 'Virtualisierung',
    module: 'proxmox-ve',
    instance: 'pve-cluster.service',
    server: 'pve-01',
    version: '9.1',
    status: 'ok',
    reason: 'Beschlussfähig, 3 von 3 Knoten online',
    since: ago(30 * DAY),
    metrics: [
      m('nodes', 'Knoten online', '3 von 3', null),
      m('quorum', 'Quorum', 'ja', null),
      m('autostart', 'Gäste aus trotz Autostart', 0, { warn: 1 }),
      m('updates', 'Updates', 4, null, { note: 'nur Hinweis' }),
    ],
    rules: [
      rule('pve.quorum', 'Cluster nicht beschlussfähig', 'critical'),
      rule('pve.autostart', 'Gast mit Autostart läuft nicht', 'warning'),
    ],
    counts: 'Knoten',
  }),
  ...module({
    family: 'Virtualisierung',
    module: 'proxmox-ve',
    instance: 'pve-cluster.service',
    server: 'pve-02',
    version: '9.1',
    status: 'warning',
    reason: 'Knoten pve-05 offline seit 22 min',
    since: ago(22),
    metrics: [
      m('nodes', 'Knoten online', '2 von 3', null, { status: 'warning' }),
      m('quorum', 'Quorum', 'ja', null),
      m('autostart', 'Gäste aus trotz Autostart', 3, { warn: 1 }, { status: 'warning' }),
    ],
    rules: [
      rule('pve.quorum', 'Cluster nicht beschlussfähig', 'critical'),
      rule('pve.node', 'Knoten offline', 'warning'),
      rule('pve.autostart', 'Gast mit Autostart läuft nicht', 'warning'),
    ],
    firing: ['pve.node', 'pve.autostart'],
    history: [{ at: ago(22), status: 'warning', text: 'pve-05 offline' }],
    parts: {
      label: 'Knoten',
      items: [
        {
          name: 'pve-02',
          status: 'ok',
          reason: 'Online, 14 Gäste',
          since: ago(30 * DAY),
          metrics: [
            m('online', 'Online', 'ja', null),
            m('ram', 'RAM', 71, { warn: 90, crit: 98 }, { unit: '%' }),
          ],
        },
        {
          name: 'pve-05',
          status: 'warning',
          reason: 'Offline seit 22 min',
          since: ago(22),
          metrics: [
            m('online', 'Online', 'nein', null, { status: 'warning' }),
            m('guests', 'Gäste aus trotz Autostart', 3, { warn: 1 }, { status: 'warning' }),
          ],
          history: [{ at: ago(22), status: 'warning', text: 'offline' }],
        },
        {
          name: 'pve-06',
          status: 'ok',
          reason: 'Online, 9 Gäste',
          since: ago(30 * DAY),
          metrics: [
            m('online', 'Online', 'ja', null),
            m('ram', 'RAM', 64, { warn: 90, crit: 98 }, { unit: '%' }),
          ],
        },
      ],
    },
  }),

  // Netz ------------------------------------------------------------------------------------
  ...module({
    family: 'Netz',
    module: 'wireguard',
    instance: 'wireguard',
    server: 'fw-02',
    status: 'warning',
    reason: '1 von 5 Tunneln ohne Handshake seit 2 h',
    since: ago(114),
    metrics: [
      m('tunnels', 'Tunnel', 5, null),
      m('stale', 'Ohne Handshake', 1, { warn: 1 }, { status: 'warning' }),
      m('oldest', 'Ältester Handshake', 124, { warn: 10 }, { unit: 'min', status: 'warning' }),
    ],
    rules: [rule('wireguard.handshake', 'Tunnel ohne Handshake seit 10 min', 'warning')],
    firing: ['wireguard.handshake'],
    history: [{ at: ago(114), status: 'warning', text: 'ein Tunnel ohne Handshake' }],
    counts: 'Tunnel',
  }),
  ...module({
    family: 'Netz',
    module: 'opnsense',
    instance: 'opnsense',
    server: 'fw-01',
    version: '26.1.4',
    status: 'critical',
    reason: 'Gateway WAN2 ausgefallen',
    since: ago(12),
    metrics: [
      m('down', 'Gateways ausgefallen', 1, { crit: 1 }, { status: 'critical' }),
      m('stopped', 'Gestoppte Dienste', 0, { warn: 1 }),
      m('states', 'States', 41, PCT_80_95, { unit: '%' }),
      m('update', 'Update', '26.1.5 verfügbar', null, { note: 'nur Hinweis' }),
    ],
    rules: [
      rule('opnsense.gateway', 'Gateway ausgefallen', 'critical'),
      rule('opnsense.services', 'Dienst gestoppt', 'warning'),
      rule('opnsense.states', 'States: Warnung ab 80 %, kritisch ab 95 %', 'critical'),
    ],
    firing: ['opnsense.gateway'],
    history: [{ at: ago(12), status: 'critical', text: 'WAN2 ausgefallen' }],
    namesAllowed: true,
    parts: {
      label: 'Gateways',
      items: [
        {
          name: 'WAN1',
          status: 'ok',
          reason: 'Online, 8 ms',
          since: ago(21 * DAY),
          metrics: [
            m('loss', 'Verlust', 0, { warn: 20, crit: 100 }, { unit: '%' }),
            m('latency', 'Antwortzeit', 8, LATENCY, { unit: 'ms' }),
          ],
        },
        {
          name: 'WAN2',
          status: 'critical',
          reason: 'Ausgefallen seit 12 min',
          since: ago(12),
          metrics: [
            m('loss', 'Verlust', 100, { warn: 20, crit: 100 }, { unit: '%', status: 'critical' }),
            m('latency', 'Antwortzeit', '–', null),
          ],
          history: [{ at: ago(12), status: 'critical', text: 'ausgefallen' }],
        },
      ],
    },
  }),

  // Host-Hardware ---------------------------------------------------------------------------
  ...module({
    family: 'Host-Hardware',
    module: 'mdadm',
    instance: 'mdadm',
    server: 'build-01',
    status: 'critical',
    reason: '1 von 2 Verbünden läuft ohne Redundanz',
    since: ago(5 * HOUR),
    metrics: [
      m('arrays', 'Verbünde', 2, null),
      m('degraded', 'Ohne Redundanz', 1, { crit: 1 }, { status: 'critical' }),
      m('resync', 'Wiederaufbau', 'keiner', null),
    ],
    rules: [rule('mdadm.degraded', 'Verbund ohne Redundanz', 'critical')],
    firing: ['mdadm.degraded'],
    history: [{ at: ago(5 * HOUR), status: 'critical', text: 'ein Verbund ohne Redundanz' }],
    counts: 'Verbünde',
  }),
  ...module({
    family: 'Host-Hardware',
    module: 'mdadm',
    instance: 'mdadm',
    server: 'web-02',
    status: 'ok',
    reason: 'Alle Verbünde sauber, Prüflauf auf md1 bei 62 %',
    since: ago(90 * DAY),
    metrics: [
      m('arrays', 'Verbünde', 2, null),
      m('degraded', 'Ohne Redundanz', 0, { crit: 1 }),
      m('resync', 'Prüflauf', 'md1, 62 %', null),
    ],
    rules: [rule('mdadm.degraded', 'Verbund ohne Redundanz', 'critical')],
    parts: {
      label: 'Verbünde',
      items: [
        {
          name: 'md0',
          status: 'ok',
          reason: 'Sauber, 2 von 2 Platten',
          since: ago(90 * DAY),
          metrics: [
            m('disks', 'Platten aktiv', '2 von 2', null),
            m('missing', 'Fehlend', 0, { crit: 1 }),
          ],
        },
        {
          name: 'md1',
          status: 'ok',
          reason: 'Sauber, Prüflauf bei 62 %',
          since: ago(90 * DAY),
          metrics: [
            m('disks', 'Platten aktiv', '2 von 2', null),
            m('missing', 'Fehlend', 0, { crit: 1 }),
            m('check', 'Prüflauf', 62, null, { unit: '%' }),
          ],
        },
      ],
    },
  }),

  // Generisch -------------------------------------------------------------------------------
  ...module({
    family: 'Generisch',
    module: 'port',
    instance: 'tcp-5432',
    server: 'db-01',
    status: 'ok',
    reason: 'Port 5432 antwortet',
    since: ago(3 * HOUR - 3),
    metrics: [
      m('open', 'Port', 'offen', null),
      m('latency', 'Antwortzeit', 2, LATENCY, { unit: 'ms' }),
    ],
    rules: [rule('port.open', 'Port antwortet nicht', 'critical')],
    history: [
      { at: ago(3 * HOUR - 3), status: 'ok', text: 'antwortet wieder' },
      { at: ago(3 * HOUR), status: 'critical', text: 'antwortet nicht' },
    ],
    counts: 'Verbindungen',
  }),
  ...module({
    family: 'Generisch',
    module: 'pm2',
    instance: 'pm2',
    server: 'app-02',
    version: '6.0.5',
    status: 'critical',
    reason: 'Prozess worker gestoppt nach 15 Neustarts',
    since: ago(50),
    metrics: [
      m('processes', 'Prozesse', 2, null),
      m('down', 'Nicht online', 1, { crit: 1 }, { status: 'critical' }),
    ],
    rules: [
      rule('pm2.down', 'Prozess nicht online', 'critical'),
      rule('pm2.restarts', 'Neustarts: Warnung ab 3, kritisch ab 10', 'critical'),
    ],
    firing: ['pm2.down', 'pm2.restarts'],
    history: [{ at: ago(50), status: 'critical', text: 'worker: errored nach 15 Neustarts' }],
    parts: {
      label: 'Prozesse',
      items: [
        {
          name: 'api',
          status: 'ok',
          reason: 'Läuft seit 3 Tagen',
          since: ago(3 * DAY),
          metrics: [
            m('state', 'Zustand', 'online', null),
            m('restarts', 'Neustarts', 0, { warn: 3, crit: 10 }),
            m('mem', 'RAM', 182, null, { unit: 'MB' }),
          ],
        },
        {
          name: 'worker',
          status: 'critical',
          reason: 'Gestoppt nach 15 Neustarts',
          since: ago(50),
          metrics: [
            m('state', 'Zustand', 'errored', null, { status: 'critical' }),
            m('restarts', 'Neustarts', 15, { warn: 3, crit: 10 }, { status: 'critical' }),
          ],
          history: [{ at: ago(50), status: 'critical', text: 'errored' }],
        },
      ],
    },
  }),
];
