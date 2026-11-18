// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Certificates, domains and endpoints (Konzept §4.6). These objects are not bound to one agent: a
// certificate is keyed by its SHA-256 (else host:port) and merges every source into one rating, a
// domain merges rdap, dns, mail_dns, dnsbl and web_domain. `server` names the host they belong to.

import type {
  Attribute,
  Detail,
  HistoryEvent,
  Metric,
  MonObject,
  RuleView,
  Status,
  Threshold,
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

function rule(
  key: string,
  text: string,
  level: RuleView['level'],
  source: RuleView['source'] = 'Katalog',
): RuleView {
  return { key, text, level, source, enabled: true };
}

function withFiring(rules: RuleView[], firing: string[] = []): RuleView[] {
  return rules.map((r) => ({ ...r, firing: firing.includes(r.key) }));
}

// ---------------------------------------------------------------------------------------------
// certificate

const CERT_RULES: RuleView[] = [
  rule(
    'cert.expiry',
    'Restlaufzeit: Warnung unter 25 %, kritisch unter 10 % der Laufzeit, mindestens 12 h',
    'critical',
  ),
  rule('cert.chain', 'Kette unvollständig', 'warning'),
  rule('cert.name', 'Name passt nicht zum Zertifikat', 'critical'),
];

/** Offene Frage 6: relative to the lifetime (25 %/10 %), never under 12 h. */
function expiryThreshold(lifetimeDays: number): Threshold {
  return {
    warn: Math.max(0.5, Math.floor(lifetimeDays * 0.25)),
    crit: Math.max(0.5, Math.floor(lifetimeDays * 0.1)),
    below: true,
  };
}

interface CertSpec {
  key: string;
  name: string;
  server: string;
  status: Status;
  reason: string;
  since: string;
  badSince?: string;
  daysLeft: number;
  lifetimeDays: number;
  until: string;
  issuer: string;
  nameMatch: string;
  nameStatus?: Status;
  sources: string[];
  extra?: Attribute[];
  history?: HistoryEvent[];
  firing?: string[];
}

function certificate(s: CertSpec): MonObject {
  const t = expiryThreshold(s.lifetimeDays);
  const expiryStatus: Status =
    s.daysLeft < t.crit! ? 'critical' : s.daysLeft < t.warn! ? 'warning' : 'ok';
  return {
    key: `certificate/${s.key}`,
    kind: 'certificate',
    name: s.name,
    server: s.server,
    identity: [
      s.issuer,
      `${s.lifetimeDays} Tage Laufzeit`,
      s.sources.length === 1 ? '1 Quelle' : `${s.sources.length} Quellen`,
    ],
    status: s.status,
    reason: s.reason,
    since: s.since,
    badSince: s.badSince,
    metrics: [
      metric('days', 'Gültig noch', s.daysLeft, t, {
        unit: 'Tage',
        status: expiryStatus,
        note: `bis ${s.until}`,
      }),
      metric('issuer', 'Aussteller', s.issuer, null),
      metric('name', 'Name/SAN', s.nameMatch, null, s.nameStatus ? { status: s.nameStatus } : {}),
      metric('sources', 'Quellen', s.sources.length, null),
    ],
    attributes: [
      { key: 'Schlüssel', value: s.key, mono: true },
      { key: 'Quellen', value: s.sources.join(' · ') },
      {
        key: 'Bewertung',
        value: `eine für alle Quellen: Warnung unter ${t.warn} Tagen, kritisch unter ${t.crit} (25 %/10 % von ${s.lifetimeDays} Tagen)`,
      },
      ...(s.extra ?? []),
    ],
    history: s.history,
    rules: withFiring(CERT_RULES, s.firing),
  };
}

export const CERTIFICATES: MonObject[] = [
  certificate({
    key: 'sha256:5c1e9a7f3b2d',
    name: 'shop.example.com',
    server: 'web-01',
    status: 'ok',
    reason: 'Gültig noch 41 Tage',
    since: ago(49 * DAY),
    daysLeft: 41,
    lifetimeDays: 90,
    until: '29.12.2026',
    issuer: 'Beispiel-CA R3',
    nameMatch: 'passt (shop.example.com, www.shop.example.com)',
    sources: [
      'zentral tls 203.0.113.10:443',
      'Modul nginx auf web-01 (vhost shop.example.com)',
      'Modul web_domain auf web-01',
    ],
  }),
  certificate({
    key: 'sha256:9e4b0c2a6d81',
    name: 'mail.example.com',
    server: 'mail-01',
    status: 'warning',
    reason: 'Läuft in 14 Tagen ab',
    since: ago(8 * DAY),
    daysLeft: 14,
    lifetimeDays: 90,
    until: '02.12.2026',
    issuer: 'Beispiel-CA R3',
    nameMatch: 'passt (mail.example.com)',
    sources: [
      'zentral smtp 192.0.2.25:25 (STARTTLS)',
      'zentral imap 192.0.2.25:993',
      'Modul postfix auf mail-01',
    ],
    extra: [{ key: 'Erneuerung', value: 'letzter Versuch vor 2 Tagen gescheitert (certbot)' }],
    firing: ['cert.expiry'],
    history: [{ at: ago(8 * DAY), status: 'warning', text: 'unter 22 Tagen' }],
  }),
  certificate({
    key: 'sha256:2f7d4a9c1e63',
    name: 'intranet.example.org',
    server: 'web-02',
    status: 'critical',
    reason: 'Läuft in 6 Tagen ab',
    since: ago(3 * DAY),
    badSince: ago(16 * DAY),
    daysLeft: 6,
    lifetimeDays: 90,
    until: '24.11.2026',
    issuer: 'Beispiel-CA R3',
    nameMatch: 'passt (intranet.example.org)',
    sources: [
      'zentral tls 198.51.100.30:443',
      'Modul nginx auf web-02 (vhost intranet.example.org)',
    ],
    firing: ['cert.expiry'],
    history: [
      { at: ago(3 * DAY), status: 'critical', text: 'unter 9 Tagen' },
      { at: ago(16 * DAY), status: 'warning', text: 'unter 22 Tagen' },
    ],
  }),
  certificate({
    key: 'sha256:7a0c5e3b9f12',
    name: 'vpn.example.net',
    server: 'fw-01',
    status: 'warning',
    reason: 'Läuft in 80 Tagen ab',
    since: ago(11 * DAY),
    daysLeft: 80,
    lifetimeDays: 365,
    until: '06.02.2027',
    issuer: 'Beispiel-CA Business',
    nameMatch: 'passt (vpn.example.net)',
    sources: ['zentral tls 203.0.113.1:443', 'Modul opnsense auf fw-01'],
    firing: ['cert.expiry'],
    history: [{ at: ago(11 * DAY), status: 'warning', text: 'unter 91 Tagen (25 % von 365)' }],
  }),
  certificate({
    key: 'sha256:c4e8a1d6b0f7',
    name: 'api.example.com',
    server: 'app-02',
    status: 'warning',
    reason: 'Kette unvollständig: Zwischenzertifikat fehlt',
    since: ago(2 * DAY),
    daysLeft: 63,
    lifetimeDays: 90,
    until: '20.01.2027',
    issuer: 'Beispiel-CA R3',
    nameMatch: 'passt (api.example.com)',
    sources: ['zentral tls 192.0.2.40:443', 'Modul traefik auf app-02'],
    extra: [{ key: 'Kette', value: 'nur Blatt-Zertifikat ausgeliefert, R3 fehlt' }],
    firing: ['cert.chain'],
    history: [
      {
        at: ago(2 * DAY),
        status: 'warning',
        text: 'Kette unvollständig nach Neustart von traefik',
      },
    ],
  }),
  certificate({
    key: 'sha256:e1b7f4c9a352',
    name: 'legacy.example.net',
    server: 'web-02',
    status: 'critical',
    reason: 'Name passt nicht: Zertifikat gilt für old.example.net',
    since: ago(5 * HOUR),
    daysLeft: 120,
    lifetimeDays: 365,
    until: '18.03.2027',
    issuer: 'Beispiel-CA Business',
    nameMatch: 'passt nicht (old.example.net)',
    nameStatus: 'critical',
    sources: ['zentral tls 198.51.100.30:443 (SNI legacy.example.net)'],
    firing: ['cert.name'],
    history: [
      {
        at: ago(5 * HOUR),
        status: 'critical',
        text: 'Name legacy.example.net nicht im Zertifikat',
      },
    ],
  }),
  certificate({
    // Only an agent module reports it, without fingerprint: the key falls back to host:port.
    key: 'app-02:8443',
    name: 'app-02:8443',
    server: 'app-02',
    status: 'ok',
    reason: 'Gültig noch 63 Tage',
    since: ago(27 * DAY),
    daysLeft: 63,
    lifetimeDays: 90,
    until: '20.01.2027',
    issuer: 'unbekannt',
    nameMatch: 'nicht geprüft',
    sources: ['Modul traefik auf app-02 (nur Restlaufzeit)'],
  }),
];

// ---------------------------------------------------------------------------------------------
// domain

const DOMAIN_RULES: RuleView[] = [
  rule(
    'domain.expiry',
    'Registrierung: Warnung unter 30 Tagen, kritisch unter 7',
    'critical',
    'Katalog, geändert',
  ),
  rule('domain.dnsbl', 'Auf einer Blockliste', 'critical'),
  rule('domain.dns', 'Nameserver antworten verschieden', 'warning'),
  rule('domain.dmarc', 'Kein DMARC-Eintrag', 'warning', 'eigene'),
  { ...rule('domain.dnssec', 'Zone nicht signiert (DNSSEC)', 'warning'), enabled: false },
];

interface DomainSpec {
  name: string;
  server: string;
  status: Status;
  reason: string;
  since: string;
  regDays: number;
  regUntil: string;
  dnssec: string;
  mail: string;
  mailStatus?: Status;
  blocklists: number;
  firing?: string[];
  history?: HistoryEvent[];
  details?: Detail[];
}

function domain(s: DomainSpec): MonObject {
  return {
    key: `domain/${s.name}`,
    kind: 'domain',
    name: s.name,
    server: s.server,
    identity: ['Beispiel-Registrar', 'rdap · dns · mail_dns · dnsbl · web_domain'],
    status: s.status,
    reason: s.reason,
    since: s.since,
    metrics: [
      metric(
        'registration',
        'Registriert noch',
        s.regDays,
        { warn: 30, crit: 7, below: true },
        {
          unit: 'Tage',
          note: `bis ${s.regUntil}`,
          status: s.regDays < 7 ? 'critical' : s.regDays < 30 ? 'warning' : 'ok',
        },
      ),
      metric('dnssec', 'DNSSEC', s.dnssec, null),
      metric('mail', 'MX/SPF/DMARC', s.mail, null, s.mailStatus ? { status: s.mailStatus } : {}),
      metric(
        'dnsbl',
        'Blocklisten',
        s.blocklists,
        { crit: 1 },
        {
          note: 'von 12',
          status: s.blocklists ? 'critical' : 'ok',
        },
      ),
    ],
    attributes: [
      { key: 'Nameserver', value: `ns1.${s.name} · ns2.${s.name}`, mono: true },
      { key: 'MX', value: `10 mail.${s.name}`, mono: true },
      { key: 'SPF', value: 'v=spf1 mx -all', mono: true },
    ],
    details: s.details,
    history: s.history,
    rules: withFiring(DOMAIN_RULES, s.firing),
  };
}

export const DOMAINS: MonObject[] = [
  domain({
    name: 'example.com',
    server: 'web-01',
    status: 'ok',
    reason: 'Registriert bis 14.03.2027, DNS konsistent',
    since: ago(60 * DAY),
    regDays: 116,
    regUntil: '14.03.2027',
    dnssec: 'signiert',
    mail: 'MX, SPF, DMARC p=quarantine',
    blocklists: 0,
  }),
  domain({
    name: 'example.net',
    server: 'mail-01',
    status: 'warning',
    reason: 'Registrierung läuft in 21 Tagen ab',
    since: ago(9 * DAY),
    regDays: 21,
    regUntil: '09.12.2026',
    dnssec: 'nicht signiert',
    mail: 'MX, SPF, DMARC p=none',
    blocklists: 0,
    firing: ['domain.expiry'],
    history: [{ at: ago(9 * DAY), status: 'warning', text: 'Registrierung unter 30 Tagen' }],
  }),
  domain({
    name: 'example.org',
    server: 'mail-01',
    status: 'critical',
    reason: 'Auf Blockliste: 1 von 12 (Beispiel-DNSBL)',
    since: ago(35),
    regDays: 240,
    regUntil: '16.07.2027',
    dnssec: 'signiert',
    mail: 'MX, SPF, DMARC p=reject',
    blocklists: 1,
    firing: ['domain.dnsbl'],
    history: [
      { at: ago(35), status: 'critical', text: 'gelistet bei Beispiel-DNSBL (192.0.2.25)' },
    ],
    details: [
      {
        type: 'note',
        title: 'Blockliste',
        text: 'Gelistet ist die Ausgangsadresse 192.0.2.25 von mail-01. Die Liste nennt als Grund Spam-Rückläufer; Austragen erst, wenn die Ursache behoben ist.',
      },
    ],
  }),
];

// ---------------------------------------------------------------------------------------------
// endpoint

const LATENCY_RULE = rule(
  'endpoint.latency',
  'Antwortzeit: Warnung ab 500 ms, kritisch ab 2 s',
  'warning',
  'eigene',
);
const DOWN_RULE = rule('endpoint.down', 'Antwortet nicht, zwei Versuche in Folge', 'critical');

/** Hourly points of the last 24 h; an endpoint that went down has none after `downAt`. */
function latencyTrend(at: (i: number) => number, downAt?: string): Detail {
  const points = Array.from({ length: 24 }, (_, i) => ({ at: ago((23 - i) * HOUR), value: at(i) }));
  return {
    type: 'trend',
    title: 'Antwortzeit, 24 h',
    unit: 'ms',
    threshold: { warn: 500, crit: 2000 },
    points: downAt ? points.filter((p) => p.at < downAt) : points,
  };
}

export const ENDPOINTS: MonObject[] = [
  {
    key: 'endpoint/https/shop.example.com/',
    kind: 'endpoint',
    name: 'https://shop.example.com/',
    server: 'web-01',
    identity: ['http', 'GET, erwartet 200', 'zentral alle 60 s'],
    status: 'critical',
    reason: 'Antwortet nicht: Verbindung abgelehnt',
    since: ago(43),
    metrics: [
      metric('code', 'Antwort', 'keine', null, {
        status: 'critical',
        note: 'Verbindung abgelehnt',
      }),
      metric('latency', 'Antwortzeit', '–', { warn: 500, crit: 2000 }, { unit: 'ms' }),
      metric('cert', 'Zertifikat', 'gültig noch 41 Tage', null, {
        note: 'bewertet am Zertifikat',
      }),
    ],
    details: [latencyTrend((i) => 150 + ((i * 37) % 60), ago(43))],
    history: [{ at: ago(43), status: 'critical', text: 'zwei Versuche ohne Antwort' }],
    rules: withFiring([DOWN_RULE, LATENCY_RULE], ['endpoint.down']),
  },
  {
    key: 'endpoint/tcp/192.0.2.25:25',
    kind: 'endpoint',
    name: 'tcp 192.0.2.25:25',
    server: 'mail-01',
    identity: ['tcp', 'Port 25', 'zentral alle 60 s'],
    status: 'ok',
    reason: 'Port offen',
    since: ago(21 * DAY),
    metrics: [
      metric('open', 'Port', 'offen', null),
      // No latency rule here: the time is shown without a threshold.
      metric('latency', 'Antwortzeit', 3, null, { unit: 'ms' }),
    ],
    rules: withFiring([DOWN_RULE]),
  },
  {
    key: 'endpoint/ping/198.51.100.7',
    kind: 'endpoint',
    name: 'ping 198.51.100.7',
    server: 'fw-01',
    identity: ['ping', 'WAN2-Gateway', 'zentral alle 60 s'],
    status: 'critical',
    reason: 'Antwortet nicht seit 12 min',
    since: ago(12),
    metrics: [
      metric('loss', 'Verlust', 100, { warn: 20, crit: 100 }, { unit: '%', status: 'critical' }),
      metric('latency', 'Antwortzeit', '–', null),
    ],
    history: [{ at: ago(12), status: 'critical', text: 'zwei Versuche ohne Antwort' }],
    rules: withFiring([DOWN_RULE], ['endpoint.down']),
  },
  {
    key: 'endpoint/https/intranet.example.org/',
    kind: 'endpoint',
    name: 'https://intranet.example.org/',
    server: 'web-02',
    identity: ['http', 'GET, erwartet 200', 'zentral alle 60 s'],
    status: 'warning',
    reason: 'Langsam: antwortet in 1,4 s',
    since: ago(3 * HOUR),
    metrics: [
      metric('code', 'Antwort', 'HTTP 200', null),
      metric(
        'latency',
        'Antwortzeit',
        1412,
        { warn: 500, crit: 2000 },
        { unit: 'ms', status: 'warning' },
      ),
      metric('cert', 'Zertifikat', 'läuft in 6 Tagen ab', null, {
        note: 'bewertet am Zertifikat',
      }),
    ],
    details: [
      latencyTrend((i) => (i < 20 ? 240 + ((i * 29) % 70) : [620, 980, 1270, 1412][i - 20])),
    ],
    history: [{ at: ago(3 * HOUR), status: 'warning', text: 'Antwortzeit 620 ms, ab 500' }],
    rules: withFiring([DOWN_RULE, LATENCY_RULE], ['endpoint.latency']),
  },
  {
    // R-1515: answers 503 while the AIO backup on app-03 stops the apache container; the exception
    // e14 takes it out of the rating only as long as the module reports the backup running.
    key: 'endpoint/https/cloud.example.net/status.php',
    kind: 'endpoint',
    name: 'https://cloud.example.net/status.php',
    server: 'app-03',
    identity: ['http', 'GET, erwartet 200', 'zentral alle 60 s'],
    status: 'critical',
    reason: 'Antwortet mit HTTP 503',
    since: ago(25),
    metrics: [
      metric('code', 'Antwort', 'HTTP 503', null, { status: 'critical' }),
      metric('latency', 'Antwortzeit', 12, { warn: 500, crit: 2000 }, { unit: 'ms' }),
    ],
    details: [latencyTrend((i) => 180 + ((i * 41) % 50), ago(25))],
    history: [
      { at: ago(25), status: 'critical', text: 'HTTP 503' },
      { at: ago(DAY - 40), status: 'ok', text: 'HTTP 200' },
      { at: ago(DAY + 25), status: 'critical', text: 'HTTP 503' },
    ],
    rules: withFiring([DOWN_RULE], ['endpoint.down']),
  },
];

export const NETWORK_OBJECTS: MonObject[] = [...CERTIFICATES, ...DOMAINS, ...ENDPOINTS];
