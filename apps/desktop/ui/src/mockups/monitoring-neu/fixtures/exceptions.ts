// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Exceptions, tags, profiles and findings of the mockup (Konzept §2, §8.1, §8.4). Every scope,
// effect and duration appears at least once, in force, resting outside its window or condition,
// and ended; migrated ones carry no wer and wann. Fictitious data only.

import type { Exception, Finding, Profile, Topology } from '../exceptions';
import { DAY, HOUR, ago } from './time';

const ADMIN = 'admin';
const BERLIN = 'Europe/Berlin';

export const AIO = 'app-03/module/nextcloud-aio/nextcloud-aio-mastercontainer';
export const STATUS_PHP = 'endpoint/https/cloud.example.net/status.php';

export const EXCEPTIONS: Exception[] = [
  {
    id: 'e1',
    scope: { kind: 'object', value: 'nas-01/disk/wwn-0x50014ee2b1a2c304' },
    effect: 'no-rating',
    duration: { kind: 'permanent' },
    bound: { metric: 'realloc', value: 3, text: '3 umgelagerte Sektoren' },
    reason: 'beobachtet, Tausch beim nächsten Wartungsfenster',
    by: ADMIN,
    at: ago(60 * DAY),
  },
  {
    id: 'e2',
    scope: { kind: 'object', value: 'backup-01/disk/wwn-0x50014ee2b1a2c317' },
    effect: 'skip',
    duration: { kind: 'permanent' },
    reason: 'USB-Sicherungsplatte, wird wöchentlich getauscht',
    by: ADMIN,
    at: ago(70 * DAY),
  },
  {
    id: 'e3',
    scope: { kind: 'object', value: 'cl-a/guest-backup/107' },
    effect: 'no-rating',
    duration: { kind: 'until', until: ago(-12 * DAY) },
    reason: 'gestoppt, läuft nur für Release-Builds',
    by: ADMIN,
    at: ago(30 * DAY),
  },
  {
    id: 'e4',
    scope: { kind: 'object', value: 'cl-a/guest-backup/9000' },
    effect: 'skip',
    duration: { kind: 'permanent' },
    reason: 'Vorlage, wird nicht gesichert',
    by: ADMIN,
    at: ago(60 * DAY),
  },
  {
    // Konzept §8.1: an ignore list becomes an exception per object, wer and wann unknown.
    id: 'e5',
    scope: { kind: 'object', value: 'web-01/container/certbot-renew' },
    effect: 'no-rating',
    duration: { kind: 'permanent' },
    migrated: 'ignore_containers',
  },
  {
    // Bound to 5 sectors; the disk now reports 8, so the exception has ended.
    id: 'e6',
    scope: { kind: 'object', value: 'pve-01/disk/wwn-0x5000c500a1b2c303' },
    effect: 'no-rating',
    duration: { kind: 'permanent' },
    bound: { metric: 'realloc', value: 5, text: '5 umgelagerte Sektoren' },
    reason: 'Platte älter, Tausch eingeplant',
    by: ADMIN,
    at: ago(45 * DAY),
  },
  {
    id: 'e7',
    scope: { kind: 'cluster', value: 'cl-a' },
    effect: 'no-notify',
    duration: { kind: 'window', days: [6], from: '22:00', to: '02:00', tz: BERLIN },
    reason: 'Proxmox-Updates',
    by: ADMIN,
    at: ago(20 * DAY),
  },
  {
    // Konzept §8.1: a MonitorMaintenance window becomes "nicht melden" for its server.
    id: 'e8',
    scope: { kind: 'server', value: 'nas-01' },
    effect: 'no-notify',
    duration: { kind: 'window', days: [7], from: '03:00', to: '05:00', tz: BERLIN },
    reason: 'Scrub',
    migrated: 'MonitorMaintenance',
  },
  {
    id: 'e9',
    scope: { kind: 'server', value: 'web-02' },
    effect: 'no-notify',
    duration: { kind: 'window', days: [3], from: '09:30', to: '11:00', tz: BERLIN },
    reason: 'Wöchentliches Deployment',
    by: ADMIN,
    at: ago(3 * DAY),
  },
  {
    id: 'e10',
    scope: {
      kind: 'rule',
      value: 'backup-01/module/restic/restic-backup.service',
      rule: 'restic.age',
    },
    effect: 'no-rating',
    duration: { kind: 'until', until: ago(-3 * DAY) },
    reason: 'Repository wird umgezogen',
    by: ADMIN,
    at: ago(DAY),
  },
  {
    id: 'e11',
    scope: { kind: 'tag', value: 'test' },
    effect: 'no-notify',
    duration: { kind: 'permanent' },
    reason: 'Testsysteme',
    by: ADMIN,
    at: ago(200 * DAY),
  },
  {
    // Matches nothing any more: the test servers have no disks of their own.
    id: 'e12',
    scope: { kind: 'check-type', value: 'smart_health', tag: 'test' },
    effect: 'skip',
    duration: { kind: 'permanent' },
    migrated: 'ignore_devices',
  },
  {
    id: 'e13',
    scope: { kind: 'server', value: 'mail-02' },
    effect: 'mute-me',
    duration: { kind: 'until', until: ago(-6 * HOUR) },
    reason: 'Migration läuft',
    by: ADMIN,
    at: ago(2 * HOUR),
  },
  {
    // R-1515: status.php answers 503 while the AIO backup has stopped the apache container.
    id: 'e14',
    scope: { kind: 'check', value: STATUS_PHP },
    effect: 'no-rating',
    duration: { kind: 'permanent' },
    condition: { object: AIO, field: 'backup', equals: 'ja' },
    reason: 'status.php meldet 503, während das AIO-Backup läuft',
    by: ADMIN,
    at: ago(10 * DAY),
  },
  {
    // Ran out two days ago while /var was already short: the mount reports again (Nachmeldung).
    id: 'e15',
    scope: { kind: 'object', value: 'mail-01/mount/var' },
    effect: 'no-notify',
    duration: { kind: 'until', until: ago(2 * DAY) },
    reason: 'Postfächer werden auf neuen Speicher umgezogen',
    by: ADMIN,
    at: ago(9 * DAY),
  },
];

export const TOPOLOGY: Topology = {
  tags: {
    'nas-01': ['storage', 'prod'],
    'pve-01': ['proxmox', 'prod'],
    'pve-02': ['proxmox', 'prod'],
    'web-01': ['web', 'prod'],
    'web-02': ['web', 'prod'],
    'db-01': ['db', 'prod'],
    'db-02': ['db', 'prod'],
    'backup-01': ['backup'],
    'backup-02': ['backup'],
    'srv-01': ['storage'],
    'app-01': ['docker', 'prod'],
    'app-02': ['docker', 'prod'],
    'app-03': ['docker', 'prod'],
    'test-01': ['test'],
    'mail-01': ['mail', 'prod'],
    'mail-02': ['mail', 'prod'],
    'build-01': ['docker', 'test'],
    'dc-01': ['windows', 'ad'],
    'dc-02': ['windows', 'ad'],
    'dc-03': ['windows', 'ad'],
    'dc-04': ['windows', 'ad'],
    'fw-01': ['firewall'],
    'fw-02': ['firewall'],
  },
  // A tag stands in for the cluster until the report carries its name (offene Frage 10).
  clusters: { 'cl-a': ['pve-01', 'pve-02'] },
};

export const PROFILES: Profile[] = [
  {
    name: 'Linux-Basis',
    tags: ['prod', 'test'],
    checkTypes: ['agent_ping', 'agent_resources', 'system_state', 'service_process'],
    policy: 'vorschlagen',
  },
  {
    name: 'Proxmox',
    tags: ['proxmox'],
    checkTypes: ['smart_health', 'zfs_health', 'proxmox_backup'],
    policy: 'automatisch',
  },
  { name: 'Docker', tags: ['docker'], checkTypes: ['docker_health'], policy: 'vorschlagen' },
  {
    name: 'Windows-Basis',
    tags: ['windows'],
    checkTypes: ['agent_ping', 'agent_resources', 'service_process', 'system_state'],
    policy: 'vorschlagen',
  },
  {
    name: 'Speicher',
    tags: ['storage', 'backup'],
    checkTypes: ['smart_health', 'zfs_health'],
    policy: 'automatisch',
  },
  { name: 'Web', tags: ['web'], checkTypes: ['http', 'central'], policy: 'vorschlagen' },
];

export const FINDINGS: Finding[] = [
  {
    id: 'f1',
    server: 'web-01',
    what: 'Dienst redis-server.service',
    checkType: 'service_process',
    foundAt: ago(5 * HOUR),
  },
  {
    id: 'f2',
    server: 'app-02',
    what: 'Container watchtower',
    checkType: 'docker_health',
    foundAt: ago(2 * DAY),
  },
  {
    id: 'f3',
    server: 'nas-01',
    what: 'Platte sde (WDC WD40EFZX)',
    checkType: 'smart_health',
    foundAt: ago(DAY),
  },
  {
    id: 'f4',
    server: 'pve-02',
    what: 'Gast 120 ci-runner',
    checkType: 'proxmox_backup',
    foundAt: ago(3 * HOUR),
  },
  {
    id: 'f5',
    server: 'dc-02',
    what: 'Dienst W32Time',
    checkType: 'service_process',
    foundAt: ago(14 * DAY),
    decision: 'declined',
  },
];
