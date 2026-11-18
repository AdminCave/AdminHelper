// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Invariants over all mockup fixtures (R-1558): every object follows the display grammar, keys
// are unique, every kind shows the states the concept names, and all data is fictitious.

import { cleanup, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import ObjectDrawer from './ObjectDrawer.svelte';
import ObjectRow from './ObjectRow.svelte';
import { STATUS_LABEL, duplicateKeys, grammarViolations, isHidden } from './grammar';
import type { Kind, MonObject, Status } from './model';
import { ALL_OBJECTS } from './fixtures';
import { NOW } from './fixtures/time';

afterEach(cleanup);

const byKind = (kind: Kind) => ALL_OBJECTS.filter((o) => o.kind === kind);
const statuses = (list: MonObject[]) =>
  new Set<Status>(list.filter((o) => !isHidden(o)).map((o) => o.status));

describe('grammar over all fixtures', () => {
  it('has fixtures at all', () => {
    expect(ALL_OBJECTS.length).toBeGreaterThan(0);
  });

  it.each(ALL_OBJECTS.map((o) => [o.key, o] as const))('%s follows the grammar', (_k, o) => {
    expect(grammarViolations(o)).toEqual([]);
  });

  it('uses every key once', () => {
    expect(duplicateKeys(ALL_OBJECTS)).toEqual([]);
  });
});

describe('states per kind (Konzept §4.1–§4.3)', () => {
  it('disk: every status, a hidden disk bound to its value, a skipped disk, new agent data', () => {
    const disks = byKind('disk');
    for (const s of ['critical', 'warning', 'unknown', 'info', 'ok'] as const)
      expect(statuses(disks).has(s), s).toBe(true);
    expect(disks.some((o) => o.exception?.effect === 'no-rating' && o.exception.boundValue)).toBe(
      true,
    );
    expect(disks.some((o) => o.exception?.effect === 'skip')).toBe(true);
    expect(disks.some((o) => o.metrics.some((m) => m.newData))).toBe(true);
    expect(disks.some((o) => o.badSince && o.badSince !== o.since)).toBe(true);
  });

  it('pool: healthy, warning and critical, each with its vdev tree', () => {
    const pools = byKind('pool');
    for (const s of ['critical', 'warning', 'ok'] as const)
      expect(statuses(pools).has(s), s).toBe(true);
    expect(pools.every((o) => o.details?.some((d) => d.type === 'vdev'))).toBe(true);
  });

  it('guest-backup: ok, warning, critical and hidden; backup-job: ok and critical', () => {
    const guests = byKind('guest-backup');
    for (const s of ['critical', 'warning', 'ok'] as const)
      expect(statuses(guests).has(s), s).toBe(true);
    expect(guests.some(isHidden)).toBe(true);
    expect(guests.some((o) => o.details?.some((d) => d.type === 'backups'))).toBe(true);
    const jobs = byKind('backup-job');
    for (const s of ['critical', 'ok'] as const) expect(statuses(jobs).has(s), s).toBe(true);
  });
});

describe('states per kind (Konzept §4.7–§4.12)', () => {
  const detailTypes = (o: MonObject) => (o.details ?? []).map((d) => d.type);

  it('host: reports, silent for 47 min, never reported, throttled', () => {
    const hosts = byKind('host');
    for (const s of ['critical', 'warning', 'unknown', 'ok'] as const)
      expect(statuses(hosts).has(s), s).toBe(true);
    expect(hosts.map((o) => o.reason)).toEqual(
      expect.arrayContaining(['Meldet sich nicht seit 47 min', 'Noch nie gemeldet']),
    );
  });

  it('every stale object belongs to a silent host', () => {
    const stale = ALL_OBJECTS.filter((o) => o.status === 'stale');
    expect(stale.length).toBeGreaterThan(0);
    const silent = new Set(
      byKind('host')
        .filter((o) => o.status === 'critical')
        .map((o) => o.server),
    );
    expect(stale.filter((o) => !silent.has(o.server)).map((o) => o.key)).toEqual([]);
  });

  it.each(['stale', 'not-collected'] as const)('%s looks different from ok', (s) => {
    const o = ALL_OBJECTS.find((x) => x.status === s && !isHidden(x));
    expect(o, s).toBeTruthy();
    const { container } = render(ObjectRow, { object: o!, now: NOW });
    const badge = container.querySelector('[class*="badge-"]');
    expect(badge?.textContent?.trim()).toBe(STATUS_LABEL[s]);
    expect(badge?.classList.contains('badge-success')).toBe(false);
  });

  it('cpu and memory: load, top processes and an OOM kill with its kernel log', () => {
    expect(
      byKind('cpu').some(
        (o) =>
          o.status === 'warning' &&
          o.metrics.some((m) => m.key === 'load' && m.status === 'warning'),
      ),
    ).toBe(true);
    expect(byKind('cpu').some((o) => detailTypes(o).includes('processes'))).toBe(true);
    const oom = byKind('memory').find((o) =>
      o.metrics.some((m) => m.key === 'oom' && m.value !== 0),
    );
    expect(oom?.status).toBe('warning');
    expect(detailTypes(oom!)).toEqual(expect.arrayContaining(['log', 'processes']));
  });

  it('mount: forecast with its line, the 20-GB rule in words, a full mount', () => {
    const mounts = byKind('mount');
    for (const s of ['critical', 'warning', 'ok'] as const)
      expect(statuses(mounts).has(s), s).toBe(true);
    const withForecast = mounts.filter((o) =>
      o.details?.some((d) => d.type === 'trend' && d.forecast?.length),
    );
    expect(withForecast.map((o) => o.status).sort()).toEqual(['critical', 'warning']);
    const used = (o: MonObject) => o.metrics.find((m) => m.key === 'used');
    const roomy = mounts.find((o) => o.status === 'ok' && Number(used(o)?.value) >= 90);
    expect(used(roomy!)?.note).toContain('20 GB');
    expect(mounts.some((o) => used(o)?.value === 100 && o.status === 'critical')).toBe(true);
  });

  it('sensor: the hardware limit next to the threshold', () => {
    expect(
      byKind('sensor').every((o) => o.metrics.some((m) => m.label === 'Hardware-Grenze')),
    ).toBe(true);
  });

  it('reboot, updates and clock: never critical, one updates kind for every source', () => {
    const sys = [...byKind('reboot'), ...byKind('updates'), ...byKind('clock')];
    expect(sys.filter((o) => o.status === 'critical').map((o) => o.key)).toEqual([]);
    expect(statuses(sys).has('not-collected')).toBe(true);
    expect(byKind('reboot').some((o) => o.metrics.some((m) => m.label === 'Nötig seit'))).toBe(
      true,
    );
    const lists = byKind('updates').find((o) =>
      o.metrics.some((m) => m.key === 'lists' && m.status === 'unknown'),
    );
    expect(lists?.status).toBe('unknown');
    const sources = byKind('updates').map((o) => o.identity.join(' '));
    for (const src of ['Agent', 'windows-host', 'proxmox-ve', 'pkg audit'])
      expect(
        sources.some((s) => s.includes(src)),
        src,
      ).toBe(true);
  });

  it('service: failed with journal, restart loop, removed', () => {
    const services = byKind('service');
    for (const s of ['critical', 'warning', 'info', 'ok'] as const)
      expect(statuses(services).has(s), s).toBe(true);
    expect(services.some((o) => o.status === 'critical' && detailTypes(o).includes('log'))).toBe(
      true,
    );
    expect(services.some((o) => o.reason.startsWith('Neustart-Schleife'))).toBe(true);
    expect(services.some((o) => o.reason.startsWith('Entfernt'))).toBe(true);
  });
});

describe('fictitious data only', () => {
  const SERVER = /^(pve|nas|web|db|mail|dc|fw|app|backup|build|test|srv)-\d\d$/;
  const text = JSON.stringify(ALL_OBJECTS);

  it('names fictitious servers only', () => {
    const bad = [...new Set(ALL_OBJECTS.map((o) => o.server))].filter((s) => !SERVER.test(s));
    expect(bad).toEqual([]);
  });

  it('uses documentation addresses only (RFC 5737)', () => {
    const ips = text.match(/\b\d{1,3}(?:\.\d{1,3}){3}\b/g) ?? [];
    const bad = ips.filter((ip) => !/^(192\.0\.2|198\.51\.100|203\.0\.113)\./.test(ip));
    expect(bad).toEqual([]);
  });

  it('uses example domains only', () => {
    const hosts = text.match(/\b[\w.-]+\.(?:com|net|org|de|io|eu|at|ch|dev|app|cloud|info)\b/g);
    const bad = (hosts ?? []).filter((h) => !/(^|\.)example\.(com|net|org)$/.test(h));
    expect(bad).toEqual([]);
  });
});

describe('every fixture renders in the drawer', () => {
  it.each(ALL_OBJECTS.map((o) => [o.key, o] as const))('%s', (_k, o) => {
    const { container } = render(ObjectDrawer, { object: o, now: NOW, onClose: () => {} });
    const headings = [...container.querySelectorAll('h3')].map((h) => h.textContent?.trim());
    for (const d of o.details ?? []) expect(headings).toContain(d.title);
  });
});
