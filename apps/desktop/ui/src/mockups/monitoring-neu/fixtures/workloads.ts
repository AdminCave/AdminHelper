// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Container fixtures (Konzept §4.4): the key is host + compose project/service/number, else host +
// name; the container id is only an attribute. A compose project rates as its worst container that
// is not hidden. Stopped one-off jobs carry a "nicht bewerten" exception and show grey.

import type {
  Attribute,
  Detail,
  ExceptionInfo,
  HistoryEvent,
  LogLine,
  Metric,
  MonObject,
  RuleView,
  Status,
  Threshold,
} from '../model';
import { DAY, HOUR, ago } from './time';

const ADMIN = 'admin';
const RESTARTS: Threshold = { warn: 3, crit: 5 };

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

const CONTAINER_RULES: RuleView[] = [
  rule(
    'container.down',
    'Beendet mit Code ungleich 0, abgestürzt oder Speicher erschöpft',
    'critical',
  ),
  rule('container.unhealthy', 'Healthcheck meldet ungesund', 'warning'),
  rule('container.restarts', 'Neustarts in 24 h: ab 3 Warnung, ab 5 kritisch', 'critical'),
];
const PROJECT_RULES: RuleView[] = [
  rule(
    'compose.worst',
    'Schlechtester Dienst des Projekts, ausgeblendete zählen nicht',
    'critical',
  ),
];

function log(atMin: number, source: string, priority: LogLine['priority'], text: string): LogLine {
  return { at: ago(atMin), source, priority, text };
}

interface ContainerSpec {
  server: string;
  /** Compose project and service; without them the container is keyed by its name. */
  project?: string;
  service?: string;
  name: string;
  image: string;
  id: string;
  status: Status;
  reason: string;
  since: string;
  badSince?: string;
  state: string;
  /** docker inspect State, as the agent reports it. */
  raw: { status: 'running' | 'exited' | 'restarting'; exitCode: number; oom?: boolean };
  health: string;
  healthStatus?: Status;
  restarts: number;
  restartStatus?: Status;
  ports?: string;
  policy: string;
  extra?: Attribute[];
  details?: Detail[];
  history?: HistoryEvent[];
  firing?: string[];
  exception?: ExceptionInfo;
}

function container(s: ContainerSpec): MonObject {
  const place = s.project ? `${s.project}/${s.service}/1` : s.name;
  return {
    key: `${s.server}/container/${place}`,
    kind: 'container',
    name: s.name,
    server: s.server,
    identity: [s.project ? `Compose ${s.project}/${s.service}` : 'ohne Compose', s.image, s.server],
    status: s.status,
    reason: s.reason,
    since: s.since,
    badSince: s.badSince,
    metrics: [
      metric('state', 'Zustand', s.state, null),
      metric('health', 'Health', s.health, null, s.healthStatus ? { status: s.healthStatus } : {}),
      metric(
        'restarts',
        'Neustarts 24 h',
        s.restarts,
        RESTARTS,
        s.restartStatus ? { status: s.restartStatus } : {},
      ),
      metric('image', 'Image', s.image, null),
    ],
    attributes: [
      { key: 'Container-ID', value: s.id, mono: true },
      { key: 'Restart-Policy', value: s.policy, mono: true },
      { key: 'Ports', value: s.ports ?? 'keine', mono: true },
      ...(s.project
        ? [
            {
              key: 'Labels',
              value: `com.docker.compose.project=${s.project} · com.docker.compose.service=${s.service}`,
              mono: true,
            },
          ]
        : []),
      ...(s.extra ?? []),
    ],
    details: s.details,
    history: s.history,
    rules: CONTAINER_RULES.map((r) => ({ ...r, firing: (s.firing ?? []).includes(r.key) })),
    exception: s.exception,
    raw: JSON.stringify(
      {
        Id: s.id,
        Name: `/${s.name}`,
        Image: s.image,
        State: { Status: s.raw.status, ExitCode: s.raw.exitCode, OOMKilled: s.raw.oom ?? false },
        RestartCount: s.restarts,
      },
      null,
      2,
    ),
  };
}

export const CONTAINERS: MonObject[] = [
  container({
    server: 'app-02',
    project: 'nextcloud',
    service: 'app',
    name: 'nextcloud-app-1',
    image: 'nextcloud:31-apache',
    id: '4f1c2a9b7d3e',
    status: 'ok',
    reason: 'Läuft seit 3 Tagen',
    since: ago(3 * DAY),
    state: 'läuft',
    raw: { status: 'running', exitCode: 0 },
    health: 'gesund',
    restarts: 0,
    ports: '192.0.2.40:8080 → 80/tcp',
    policy: 'unless-stopped',
  }),
  container({
    server: 'app-02',
    project: 'nextcloud',
    service: 'db',
    name: 'nextcloud-db-1',
    image: 'postgres:17',
    id: '8a2d4c6e1f30',
    status: 'ok',
    reason: 'Läuft seit 3 Tagen',
    since: ago(3 * DAY),
    state: 'läuft',
    raw: { status: 'running', exitCode: 0 },
    health: 'gesund',
    restarts: 0,
    policy: 'unless-stopped',
  }),
  container({
    server: 'app-02',
    project: 'nextcloud',
    service: 'redis',
    name: 'nextcloud-redis-1',
    image: 'redis:7',
    id: 'c3e5a7b9d1f2',
    status: 'ok',
    reason: 'Läuft seit 3 Tagen',
    since: ago(3 * DAY),
    state: 'läuft',
    raw: { status: 'running', exitCode: 0 },
    health: 'ohne Healthcheck',
    restarts: 0,
    policy: 'unless-stopped',
  }),
  container({
    server: 'app-02',
    project: 'nextcloud',
    service: 'cron',
    name: 'nextcloud-cron-1',
    image: 'nextcloud:31-apache',
    id: 'e7f9b1d3a5c4',
    status: 'warning',
    reason: 'Ungesund seit 10 min',
    since: ago(10),
    state: 'läuft',
    raw: { status: 'running', exitCode: 0 },
    health: 'ungesund',
    healthStatus: 'warning',
    restarts: 0,
    policy: 'unless-stopped',
    firing: ['container.unhealthy'],
    details: [
      {
        type: 'log',
        title: 'Health-Log',
        lines: [
          log(20, 'healthcheck', 'info', 'exit 0: letzter cron.php-Lauf vor 4 min'),
          log(15, 'healthcheck', 'err', 'exit 1: letzter cron.php-Lauf vor 9 min'),
          log(12, 'healthcheck', 'err', 'exit 1: letzter cron.php-Lauf vor 12 min'),
          log(10, 'healthcheck', 'err', 'exit 1: letzter cron.php-Lauf vor 14 min'),
        ],
        more: 'docker inspect --format "{{json .State.Health}}" nextcloud-cron-1',
      },
    ],
    history: [{ at: ago(10), status: 'warning', text: 'ungesund nach 3 Fehlschlägen in Folge' }],
  }),
  container({
    server: 'app-02',
    project: 'paperless',
    service: 'webserver',
    name: 'paperless-webserver-1',
    image: 'paperless-ngx:2.14',
    id: '1b3d5f7a9c2e',
    status: 'critical',
    reason: 'Abgestürzt mit Code 3 (vor 2 h)',
    since: ago(2 * HOUR),
    state: 'beendet, Code 3',
    raw: { status: 'exited', exitCode: 3 },
    health: 'ohne Lauf',
    restarts: 0,
    ports: '192.0.2.40:8000 → 8000/tcp',
    policy: 'no',
    firing: ['container.down'],
    details: [
      {
        type: 'log',
        title: 'Container-Log, letzte Zeilen',
        lines: [
          log(2 * HOUR + 1, 'paperless-webserver-1', 'info', 'Applying database migrations'),
          log(
            2 * HOUR,
            'paperless-webserver-1',
            'err',
            'OperationalError: connection to server at "db" failed',
          ),
          log(2 * HOUR, 'docker', 'warning', 'container exited with code 3'),
        ],
        more: 'docker logs --tail 200 paperless-webserver-1',
      },
    ],
    history: [{ at: ago(2 * HOUR), status: 'critical', text: 'beendet mit Code 3' }],
  }),
  container({
    server: 'app-02',
    project: 'paperless',
    service: 'broker',
    name: 'paperless-broker-1',
    image: 'redis:7',
    id: '9d1f3b5a7c8e',
    status: 'ok',
    reason: 'Läuft seit 12 Tagen',
    since: ago(12 * DAY),
    state: 'läuft',
    raw: { status: 'running', exitCode: 0 },
    health: 'ohne Healthcheck',
    restarts: 0,
    policy: 'unless-stopped',
  }),
  container({
    server: 'app-02',
    project: 'proxy',
    service: 'traefik',
    name: 'proxy-traefik-1',
    image: 'traefik:3.3',
    id: '2c4e6a8b0d1f',
    status: 'ok',
    reason: 'Läuft seit 12 Tagen',
    since: ago(12 * DAY),
    state: 'läuft',
    raw: { status: 'running', exitCode: 0 },
    health: 'gesund',
    restarts: 0,
    ports: '192.0.2.40:443 → 443/tcp',
    policy: 'unless-stopped',
  }),
  container({
    server: 'build-01',
    name: 'ci-runner',
    image: 'registry.example.com/ci/runner:2.4',
    id: '5e7a9c1b3d4f',
    status: 'critical',
    reason: 'Speicher erschöpft (Limit 4 GB)',
    since: ago(25),
    state: 'beendet, Code 137',
    raw: { status: 'exited', exitCode: 137, oom: true },
    health: 'ohne Healthcheck',
    restarts: 0,
    policy: 'no',
    extra: [
      { key: 'Speicherlimit', value: '4 GB' },
      { key: 'OOMKilled', value: 'true', mono: true },
    ],
    firing: ['container.down'],
    history: [{ at: ago(25), status: 'critical', text: 'vom Kernel beendet (OOM), Code 137' }],
  }),
  container({
    server: 'build-01',
    name: 'registry',
    image: 'registry:2',
    id: '7a9c1e3b5d6f',
    status: 'critical',
    reason: 'Startet ständig neu (14x in 24 h)',
    since: ago(4 * HOUR),
    badSince: ago(5 * HOUR),
    state: 'startet neu',
    raw: { status: 'restarting', exitCode: 1 },
    health: 'ohne Healthcheck',
    restarts: 14,
    restartStatus: 'critical',
    ports: '192.0.2.50:5000 → 5000/tcp',
    policy: 'always',
    firing: ['container.restarts'],
    details: [
      {
        type: 'log',
        title: 'Container-Log, letzte Zeilen',
        lines: [
          log(3, 'registry', 'err', 'configuration error: storage: unknown driver "s4"'),
          log(3, 'docker', 'warning', 'container exited with code 1, restarting'),
        ],
        more: 'docker logs --tail 200 registry',
      },
    ],
    history: [
      { at: ago(4 * HOUR), status: 'critical', text: '5 Neustarts in 24 h' },
      { at: ago(5 * HOUR), status: 'warning', text: '3 Neustarts in 24 h' },
    ],
  }),
  container({
    server: 'build-01',
    name: 'ci-cache',
    image: 'minio:2026-10',
    id: '3b5d7f9a1c2e',
    status: 'info',
    reason: 'Verschwunden: zuletzt gesehen vor 2 h',
    since: ago(2 * HOUR),
    state: 'nicht mehr vorhanden',
    raw: { status: 'running', exitCode: 0 },
    health: 'ohne Lauf',
    restarts: 0,
    policy: 'unless-stopped',
    history: [{ at: ago(2 * HOUR), status: 'info', text: 'nicht mehr in der Liste des Agents' }],
  }),
  container({
    server: 'web-01',
    name: 'certbot-renew',
    image: 'certbot:3.1',
    id: '6c8e0a2b4d5f',
    status: 'info',
    reason: 'Gestoppt (Code 0, vor 6 h)',
    since: ago(6 * HOUR),
    state: 'beendet, Code 0',
    raw: { status: 'exited', exitCode: 0 },
    health: 'ohne Healthcheck',
    restarts: 0,
    policy: 'no',
    exception: {
      effect: 'no-rating',
      scope: 'dieses Objekt',
      reason: 'Einmal-Job, läuft nachts und beendet sich',
      by: ADMIN,
      at: ago(40 * DAY),
    },
  }),
];

interface ProjectSpec {
  server: string;
  project: string;
  status: Status;
  reason: string;
  since: string;
  services: number;
  running: number;
  unhealthy: number;
  firing?: string[];
}

function project(s: ProjectSpec): MonObject {
  return {
    key: `${s.server}/compose-project/${s.project}`,
    kind: 'compose-project',
    name: s.project,
    server: s.server,
    identity: [`/srv/${s.project}/compose.yaml`, s.server],
    status: s.status,
    reason: s.reason,
    since: s.since,
    metrics: [
      metric('running', 'Dienste laufen', `${s.running} von ${s.services}`, null),
      metric(
        'crashed',
        'Abgestürzt',
        s.services - s.running,
        { crit: 1 },
        {
          status: s.running < s.services ? 'critical' : 'ok',
        },
      ),
      metric(
        'unhealthy',
        'Ungesund',
        s.unhealthy,
        { warn: 1 },
        {
          status: s.unhealthy ? 'warning' : 'ok',
        },
      ),
    ],
    rules: PROJECT_RULES.map((r) => ({ ...r, firing: (s.firing ?? []).includes(r.key) })),
  };
}

export const PROJECTS: MonObject[] = [
  project({
    server: 'app-02',
    project: 'nextcloud',
    status: 'warning',
    reason: 'Dienst cron ungesund',
    since: ago(10),
    services: 4,
    running: 4,
    unhealthy: 1,
    firing: ['compose.worst'],
  }),
  project({
    server: 'app-02',
    project: 'paperless',
    status: 'critical',
    reason: 'Dienst webserver abgestürzt',
    since: ago(2 * HOUR),
    services: 2,
    running: 1,
    unhealthy: 0,
    firing: ['compose.worst'],
  }),
  project({
    server: 'app-02',
    project: 'proxy',
    status: 'ok',
    reason: 'Alle Dienste laufen',
    since: ago(12 * DAY),
    services: 1,
    running: 1,
    unhealthy: 0,
  }),
];

export const WORKLOAD_OBJECTS: MonObject[] = [...PROJECTS, ...CONTAINERS];
