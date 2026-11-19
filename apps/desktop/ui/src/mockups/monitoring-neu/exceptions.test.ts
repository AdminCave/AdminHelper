// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Exceptions of the target model (Konzept §2, §8.1, §8.4; R-1515): which objects a scope covers,
// when an exception is in force, rests or has ended, what it does to the object, and the coverage
// per server.

import { describe, expect, it } from 'vitest';
import {
  MIGRATED_BY,
  affected,
  applyExceptions,
  coverageOf,
  covers,
  durationText,
  exceptionState,
  findingState,
  inWindow,
  reviewReason,
  type Duration,
  type Exception,
  type Scope,
  type Topology,
} from './exceptions';
import { exceptionText, grammarViolations, isHidden } from './grammar';
import type { MonObject } from './model';
import { ALL_OBJECTS, BASE_OBJECTS } from './fixtures';
import { AIO, EXCEPTIONS, FINDINGS, PROFILES, STATUS_PHP, TOPOLOGY } from './fixtures/exceptions';
import { DAY, NOW, ago } from './fixtures/time';

function obj(o: Partial<MonObject> & Pick<MonObject, 'key' | 'kind' | 'server'>): MonObject {
  return {
    name: o.key,
    identity: ['test'],
    status: 'ok',
    reason: 'Gesund',
    since: ago(DAY),
    metrics: [],
    ...o,
  };
}

const DISK = obj({ key: 'srv-01/disk/a', kind: 'disk', server: 'srv-01' });
const SERVICE = obj({ key: 'srv-01/service/b.service', kind: 'service', server: 'srv-01' });
const MODULE = obj({ key: 'app-01/module/m/i', kind: 'module', server: 'app-01' });
const PART = obj({
  key: 'app-01/module/m/i/p',
  kind: 'module',
  server: 'app-01',
  parent: MODULE.key,
});
const ENDPOINT = obj({
  key: 'endpoint/https/a.example.com/',
  kind: 'endpoint',
  server: 'app-01',
  identity: ['http', 'GET, erwartet 200'],
});
const OBJECTS = [DISK, SERVICE, MODULE, PART, ENDPOINT];
const TOPO: Topology = {
  tags: { 'srv-01': ['storage'], 'app-01': ['docker'] },
  clusters: { 'cl-x': ['srv-01'] },
};

function keysCovered(scope: Scope): string[] {
  return OBJECTS.filter((o) => covers(scope, o, TOPO)).map((o) => o.key);
}

function exc(e: Partial<Exception> & Pick<Exception, 'scope'>): Exception {
  return {
    id: 'x',
    effect: 'no-rating',
    duration: { kind: 'permanent' },
    by: 'admin',
    at: ago(DAY),
    ...e,
  };
}

const byKey = (list: readonly MonObject[], key: string) => {
  const o = list.find((x) => x.key === key);
  if (!o) throw new Error(`no object ${key}`);
  return o;
};

describe('scope: which objects an exception covers', () => {
  it.each([
    [{ kind: 'object', value: DISK.key }, [DISK.key]],
    [{ kind: 'rule', value: SERVICE.key, rule: 'r' }, [SERVICE.key]],
    [{ kind: 'check', value: 'srv-01/smart_health' }, [DISK.key]],
    [{ kind: 'check', value: MODULE.key }, [MODULE.key, PART.key]],
    [{ kind: 'check', value: ENDPOINT.key }, [ENDPOINT.key]],
    [{ kind: 'check-type', value: 'smart_health' }, [DISK.key]],
    [{ kind: 'check-type', value: 'smart_health', tag: 'docker' }, []],
    [{ kind: 'check-type', value: 'http' }, [ENDPOINT.key]],
    [{ kind: 'server', value: 'srv-01' }, [DISK.key, SERVICE.key]],
    [{ kind: 'tag', value: 'docker' }, [MODULE.key, PART.key, ENDPOINT.key]],
    [{ kind: 'cluster', value: 'cl-x' }, [DISK.key, SERVICE.key]],
    [{ kind: 'cluster', value: 'cl-unknown' }, []],
  ] as [Scope, string[]][])('%o covers %o', (scope, keys) => {
    expect(keysCovered(scope)).toEqual(keys);
  });
});

describe('duration', () => {
  const sat: Extract<Duration, { kind: 'window' }> = {
    kind: 'window',
    days: [6],
    from: '22:00',
    to: '02:00',
    tz: 'Europe/Berlin',
  };

  it.each([
    ['2026-11-21T21:30:00Z', true], // Sa 22:30 in Berlin
    ['2026-11-22T00:30:00Z', true], // So 01:30: the window of Saturday runs past midnight
    ['2026-11-22T01:30:00Z', false], // So 02:30
    ['2026-11-21T20:30:00Z', false], // Sa 21:30
    ['2026-11-20T23:30:00Z', false], // Sa 00:30 belongs to Friday's window, and Friday has none
  ])('Saturday 22:00–02:00 Berlin at %s: %s', (at, inside) => {
    expect(inWindow(sat, new Date(at))).toBe(inside);
  });

  it('reads the window in its own time zone, summer time included', () => {
    const wed = { kind: 'window' as const, days: [3], from: '09:30', to: '11:00' };
    expect(inWindow({ ...wed, tz: 'Europe/Berlin' }, NOW)).toBe(true); // 10:00 in Berlin
    expect(inWindow({ ...wed, tz: 'UTC' }, NOW)).toBe(false); // 09:00 UTC
    expect(inWindow({ ...wed, tz: 'Europe/Berlin' }, new Date('2026-07-01T08:00:00Z'))).toBe(true);
    expect(inWindow({ ...wed, tz: 'Europe/Berlin' }, new Date('2026-07-01T09:30:00Z'))).toBe(false);
  });

  it('a window outside its time rests, an expired one has ended', () => {
    expect(
      exceptionState(
        exc({ scope: { kind: 'object', value: DISK.key }, duration: sat }),
        OBJECTS,
        NOW,
      ),
    ).toEqual({
      state: 'resting',
      text: 'außerhalb des Fensters',
    });
    const until = (at: string) =>
      exceptionState(
        exc({ scope: { kind: 'object', value: DISK.key }, duration: { kind: 'until', until: at } }),
        OBJECTS,
        NOW,
      );
    expect(until(ago(-60)).state).toBe('active');
    expect(until(ago(60))).toEqual({
      state: 'ended',
      text: `abgelaufen am ${'18.11.2026, 08:00'}`,
    });
  });

  it('says how long in words', () => {
    expect(durationText({ kind: 'permanent' })).toBe('dauerhaft');
    expect(durationText({ kind: 'until', until: '2026-11-30T23:59:00Z' })).toBe(
      'bis 30.11.2026, 23:59',
    );
    expect(durationText({ ...sat, days: [6, 7] })).toBe(
      'wiederkehrend Sa, So 22:00–02:00 (Europe/Berlin)',
    );
  });
});

describe('bound to the value', () => {
  const disk = {
    ...DISK,
    metrics: [{ key: 'realloc', label: 'Umgelagerte Sektoren', value: 3, threshold: { warn: 1 } }],
  };
  const bound = exc({
    scope: { kind: 'object', value: DISK.key },
    bound: { metric: 'realloc', value: 3, text: '3 umgelagerte Sektoren' },
  });

  it('holds while the value stays', () => {
    expect(exceptionState(bound, [disk], NOW).state).toBe('active');
  });

  it('ends once the value changes, and says to what', () => {
    const now8 = { ...disk, metrics: [{ ...disk.metrics[0], value: 8 }] };
    expect(exceptionState(bound, [now8], NOW)).toEqual({
      state: 'ended',
      text: 'Umgelagerte Sektoren jetzt 8, gebunden an 3',
    });
  });

  it('ends when the value is no longer reported', () => {
    expect(exceptionState(bound, [DISK], NOW).state).toBe('ended');
  });
});

describe('condition over another check of the instance (R-1515)', () => {
  const e14 = EXCEPTIONS.find((e) => e.id === 'e14') as Exception;
  const withBackup = (value: string) =>
    BASE_OBJECTS.map((o) =>
      o.key === AIO
        ? { ...o, metrics: o.metrics.map((m) => (m.key === 'backup' ? { ...m, value } : m)) }
        : o,
    );

  it('hides status.php while the AIO backup runs', () => {
    expect(exceptionState(e14, BASE_OBJECTS, NOW).state).toBe('active');
    const endpoint = byKey(ALL_OBJECTS, STATUS_PHP);
    expect(isHidden(endpoint)).toBe(true);
    expect(endpoint.exception?.condition).toBe(
      'nur solange Modul nextcloud-aio nextcloud-aio-mastercontainer auf app-03 „Backup läuft: ja“ meldet',
    );
    // The module itself stays ok: the backup is expected, only its field changes.
    expect(byKey(ALL_OBJECTS, AIO).status).toBe('ok');
  });

  it('rates status.php again once the backup is over', () => {
    const objects = withBackup('nein');
    expect(exceptionState(e14, objects, NOW)).toEqual({
      state: 'resting',
      text: 'Bedingung nicht erfüllt: Backup läuft nein',
    });
    const endpoint = byKey(applyExceptions(objects, EXCEPTIONS, NOW, TOPOLOGY), STATUS_PHP);
    expect(isHidden(endpoint)).toBe(false);
    expect(endpoint.exception).toBeUndefined();
    expect(endpoint.status).toBe('critical');
  });

  it('reads the status of the other object in words', () => {
    const e = exc({
      scope: { kind: 'object', value: ENDPOINT.key },
      condition: { object: SERVICE.key, field: 'status', equals: 'warning' },
    });
    expect(exceptionState(e, OBJECTS, NOW)).toEqual({
      state: 'resting',
      text: 'Bedingung nicht erfüllt: Zustand OK',
    });
    expect(exceptionState(e, [{ ...SERVICE, status: 'warning' }, ENDPOINT], NOW).state).toBe(
      'active',
    );
    expect(exceptionState(e, [ENDPOINT], NOW).state).toBe('resting');
  });
});

describe('what an exception does to the object', () => {
  it('the most specific exception in force wins; a resting one falls back to the broader', () => {
    const server = exc({
      id: 's',
      scope: { kind: 'server', value: 'srv-01' },
      effect: 'no-notify',
    });
    const own = exc({ id: 'o', scope: { kind: 'object', value: DISK.key } });
    const [disk, service] = applyExceptions([DISK, SERVICE], [server, own], NOW, TOPO);
    expect(disk.exception?.id).toBe('o');
    expect(disk.exception?.scope).toBe('dieses Objekt');
    expect(disk.exception?.wide).toBe(false);
    expect(service.exception?.id).toBe('s');
    expect(service.exception?.scope).toBe('Server srv-01');
    expect(service.exception?.wide).toBe(true);
    const resting = {
      ...own,
      duration: { kind: 'window', days: [7], from: '03:00', to: '05:00', tz: 'UTC' },
    } as Exception;
    expect(applyExceptions([DISK], [server, resting], NOW, TOPO)[0].exception?.id).toBe('s');
  });

  it('ranks what the object is before where it runs: object, rule, check, check type, server, tag, cluster', () => {
    let all = [
      exc({ id: 'cluster', scope: { kind: 'cluster', value: 'cl-x' } }),
      exc({ id: 'tag', scope: { kind: 'tag', value: 'storage' } }),
      exc({ id: 'server', scope: { kind: 'server', value: 'srv-01' } }),
      exc({ id: 'check-type', scope: { kind: 'check-type', value: 'smart_health' } }),
      exc({ id: 'check', scope: { kind: 'check', value: 'srv-01/smart_health' } }),
      exc({ id: 'rule', scope: { kind: 'rule', value: DISK.key, rule: 'r' } }),
      exc({ id: 'object', scope: { kind: 'object', value: DISK.key } }),
    ];
    const order: string[] = [];
    while (all.length) {
      const id = applyExceptions([DISK], all, NOW, TOPO)[0].exception?.id ?? '';
      order.push(id);
      all = all.filter((e) => e.id !== id);
    }
    expect(order).toEqual(['object', 'rule', 'check', 'check-type', 'server', 'tag', 'cluster']);
  });

  it('an ended exception stays attached so the object reports again with the reason', () => {
    const ended = exc({
      scope: { kind: 'object', value: DISK.key },
      duration: { kind: 'until', until: ago(60) },
    });
    const [disk] = applyExceptions([DISK], [ended], NOW, TOPO);
    expect(isHidden(disk)).toBe(false);
    expect(disk.exception?.ended).toBe('abgelaufen am 18.11.2026, 08:00');
    expect(exceptionText(disk.exception!)).toMatch(
      /^erloschen \(abgelaufen am 18\.11\.2026, 08:00\) · /,
    );
  });

  it('skip: the object is not checked and shows not-collected', () => {
    const bad = { ...DISK, status: 'critical' as const, reason: 'Defekt', badSince: ago(DAY) };
    const [disk] = applyExceptions(
      [bad],
      [exc({ scope: { kind: 'object', value: DISK.key }, effect: 'skip' })],
      NOW,
      TOPO,
    );
    expect(disk).toMatchObject({
      status: 'not-collected',
      reason: 'Nicht geprüft',
      badSince: undefined,
    });
    expect(isHidden(disk)).toBe(true);
    expect(grammarViolations(disk)).toEqual([]);
  });

  it('rule: takes one rule out; without another firing rule the object is ok', () => {
    const restic = byKey(ALL_OBJECTS, 'backup-01/module/restic/restic-backup.service');
    expect(restic.status).toBe('ok');
    expect(restic.reason).toBe(
      'Regel ausgenommen: Letzter Lauf: Warnung ab 26 h, kritisch ab 50 h (Katalog: 24 h)',
    );
    expect(restic.badSince).toBeUndefined();
    expect(restic.rules?.find((r) => r.key === 'restic.age')?.firing).toBe(false);
    expect(isHidden(restic)).toBe(false);
    expect(grammarViolations(restic)).toEqual([]);
    expect(restic.exception?.scope).toBe(
      'Regel „Letzter Lauf: Warnung ab 26 h, kritisch ab 50 h (Katalog: 24 h)“',
    );
  });

  it('rule: another firing rule keeps the object bad', () => {
    const two = {
      ...SERVICE,
      status: 'critical' as const,
      reason: 'Fehlgeschlagen',
      badSince: ago(DAY),
      rules: [
        { key: 'a', text: 'A', level: 'warning', source: 'Katalog', enabled: true, firing: true },
        { key: 'b', text: 'B', level: 'critical', source: 'Katalog', enabled: true, firing: true },
      ],
    } satisfies MonObject;
    const e = exc({ scope: { kind: 'rule', value: SERVICE.key, rule: 'a' } });
    const [svc] = applyExceptions([two], [e], NOW, TOPO);
    expect(svc.status).toBe('critical');
    expect(svc.rules?.map((r) => r.firing)).toEqual([false, true]);
    expect(svc.exception?.rule).toBe('a');
  });

  it('rule: the reason never names the excepted rule while another of the level fires', () => {
    const two = {
      ...SERVICE,
      status: 'critical' as const,
      reason: 'A',
      badSince: ago(DAY),
      rules: [
        { key: 'a', text: 'A', level: 'critical', source: 'Katalog', enabled: true, firing: true },
        { key: 'b', text: 'B', level: 'critical', source: 'Katalog', enabled: true, firing: true },
      ],
    } satisfies MonObject;
    const e = exc({ scope: { kind: 'rule', value: SERVICE.key, rule: 'a' } });
    const [svc] = applyExceptions([two], [e], NOW, TOPO);
    expect(svc.status).toBe('critical');
    expect(svc.reason).toBe('B');
  });

  it('rule: taking out the critical rule leaves the warning still firing', () => {
    const two = {
      ...SERVICE,
      status: 'critical' as const,
      reason: 'B',
      badSince: ago(DAY),
      rules: [
        { key: 'a', text: 'A', level: 'warning', source: 'Katalog', enabled: true, firing: true },
        { key: 'b', text: 'B', level: 'critical', source: 'Katalog', enabled: true, firing: true },
      ],
    } satisfies MonObject;
    const e = exc({ scope: { kind: 'rule', value: SERVICE.key, rule: 'b' } });
    const [svc] = applyExceptions([two], [e], NOW, TOPO);
    expect(svc).toMatchObject({ status: 'warning', reason: 'A', badSince: ago(DAY) });
    expect(svc.rules?.map((r) => r.firing)).toEqual([true, false]);
    expect(svc.exception?.wide).toBe(false);
  });

  it('a migrated exception names no one', () => {
    const certbot = byKey(ALL_OBJECTS, 'web-01/container/certbot-renew');
    expect(certbot.exception?.by).toBe(MIGRATED_BY);
    expect(certbot.exception?.at).toBeUndefined();
    expect(isHidden(certbot)).toBe(true);
  });
});

describe('fixture exceptions', () => {
  const state = (id: string) =>
    exceptionState(EXCEPTIONS.find((e) => e.id === id) as Exception, BASE_OBJECTS, NOW);

  it.each([
    ['e1', 'active'],
    ['e2', 'active'],
    ['e3', 'active'],
    ['e4', 'active'],
    ['e5', 'active'],
    ['e6', 'ended'],
    ['e7', 'resting'],
    ['e8', 'resting'],
    ['e9', 'active'],
    ['e10', 'active'],
    ['e11', 'active'],
    ['e12', 'active'],
    ['e13', 'active'],
    ['e14', 'active'],
    ['e15', 'ended'],
  ])('%s is %s now', (id, expected) => {
    expect(state(id).state).toBe(expected);
  });

  it('every exception but the stale migrated one covers an object', () => {
    const empty = EXCEPTIONS.filter((e) => affected(e, BASE_OBJECTS, TOPOLOGY).length === 0);
    expect(empty.map((e) => e.id)).toEqual(['e12']);
  });

  it('shows every scope, effect and duration', () => {
    expect(new Set(EXCEPTIONS.map((e) => e.scope.kind))).toEqual(
      new Set(['object', 'rule', 'check', 'check-type', 'server', 'tag', 'cluster']),
    );
    expect(new Set(EXCEPTIONS.map((e) => e.effect))).toEqual(
      new Set(['skip', 'no-rating', 'no-notify', 'mute-me']),
    );
    expect(new Set(EXCEPTIONS.map((e) => e.duration.kind))).toEqual(
      new Set(['permanent', 'until', 'window']),
    );
  });

  it('the ended bound exception reports the disk again', () => {
    const disk = byKey(ALL_OBJECTS, 'pve-01/disk/wwn-0x5000c500a1b2c303');
    expect(disk.exception?.ended).toBe('Umgelagert jetzt 8, gebunden an 5');
    expect(isHidden(disk)).toBe(false);
  });

  it('the deployment window of web-02 is in force on Wednesday 10:00 in Berlin', () => {
    const web02 = ALL_OBJECTS.filter((o) => o.server === 'web-02');
    expect(web02.length).toBeGreaterThan(0);
    expect(web02.every((o) => o.exception?.id === 'e9')).toBe(true);
    expect(web02[0].exception?.window).toBe('wiederkehrend Mi 09:30–11:00 (Europe/Berlin)');
  });

  it('the resting maintenance window attaches nothing', () => {
    expect(
      ALL_OBJECTS.filter((o) => o.server === 'pve-02').some((o) => o.exception?.id === 'e7'),
    ).toBe(false);
  });

  it('puts migrated, old and empty ones up for review', () => {
    const reasons = Object.fromEntries(
      EXCEPTIONS.map((e) => [
        e.id,
        reviewReason(e, affected(e, BASE_OBJECTS, TOPOLOGY).length, NOW),
      ]),
    );
    expect(reasons.e5).toBe('migriert aus ignore_containers, wer und wann unbekannt');
    expect(reasons.e8).toBe('migriert aus MonitorMaintenance, wer und wann unbekannt');
    expect(reasons.e11).toBe('dauerhaft, seit über 90 Tagen');
    expect(reasons.e1).toBeUndefined();
    expect(reviewReason({ ...EXCEPTIONS[0], reviewed: true }, 0, NOW)).toBeUndefined();
    expect(reviewReason(EXCEPTIONS[0], 0, NOW)).toBe('betrifft kein Objekt mehr');
  });
});

describe('coverage (Konzept §8.4)', () => {
  const state = (id: string) =>
    findingState(
      FINDINGS.find((f) => f.id === id)!,
      PROFILES,
      TOPOLOGY,
    );

  it('a profile with "automatisch" takes the finding, "vorschlagen" leaves it open', () => {
    expect(state('f1')).toBe('open'); // web-01: Linux-Basis schlägt vor
    expect(state('f2')).toBe('open'); // app-02: Docker schlägt vor
    expect(state('f3')).toBe('auto'); // nas-01: Speicher übernimmt Platten
    expect(state('f4')).toBe('auto'); // pve-02: Proxmox übernimmt Gäste
    expect(state('f5')).toBe('declined');
    expect(findingState({ ...FINDINGS[0], decision: 'taken' }, PROFILES, TOPOLOGY)).toBe('taken');
  });

  it('counts per server what is watched, not collected, hidden and found', () => {
    const rows = coverageOf(ALL_OBJECTS, FINDINGS, PROFILES, TOPOLOGY);
    const nas = rows.find((r) => r.server === 'nas-01')!;
    const own = ALL_OBJECTS.filter((o) => o.server === 'nas-01');
    expect(nas.tags).toEqual(['storage', 'prod']);
    expect(nas.profiles).toEqual(['Linux-Basis', 'Speicher']);
    expect(nas.watched + nas.notCollected + nas.hidden).toBe(own.length);
    expect(nas.hidden).toBe(own.filter(isHidden).length);
    expect(nas.hidden).toBeGreaterThan(0);
    expect(nas.auto.map((f) => f.id)).toEqual(['f3']);
    const web = rows.find((r) => r.server === 'web-01')!;
    expect(web.open.map((f) => f.id)).toEqual(['f1']);
    expect(rows.map((r) => r.server)).toEqual([...rows.map((r) => r.server)].sort());
  });
});
