// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-neu-p0-abnahme T2 (R-1558): the server-wise arrangement of the one object list
// (Kevin 2026-11-18: a server list as in today's monitoring). Every summary adds up to the
// objects of its server, the list runs worst first, and the Lage by server loses nothing.

import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/svelte';
import { ALL_OBJECTS } from '../fixtures';
import { SCALE_OBJECTS } from '../fixtures/scale';
import { isHidden, statusRank } from '../grammar';
import type { MonObject, Status } from '../model';
import { isProblem, lageOf } from './lists';
import { BAR_ORDER, lageByServer, serverSummaries } from './servers';
import StatusBar from './StatusBar.svelte';

afterEach(cleanup);

function obj(over: Partial<MonObject> & Pick<MonObject, 'key' | 'server'>): MonObject {
  return {
    kind: 'service',
    name: over.key,
    identity: ['x'],
    status: 'ok',
    reason: 'Läuft.',
    since: '2026-11-18T08:00:00Z',
    metrics: [],
    ...over,
  };
}

const NO_RATING = {
  effect: 'no-rating' as const,
  scope: 'dieses Objekt',
  reason: 'Test',
  by: 'anna',
  at: '2026-11-01T10:00:00Z',
};

describe('serverSummaries', () => {
  for (const [name, all] of [
    ['normal', ALL_OBJECTS],
    ['large', SCALE_OBJECTS],
  ] as const) {
    it(`adds up to the objects of each server (${name} data)`, () => {
      const summaries = serverSummaries(all);
      expect(summaries.map((s) => s.server).sort()).toEqual(
        [...new Set(all.map((o) => o.server))].sort(),
      );
      for (const s of summaries) {
        const own = all.filter((o) => o.server === s.server);
        const shown = own.filter((o) => !isHidden(o));
        const counted = Object.values(s.counts).reduce((a, b) => a + b, 0);
        expect(counted + s.hidden, s.server).toBe(own.length);
        expect(s.total, s.server).toBe(own.length);
        expect(s.hidden, s.server).toBe(own.length - shown.length);
        expect(s.problems, s.server).toBe(own.filter(isProblem).length);
        const rated = shown.filter((o) => o.status !== 'not-collected').map((o) => o.status);
        const worst = rated.sort((a, b) => statusRank(a) - statusRank(b))[0] ?? 'not-collected';
        expect(s.worst, s.server).toBe(worst);
      }
    });

    it(`lists the worst server first, then more problems, then by name (${name} data)`, () => {
      const s = serverSummaries(all);
      for (let i = 1; i < s.length; i++) {
        const a = s[i - 1];
        const b = s[i];
        const order =
          statusRank(a.worst) - statusRank(b.worst) ||
          b.problems - a.problems ||
          a.server.localeCompare(b.server, 'de');
        expect(order, `${a.server} before ${b.server}`).toBeLessThan(0);
      }
    });
  }

  it('rates no hidden object and shows not-collected only when nothing else reports', () => {
    const s = serverSummaries([
      obj({ key: 'a/host', server: 'a', kind: 'host', identity: ['Debian 13', '192.0.2.10'] }),
      obj({ key: 'a/x', server: 'a', status: 'critical', exception: NO_RATING }),
      obj({ key: 'a/y', server: 'a', status: 'not-collected' }),
      obj({ key: 'b/y', server: 'b', status: 'not-collected' }),
    ]);
    const a = s.find((x) => x.server === 'a');
    const b = s.find((x) => x.server === 'b');
    expect(a).toMatchObject({ worst: 'ok', problems: 0, hidden: 1, total: 3 });
    expect(a?.counts.critical).toBe(0);
    expect(a?.counts['not-collected']).toBe(1);
    expect(a?.identity).toEqual(['Debian 13', '192.0.2.10']);
    expect(b).toMatchObject({ worst: 'not-collected', identity: [] });
  });
});

describe('lageByServer', () => {
  for (const [name, all] of [
    ['normal', ALL_OBJECTS],
    ['large', SCALE_OBJECTS],
  ] as const) {
    it(`puts every problem and stale value under its server and loses none (${name} data)`, () => {
      const { attention, quiet } = lageByServer(all);
      const lage = lageOf(all);
      const order = serverSummaries(all).map((s) => s.server);
      // Servers in the order of the server list, each once, split into attention and quiet.
      expect(attention.map((x) => x.summary.server)).toEqual(
        order.filter((s) => attention.some((x) => x.summary.server === s)),
      );
      expect(
        [...attention.map((x) => x.summary.server), ...quiet.map((q) => q.server)].sort(),
      ).toEqual([...order].sort());
      // Every entry of the Lage once, under its own server.
      expect(attention.flatMap((x) => x.entries.map((e) => e.object.key)).sort()).toEqual(
        lage.problems.map((e) => e.object.key).sort(),
      );
      for (const x of attention) {
        for (const e of x.entries) expect(e.object.server).toBe(x.summary.server);
        for (const o of x.stale) expect(o.server).toBe(x.summary.server);
        expect(x.entries.length + x.stale.length).toBeGreaterThan(0);
      }
      expect(attention.reduce((n, x) => n + x.stale.length, 0)).toBe(
        lage.staleLeft.reduce((n, g) => n + g.objects.length, 0),
      );
      // A quiet server has nothing to show.
      for (const q of quiet) expect(q.problems, q.server).toBe(0);
    });
  }

  it('shows stale values with their server and folds those of a silent host into it', () => {
    const { attention, quiet } = lageByServer([
      obj({ key: 'a/host', server: 'a', kind: 'host' }),
      obj({ key: 'a/x', server: 'a', status: 'stale' }),
      obj({ key: 'b/host', server: 'b', kind: 'host', status: 'critical' }),
      obj({ key: 'b/x', server: 'b', status: 'stale' }),
      obj({ key: 'c/host', server: 'c', kind: 'host' }),
      obj({ key: 'd/x', server: 'd', status: 'critical', exception: NO_RATING }),
    ]);
    expect(
      attention.map((x) => ({
        server: x.summary.server,
        entries: x.entries.map((e) => [e.object.key, e.stale.map((o) => o.key)]),
        stale: x.stale.map((o) => o.key),
      })),
    ).toEqual([
      { server: 'b', entries: [['b/host', ['b/x']]], stale: [] },
      { server: 'a', entries: [], stale: ['a/x'] },
    ]);
    expect(quiet.map((q) => q.server)).toEqual(['d', 'c']);
  });
});

describe('StatusBar', () => {
  const counts = (over: Partial<Record<Status, number>>): Record<Status, number> => ({
    critical: 0,
    warning: 0,
    unknown: 0,
    stale: 0,
    info: 0,
    'not-collected': 0,
    ok: 0,
    ...over,
  });

  it('shows one segment per state present, worst first, then the hidden ones', () => {
    const { container } = render(StatusBar, {
      counts: counts({ ok: 30, critical: 2, info: 1, warning: 3 }),
      hidden: 4,
    });
    const segs = [...container.querySelectorAll('.seg')];
    expect(segs.map((s) => s.getAttribute('data-st'))).toEqual([
      'critical',
      'warning',
      'info',
      'ok',
      'hidden',
    ]);
    expect(segs.map((s) => (s as HTMLElement).style.flexGrow)).toEqual(['2', '3', '1', '30', '4']);
    expect(container.querySelector('[role="img"]')?.getAttribute('aria-label')).toBe(
      '2 Kritisch, 3 Warnung, 1 Info, 30 OK, 4 ausgeblendet',
    );
    expect(BAR_ORDER).toEqual([
      'critical',
      'warning',
      'unknown',
      'stale',
      'info',
      'not-collected',
      'ok',
    ]);
  });

  it('takes a label from the caller', () => {
    const { container } = render(StatusBar, {
      counts: counts({ ok: 1 }),
      label: 'web-01: alles OK',
    });
    expect(container.querySelector('[role="img"]')?.getAttribute('aria-label')).toBe(
      'web-01: alles OK',
    );
  });
});
