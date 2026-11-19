// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// A large fictitious fleet for the scale switch of the mockup (Kevin 2026-11-19: does it still
// look good with very many servers and checks?): about 300 servers in roles, each with the usual
// host objects and, by role, dozens of services, containers, guest backups or certificates. A
// rack of Kubernetes nodes has just gone silent, so a burst of new critical problems shows too.
// A seeded generator keeps every load the same.
import type { Attribute, Kind, Metric, MonObject, Status, Threshold } from '../model';
import { DAY, HOUR, ago } from './time';

/** mulberry32: small, fast, good enough for fixtures. */
function seeded(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const rnd = seeded(20261119);
const int = (lo: number, hi: number): number => lo + Math.floor(rnd() * (hi - lo + 1));
const pick = <T>(list: readonly T[]): T => list[Math.floor(rnd() * list.length)];
const chance = (p: number): boolean => rnd() < p;

const CPU: Threshold = { warn: 90, crit: 95 };
const RAM: Threshold = { warn: 90, crit: 98 };
const DISK: Threshold = { warn: 80, crit: 90 };

interface Role {
  role: string;
  count: number;
  os: string[];
  services: string[];
  mounts: string[];
  physical?: boolean;
  containers?: [number, number];
  guests?: [number, number];
  certs?: [number, number];
  endpoints?: [number, number];
  jobs?: [number, number];
  domains?: [number, number];
}

const LINUX = ['Debian 13', 'Debian 13', 'Ubuntu 26.04'];
const BASE_SERVICES = [
  'ssh.service',
  'cron.service',
  'chrony.service',
  'rsyslog.service',
  'unattended-upgrades.service',
  'adminhelper-agent.service',
];

const ROLES: Role[] = [
  {
    role: 'web',
    count: 48,
    os: LINUX,
    services: ['nginx.service', 'php8.4-fpm.service', 'varnish.service', 'certbot.timer'],
    mounts: ['/', '/var', '/srv'],
    certs: [2, 8],
    endpoints: [2, 6],
  },
  {
    role: 'app',
    count: 40,
    os: LINUX,
    services: [
      'app-shop.service',
      'app-api.service',
      'app-worker@1.service',
      'app-worker@2.service',
      'app-worker@3.service',
      'redis-server.service',
      'docker.service',
    ],
    mounts: ['/', '/var', '/var/lib/docker'],
    containers: [6, 18],
    endpoints: [1, 3],
  },
  {
    role: 'k8s',
    count: 72,
    os: ['Ubuntu 26.04'],
    services: ['kubelet.service', 'containerd.service'],
    mounts: ['/', '/var/lib/containerd', '/var/lib/kubelet'],
    containers: [24, 48],
  },
  {
    role: 'db',
    count: 18,
    os: LINUX,
    services: ['postgresql@17-main.service', 'pgbouncer.service', 'pgbackrest.timer'],
    mounts: ['/', '/var/lib/postgresql', '/var/lib/postgresql/wal'],
    physical: true,
  },
  {
    role: 'cache',
    count: 12,
    os: LINUX,
    services: ['redis-server.service', 'memcached.service'],
    mounts: ['/', '/var'],
  },
  {
    role: 'mq',
    count: 8,
    os: LINUX,
    services: ['rabbitmq-server.service', 'epmd.service'],
    mounts: ['/', '/var/lib/rabbitmq'],
  },
  {
    role: 'pve',
    count: 16,
    os: ['Proxmox VE 9'],
    services: [
      'pveproxy.service',
      'pvedaemon.service',
      'pve-cluster.service',
      'corosync.service',
      'pve-firewall.service',
      'zfs-zed.service',
      'ksmtuned.service',
    ],
    mounts: ['/', '/var/lib/vz'],
    physical: true,
    guests: [16, 40],
  },
  {
    role: 'backup',
    count: 8,
    os: ['Proxmox Backup Server 4'],
    services: ['proxmox-backup.service', 'proxmox-backup-proxy.service', 'zfs-zed.service'],
    mounts: ['/', '/mnt/datastore'],
    physical: true,
    jobs: [10, 24],
  },
  {
    role: 'mail',
    count: 6,
    os: LINUX,
    services: [
      'postfix.service',
      'dovecot.service',
      'rspamd.service',
      'clamav-daemon.service',
      'opendkim.service',
    ],
    mounts: ['/', '/var/mail'],
    certs: [1, 3],
    endpoints: [2, 4],
    domains: [2, 6],
  },
  {
    role: 'dns',
    count: 6,
    os: LINUX,
    services: ['unbound.service', 'named.service'],
    mounts: ['/'],
    domains: [4, 12],
  },
  {
    role: 'fw',
    count: 6,
    os: ['FreeBSD 15'],
    services: ['pf', 'sshd', 'unbound', 'dhcpd', 'openvpn'],
    mounts: ['/', '/var'],
    physical: true,
    endpoints: [1, 2],
  },
  {
    role: 'ci',
    count: 14,
    os: LINUX,
    services: ['gitlab-runner.service', 'docker.service', 'containerd.service'],
    mounts: ['/', '/var/lib/docker', '/builds'],
    containers: [8, 30],
  },
  {
    role: 'file',
    count: 10,
    os: LINUX,
    services: ['smbd.service', 'nmbd.service', 'nfs-server.service', 'zfs-zed.service'],
    mounts: ['/', '/srv/share', '/srv/home', '/srv/archiv'],
    physical: true,
  },
  {
    role: 'edge',
    count: 20,
    os: LINUX,
    services: ['haproxy.service', 'keepalived.service', 'nginx.service'],
    mounts: ['/', '/var'],
    certs: [4, 12],
    endpoints: [3, 8],
  },
  {
    role: 'log',
    count: 8,
    os: LINUX,
    services: ['loki.service', 'vector.service', 'opensearch.service', 'grafana-server.service'],
    mounts: ['/', '/var/lib/loki', '/var/lib/opensearch'],
  },
];

const APPS = [
  'shop-api',
  'shop-web',
  'checkout',
  'search',
  'payments',
  'auth',
  'mailer',
  'images',
  'reports',
  'export',
  'import',
  'scheduler',
  'gateway',
  'ingress-nginx',
  'coredns',
  'metrics-agent',
  'log-shipper',
  'cert-manager',
  'redis',
  'queue-worker',
];
const DISK_MODELS: [string, string, string][] = [
  ['Samsung PM893', '1,92 TB', 'SSD'],
  ['Micron 7450 PRO', '3,84 TB', 'NVMe'],
  ['Seagate Exos X18', '16 TB', 'HDD'],
  ['WD Red Plus', '8 TB', 'HDD'],
];
const SITES = [
  'shop',
  'portal',
  'api',
  'status',
  'docs',
  'login',
  'cdn',
  'static',
  'kunden',
  'b2b',
];

/** Kubernetes nodes in the rack that went silent 12 minutes ago. */
const SILENT_RACK = new Set(['k8s-41', 'k8s-42', 'k8s-43', 'k8s-44', 'k8s-45', 'k8s-46']);
const SILENT_MIN = 12;

function address(n: number): string {
  const net = ['192.0.2', '198.51.100', '203.0.113'][Math.floor(n / 250)];
  return `${net}.${(n % 250) + 2}`;
}

function suffix(): string {
  return Math.floor(rnd() * 0xfffff)
    .toString(16)
    .padStart(5, '0');
}

/** When an ok object last changed: days ago. */
function calmSince(): string {
  return ago(int(2, 40) * DAY + int(0, 23) * HOUR);
}

/** When a problem began: mostly hours or days, a few just now. */
function badSince(status: Status): string {
  if (status === 'critical' && chance(0.12)) return ago(int(3, 50));
  return ago(chance(0.5) ? int(20, 23 * 60) : int(1, 9) * DAY);
}

interface Draft {
  kind: Kind;
  id: string;
  name: string;
  identity: string[];
  status: Status;
  reason: string;
  metrics?: Metric[];
  attributes?: Attribute[];
}

function percent(
  key: string,
  label: string,
  t: Threshold,
  bad: { p: number; warn: string; crit: string; ok: string },
): { status: Status; reason: string; metrics: Metric[] } {
  let v = int(8, 72);
  let status: Status = 'ok';
  if (chance(bad.p)) {
    status = chance(0.3) ? 'critical' : 'warning';
    v =
      status === 'critical'
        ? int((t.crit ?? 95) + 1, 99)
        : int((t.warn ?? 80) + 1, (t.crit ?? 95) - 1);
  }
  const reason = (status === 'critical' ? bad.crit : status === 'warning' ? bad.warn : bad.ok)
    .replace('{v}', String(v))
    .replace('{free}', String(Math.max(1, Math.round((100 - v) * 1.6))));
  const metric: Metric = { key, label, value: v, unit: '%', threshold: t };
  if (status !== 'ok') metric.status = status;
  return { status, reason, metrics: [metric] };
}

function serverDrafts(r: Role, server: string, os: string, ip: string): Draft[] {
  const cores = pick([2, 4, 4, 8, 8, 16, 32]);
  const out: Draft[] = [
    {
      kind: 'host',
      id: 'host',
      name: server,
      identity: [os, ip],
      status: 'ok',
      reason: 'Meldet sich regelmäßig',
    },
    {
      kind: 'cpu',
      id: 'cpu',
      name: 'CPU',
      identity: [`${cores} Kerne`],
      ...percent('usage', 'Auslastung', CPU, {
        p: 0.02,
        warn: 'Auslastung {v} % seit 20 min',
        crit: 'Auslastung {v} % seit 35 min',
        ok: 'Im Rahmen',
      }),
    },
    {
      kind: 'memory',
      id: 'memory',
      name: 'Arbeitsspeicher',
      identity: [`${cores * 4} GB`],
      ...percent('used', 'Belegt', RAM, {
        p: 0.02,
        warn: '{v} % belegt',
        crit: '{v} % belegt, Auslagerung aktiv',
        ok: 'Im Rahmen',
      }),
    },
  ];

  const sec = chance(0.07) ? int(1, 14) : 0;
  out.push({
    kind: 'updates',
    id: 'updates',
    name: 'Updates',
    identity: [os.startsWith('FreeBSD') ? 'pkg' : 'apt', 'Quelle: Agent'],
    status: sec ? 'warning' : 'ok',
    reason: sec ? `${sec} Sicherheitsupdates ausstehend` : 'Aktuell',
    metrics: [
      {
        key: 'security',
        label: 'Sicherheitsupdates',
        value: sec,
        threshold: { warn: 1 },
        ...(sec ? { status: 'warning' as Status } : {}),
      },
    ],
  });
  out.push({
    kind: 'clock',
    id: 'clock',
    name: 'Uhr',
    identity: ['chrony'],
    ...(chance(0.01)
      ? { status: 'warning' as Status, reason: 'Uhr weicht 2,4 s ab' }
      : { status: 'ok' as Status, reason: 'Synchron' }),
  });
  if (chance(0.05))
    out.push({
      kind: 'reboot',
      id: 'reboot',
      name: 'Neustart',
      identity: ['Kernel-Update'],
      status: 'warning',
      reason: 'Neustart nötig nach Kernel-Update',
    });

  for (const m of r.mounts)
    out.push({
      kind: 'mount',
      id: `mount${m}`,
      name: m,
      identity: [m === '/' ? 'ext4' : pick(['ext4', 'xfs', 'zfs'])],
      ...percent('used', 'Belegt', DISK, {
        p: 0.025,
        warn: '{v} % belegt, {free} GB frei',
        crit: '{v} % belegt, nur {free} GB frei',
        ok: 'Im Rahmen',
      }),
    });

  if (r.physical) {
    const disks = int(2, 12);
    for (let i = 0; i < disks; i++) {
      const dev = `sd${String.fromCharCode(97 + i)}`;
      const bad = chance(0.012) ? pick<Status>(['warning', 'critical']) : 'ok';
      const [model, size, cls] = pick(DISK_MODELS);
      out.push({
        kind: 'disk',
        id: `disk/${dev}`,
        name: dev,
        identity: [`${model} ${size}`],
        attributes: [
          { key: 'Gerät', value: `/dev/${dev}` },
          { key: 'Modell', value: model },
          { key: 'Klasse', value: cls },
          { key: 'Kapazität', value: size },
        ],
        status: bad,
        reason:
          bad === 'critical'
            ? 'SMART: Selbsttest fehlgeschlagen'
            : bad === 'warning'
              ? `SMART: ${int(4, 40)} umgelagerte Sektoren`
              : 'SMART in Ordnung',
      });
    }
    out.push({
      kind: 'sensor',
      id: 'sensor/cpu',
      name: 'CPU-Temperatur',
      identity: ['coretemp'],
      ...(chance(0.03)
        ? { status: 'warning' as Status, reason: `Temperatur ${int(81, 92)} °C` }
        : { status: 'ok' as Status, reason: `Temperatur ${int(38, 64)} °C` }),
    });
  }
  if (r.role === 'pve' || r.role === 'backup' || r.role === 'file') {
    for (const pool of r.role === 'pve' ? ['rpool'] : ['rpool', 'tank']) {
      const st: Status = chance(0.05) ? pick<Status>(['warning', 'critical']) : 'ok';
      out.push({
        kind: 'pool',
        id: `pool/${pool}`,
        name: pool,
        identity: ['ZFS'],
        status: st,
        reason:
          st === 'critical'
            ? 'DEGRADED: ein Gerät fehlt'
            : st === 'warning'
              ? `${int(81, 89)} % belegt`
              : 'ONLINE',
      });
    }
  }

  for (const s of [...BASE_SERVICES, ...r.services]) {
    const failed = chance(0.004);
    out.push({
      kind: 'service',
      id: `service/${s}`,
      name: s,
      identity: ['systemd'],
      status: failed ? 'critical' : 'ok',
      reason: failed ? 'Dienst fehlgeschlagen (exit-code 1)' : 'Läuft',
    });
  }

  if (r.containers) {
    const n = int(...r.containers);
    for (let i = 0; i < n; i++) {
      const name = `${pick(APPS)}-${suffix()}`;
      const st: Status = chance(0.006) ? pick<Status>(['warning', 'critical']) : 'ok';
      out.push({
        kind: 'container',
        id: `container/${name}`,
        name,
        identity: [r.role === 'k8s' ? 'Kubernetes-Pod' : 'Docker'],
        status: st,
        reason:
          st === 'critical'
            ? 'Beendet mit Exit-Code 137'
            : st === 'warning'
              ? `Neustart-Schleife: ${int(5, 14)} Neustarts in der letzten Stunde`
              : 'Läuft',
      });
    }
  }
  if (r.guests) {
    const n = int(...r.guests);
    for (let i = 0; i < n; i++) {
      const vmid = 100 + i;
      const st: Status = chance(0.015) ? pick<Status>(['warning', 'critical']) : 'ok';
      out.push({
        kind: 'guest-backup',
        id: `guest-backup/${vmid}`,
        name: `VM ${vmid}`,
        identity: [`vzdump · PBS ${pick(['backup-01', 'backup-02', 'backup-03'])}`],
        attributes: [
          { key: 'Cluster', value: `pve-${Math.ceil(Number(server.slice(4)) / 4)}` },
          { key: 'Node', value: server },
        ],
        status: st,
        reason:
          st === 'critical'
            ? 'Letzte Sicherung fehlgeschlagen'
            : st === 'warning'
              ? `Letzte Sicherung vor ${int(2, 5)} Tagen`
              : `Gesichert vor ${int(2, 20)} h`,
      });
    }
  }
  if (r.jobs) {
    const n = int(...r.jobs);
    for (let i = 0; i < n; i++) {
      const st: Status = chance(0.02) ? 'critical' : 'ok';
      out.push({
        kind: 'backup-job',
        id: `backup-job/${i + 1}`,
        name: `sync-${String(i + 1).padStart(2, '0')}`,
        identity: ['Proxmox Backup Server'],
        status: st,
        reason: st === 'critical' ? 'Lauf fehlgeschlagen' : 'Letzter Lauf erfolgreich',
      });
    }
  }
  if (r.certs) {
    const n = int(...r.certs);
    for (let i = 0; i < n; i++) {
      const host = `${SITES[(i + server.length) % SITES.length]}${i >= SITES.length ? i : ''}.example.com`;
      const days = chance(0.04) ? int(2, 13) : int(30, 89);
      const st: Status = days < 7 ? 'critical' : days < 14 ? 'warning' : 'ok';
      out.push({
        kind: 'certificate',
        id: `certificate/${host}`,
        name: host,
        identity: ["Let's Encrypt"],
        status: st,
        reason: st === 'ok' ? `Gültig noch ${days} Tage` : `Läuft in ${days} Tagen ab`,
      });
    }
  }
  if (r.endpoints) {
    const n = int(...r.endpoints);
    for (let i = 0; i < n; i++) {
      const url = `https://${SITES[(i * 3 + server.length) % SITES.length]}.example.org/health`;
      const st: Status = chance(0.012) ? pick<Status>(['warning', 'critical']) : 'ok';
      out.push({
        kind: 'endpoint',
        id: `endpoint/${i}`,
        name: url,
        identity: ['HTTP-Prüfung'],
        status: st,
        reason:
          st === 'critical'
            ? 'Antwortet nicht (Zeitüberschreitung nach 10 s)'
            : st === 'warning'
              ? `Antwortzeit ${int(21, 48) / 10} s über 2 s`.replace('.', ',')
              : `Antwortet in ${int(40, 300)} ms`,
      });
    }
  }
  if (r.domains) {
    const n = int(...r.domains);
    for (let i = 0; i < n; i++) {
      const name = `${SITES[i % SITES.length]}${i >= SITES.length ? i : ''}-${server}.example.net`;
      const days = chance(0.05) ? int(10, 28) : int(60, 360);
      out.push({
        kind: 'domain',
        id: `domain/${name}`,
        name,
        identity: ['Registrar-Abfrage'],
        status: days < 30 ? 'warning' : 'ok',
        reason: days < 30 ? `Läuft in ${days} Tagen ab` : `Registriert noch ${days} Tage`,
      });
    }
  }
  return out;
}

function build(): MonObject[] {
  const out: MonObject[] = [];
  let n = 0;
  for (const r of ROLES) {
    for (let i = 1; i <= r.count; i++) {
      const server = `${r.role}-${String(i).padStart(2, '0')}`;
      const silent = SILENT_RACK.has(server);
      for (const d of serverDrafts(r, server, pick(r.os), address(n++))) {
        let { status, reason } = d;
        if (silent) {
          if (d.kind === 'host') {
            status = 'critical';
            reason = `Meldet sich nicht seit ${SILENT_MIN} min`;
          } else {
            status = 'stale';
            reason = `Veraltet: letzte Werte von vor ${SILENT_MIN} min`;
          }
        }
        const since = silent ? ago(SILENT_MIN) : status === 'ok' ? calmSince() : badSince(status);
        out.push({
          key: `${server}/${d.id}`,
          kind: d.kind,
          name: d.name,
          server,
          identity: d.identity,
          status,
          reason,
          since,
          metrics: d.metrics ?? [],
          ...(d.attributes ? { attributes: d.attributes } : {}),
        });
      }
    }
  }
  return out;
}

/** The large fleet, as the checks report it. */
export const SCALE_OBJECTS: MonObject[] = build();
