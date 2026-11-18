// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-neu-p0 T5 (R-1558): Lage, Server, Objekte and the cross views all derive from
// the one object list. The Lage lists only open problems, the filter never finds a hidden object
// by status, every cross view has its columns filled, and a click opens the same drawer.

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import MockupApp from '../MockupApp.svelte';
import ObjectDrawer from '../ObjectDrawer.svelte';
import type { MonObject, Status } from '../model';
import { isHidden, statusRank } from '../grammar';
import { ACKS, ALL_OBJECTS } from '../fixtures';
import { NOW } from '../fixtures/time';
import CrossView from './CrossView.svelte';
import Lage from './Lage.svelte';
import ObjectsView from './ObjectsView.svelte';
import ServerView from './ServerView.svelte';
import { CROSS_VIEWS, NONE } from './cross';
import { NO_FILTER, filterObjects, isProblem, lageOf, nestParts, serversOf } from './lists';

afterEach(cleanup);

const PROBLEM: Status[] = ['critical', 'warning', 'unknown'];
const byKey = new Map(ALL_OBJECTS.map((o) => [o.key, o]));

function obj(key: string, extra: Partial<MonObject> = {}): MonObject {
  return {
    key,
    kind: 'service',
    name: key,
    server: 'srv-01',
    identity: [],
    status: 'ok',
    reason: 'läuft',
    since: '2026-11-18T08:00:00Z',
    metrics: [],
    ...extra,
  };
}

function rowKeys(root: Element, selector: string): string[] {
  return [...root.querySelectorAll(selector)].map((e) => e.getAttribute('data-key') ?? '');
}

describe('Lage', () => {
  it('lists only open problems, never an ok, info or stale object as a row', () => {
    const { container } = render(Lage, { objects: ALL_OBJECTS, now: NOW, onOpen: () => {} });
    const keys = rowKeys(container, 'button.row[data-key]');
    expect(keys.length).toBeGreaterThan(0);
    for (const k of keys) {
      const o = byKey.get(k);
      expect(o, k).toBeDefined();
      expect(PROBLEM, k).toContain(o?.status);
      expect(isHidden(o as MonObject), k).toBe(false);
    }
    // ...and every open problem is there, either as an entry or as a part under its instance.
    expect(new Set(keys)).toEqual(new Set(ALL_OBJECTS.filter(isProblem).map((o) => o.key)));
  });

  it('folds the stale objects of a silent host into its entry', () => {
    const lage = lageOf(ALL_OBJECTS);
    const stale = ALL_OBJECTS.filter((o) => o.status === 'stale' && !isHidden(o));
    expect(stale.length).toBeGreaterThan(0);
    const folded = lage.problems.flatMap((e) => e.stale);
    const left = lage.staleLeft.flatMap((g) => g.objects);
    expect([...folded, ...left].map((o) => o.key).sort()).toEqual(stale.map((o) => o.key).sort());
    for (const e of lage.problems.filter((x) => x.stale.length > 0)) {
      expect(e.object.kind).toBe('host');
      for (const s of e.stale) expect(s.server).toBe(e.object.server);
    }
  });

  it('keeps stale values without a host problem in their own section', () => {
    const objects = [
      obj('srv-01/host', { kind: 'host', name: 'srv-01' }),
      obj('srv-01/cpu', { kind: 'cpu', name: 'CPU', status: 'stale' }),
    ];
    const lage = lageOf(objects);
    expect(lage.problems).toEqual([]);
    expect(lage.staleLeft).toEqual([{ server: 'srv-01', objects: [objects[1]] }]);
    const { container } = render(Lage, { objects, now: NOW, onOpen: () => {} });
    expect(container.querySelector('[data-stale-key="srv-01/cpu"]')).not.toBeNull();
    expect(container.querySelector('button.row')).toBeNull();
  });

  it('nests problem parts under their problem instance, not as entries of their own', () => {
    const lage = lageOf(ALL_OBJECTS);
    const entryKeys = new Set(lage.problems.map((e) => e.object.key));
    for (const e of lage.problems) {
      for (const p of e.parts) {
        expect(p.parent).toBe(e.object.key);
        expect(entryKeys.has(p.key)).toBe(false);
      }
    }
    expect(lage.problems.some((e) => e.parts.length > 0)).toBe(true);
  });

  it('sums the green line over every object', () => {
    const lage = lageOf(ALL_OBJECTS);
    const listed = lage.problems.reduce((n, e) => n + 1 + e.parts.length + e.stale.length, 0);
    const left = lage.staleLeft.reduce((n, g) => n + g.objects.length, 0);
    expect(listed + left + lage.ok + lage.info + lage.notCollected + lage.hidden).toBe(
      ALL_OBJECTS.length,
    );
    expect(lage.servers).toBe(serversOf(ALL_OBJECTS).length);
  });

  it('shows who acknowledged a problem; the problem stays open', () => {
    expect(Object.keys(ACKS).length).toBeGreaterThan(0);
    for (const key of Object.keys(ACKS)) {
      const o = byKey.get(key);
      expect(o, key).toBeDefined();
      expect(o?.ack).toEqual(ACKS[key]);
      expect(isProblem(o as MonObject), key).toBe(true);
    }
    const { container } = render(Lage, { objects: ALL_OBJECTS, now: NOW, onOpen: () => {} });
    for (const key of Object.keys(ACKS)) {
      const line = container.querySelector(`[data-ack="${key}"]`);
      expect(line?.textContent, key).toContain(`Bestätigt von ${ACKS[key].by}`);
    }
  });
});

describe('drawer', () => {
  it('carries the acknowledgement with its note', () => {
    const [key, ack] = Object.entries(ACKS)[0];
    const { container } = render(ObjectDrawer, {
      object: byKey.get(key) as MonObject,
      now: NOW,
      onClose: () => {},
    });
    const text = container.querySelector(`[data-ack="${key}"]`)?.textContent ?? '';
    expect(text).toContain(`Bestätigt von ${ack.by}`);
    expect(text).toContain(ack.note ?? '');
  });
});

describe('object filter', () => {
  it('sorts worst first and puts hidden objects at the end', () => {
    const list = filterObjects(ALL_OBJECTS, NO_FILTER);
    expect(list).toHaveLength(ALL_OBJECTS.length);
    const firstHidden = list.findIndex(isHidden);
    expect(firstHidden).toBeGreaterThan(0);
    expect(list.slice(firstHidden).every(isHidden)).toBe(true);
    const ranks = list.slice(0, firstHidden).map((o) => statusRank(o.status));
    expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
  });

  it('never finds a hidden object by status', () => {
    const hidden = ALL_OBJECTS.filter(isHidden);
    expect(hidden.length).toBeGreaterThan(0);
    for (const status of [...PROBLEM, 'ok', 'problems'] as const) {
      const list = filterObjects(ALL_OBJECTS, { ...NO_FILTER, status });
      expect(list.some(isHidden), status).toBe(false);
    }
    const problems = filterObjects(ALL_OBJECTS, { ...NO_FILTER, status: 'problems' });
    expect(problems.map((o) => o.key).sort()).toEqual(
      ALL_OBJECTS.filter(isProblem)
        .map((o) => o.key)
        .sort(),
    );
    expect(filterObjects(ALL_OBJECTS, { ...NO_FILTER, showHidden: false })).toHaveLength(
      ALL_OBJECTS.length - hidden.length,
    );
  });

  it('combines kind, server and a search over identity and key', () => {
    const disks = filterObjects(ALL_OBJECTS, { ...NO_FILTER, kind: 'disk', server: 'nas-01' });
    expect(disks.length).toBeGreaterThan(0);
    expect(disks.every((o) => o.kind === 'disk' && o.server === 'nas-01')).toBe(true);
    const target = ALL_OBJECTS.find((o) => o.kind === 'disk' && o.identity.length > 0);
    const word = target?.identity[0] ?? '';
    const hits = filterObjects(ALL_OBJECTS, { ...NO_FILTER, query: word.toUpperCase() });
    expect(hits.map((o) => o.key)).toContain(target?.key);
    expect(filterObjects(ALL_OBJECTS, { ...NO_FILTER, query: 'gibt-es-nicht' })).toEqual([]);
  });

  it('the table follows the status filter', async () => {
    const { container, getByTestId } = render(ObjectsView, {
      objects: ALL_OBJECTS,
      now: NOW,
      onOpen: () => {},
    });
    expect(getByTestId('objects-count').textContent).toBe(
      `${ALL_OBJECTS.length} von ${ALL_OBJECTS.length} Objekten`,
    );
    const status = container.querySelectorAll('select')[1] as HTMLSelectElement;
    status.value = 'problems';
    await fireEvent.change(status);
    const n = ALL_OBJECTS.filter(isProblem).length;
    expect(getByTestId('objects-count').textContent).toBe(
      `${n} von ${ALL_OBJECTS.length} Objekten`,
    );
    const rows = [...container.querySelectorAll('tbody tr')];
    expect(rows).toHaveLength(n);
    for (const r of rows) expect(PROBLEM).toContain(r.getAttribute('data-status'));
  });
});

describe('nested parts', () => {
  it('a part follows its instance; an orphaned part stays on top', () => {
    const inst = obj('srv-01/module/x/x', { kind: 'module' });
    const part = obj('srv-01/module/x/x/a', { kind: 'module', parent: inst.key });
    const orphan = obj('srv-01/module/y/y/b', { kind: 'module', parent: 'srv-01/module/y/y' });
    const other = obj('srv-01/module/z/z', { kind: 'module' });
    expect(nestParts([part, other, inst, orphan])).toEqual([
      { object: other, depth: 0 },
      { object: inst, depth: 0 },
      { object: part, depth: 1 },
      { object: orphan, depth: 0 },
    ]);
  });
});

describe('server view', () => {
  it('shows identity, problems and a coverage line that adds up', async () => {
    const { container, getByTestId } = render(ServerView, {
      objects: ALL_OBJECTS,
      now: NOW,
      onOpen: () => {},
    });
    const select = container.querySelector('select') as HTMLSelectElement;
    select.value = 'nas-01';
    await fireEvent.change(select);
    expect(container.querySelector('[data-server="nas-01"]')).not.toBeNull();
    const own = ALL_OBJECTS.filter((o) => o.server === 'nas-01');
    const nums = (getByTestId('coverage').textContent ?? '').match(/\d+/g)?.map(Number) ?? [];
    expect(nums.reduce((a, b) => a + b, 0)).toBe(own.length);
    const listed = rowKeys(container, 'section[data-kind] button.row[data-key]');
    expect(listed.sort()).toEqual(own.map((o) => o.key).sort());
  });
});

describe('cross views', () => {
  const TH: Record<string, number> = {
    disks: 10,
    backups: 9,
    pools: 8,
    containers: 7,
    certificates: 5,
    updates: 6,
    mounts: 5,
    services: 4,
  };

  it('has the eight views of Konzept §5', () => {
    expect(CROSS_VIEWS.map((v) => v.id)).toEqual(Object.keys(TH));
  });

  it.each(CROSS_VIEWS.map((v) => v.id))(
    '%s: Zustand plus its columns, every column filled',
    (id) => {
      const view = CROSS_VIEWS.find((v) => v.id === id) as (typeof CROSS_VIEWS)[number];
      const { container } = render(CrossView, {
        objects: ALL_OBJECTS,
        now: NOW,
        view: id,
        onOpen: () => {},
      });
      const th = [...container.querySelectorAll('thead th')].map((e) => e.textContent?.trim());
      expect(th).toHaveLength(TH[id]);
      expect(th[0]).toBe('Zustand');
      const rows = view.rows(ALL_OBJECTS);
      expect(rows.length).toBeGreaterThan(0);
      expect(container.querySelectorAll('tbody tr')).toHaveLength(rows.length);
      for (const r of rows) expect(r.cells).toHaveLength(view.columns.length);
      view.columns.forEach((c, i) => {
        const filled = rows.some((r) => r.cells[i].text !== NONE.text || r.cells[i].newData);
        expect(filled, `${id}.${c.key}`).toBe(true);
      });
    },
  );

  const rowsOf = (id: string) => CROSS_VIEWS.find((v) => v.id === id)?.rows(ALL_OBJECTS) ?? [];

  it('Dienste lists only services that do not run as expected', () => {
    const rows = rowsOf('services');
    expect(rows.every((r) => r.object.kind === 'service' && r.object.status !== 'ok')).toBe(true);
    expect(rows).toHaveLength(
      ALL_OBJECTS.filter((o) => o.kind === 'service' && o.status !== 'ok').length,
    );
  });

  it('Updates & Neustart has one row per server', () => {
    const servers = rowsOf('updates').map((r) => r.object.server);
    expect(new Set(servers).size).toBe(servers.length);
    const withUpdates = new Set(
      ALL_OBJECTS.filter((o) => o.kind === 'updates').map((o) => o.server),
    );
    for (const s of withUpdates) expect(servers).toContain(s);
  });

  it('Mounts lists the fullest first, hidden ones at the end', () => {
    const rows = rowsOf('mounts');
    const shown = rows.filter((r) => !isHidden(r.object));
    const used = shown.map((r) => Number(r.object.metrics.find((m) => m.key === 'used')?.value));
    expect(used).toEqual([...used].sort((a, b) => b - a));
    expect(rows.slice(shown.length).every((r) => isHidden(r.object))).toBe(true);
  });

  it('a hidden row shows its exception instead of a status', () => {
    const view = CROSS_VIEWS.find((v) => v.rows(ALL_OBJECTS).some((r) => isHidden(r.object)));
    expect(view).toBeDefined();
    const { container } = render(CrossView, {
      objects: ALL_OBJECTS,
      now: NOW,
      view: view?.id,
      onOpen: () => {},
    });
    const tr = container.querySelector('tbody tr.hidden');
    expect(tr?.textContent).toContain('Ausgeblendet');
  });
});

describe('every view opens the same drawer', () => {
  it('a click in a cross view calls onOpen with the object key', async () => {
    const onOpen = vi.fn();
    const { container } = render(CrossView, { objects: ALL_OBJECTS, now: NOW, onOpen });
    const tr = container.querySelector('tbody tr') as HTMLElement;
    await fireEvent.click(tr.querySelector('button.open') as HTMLElement);
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen).toHaveBeenCalledWith(tr.getAttribute('data-key'));
  });

  it.each(['Lage', 'Server', 'Objekte', 'Querschnitte', 'Objektarten'])(
    '%s: a click opens the drawer of that object',
    async (label) => {
      const { container, getByRole } = render(MockupApp);
      await fireEvent.click(getByRole('tab', { name: label }));
      const target = container.querySelector(
        'main button.row[data-key], main button.open',
      ) as HTMLElement;
      expect(target, label).not.toBeNull();
      const key =
        target.getAttribute('data-key') ?? target.closest('tr')?.getAttribute('data-key') ?? '';
      await fireEvent.click(target);
      expect(container.querySelector('aside.drawer')?.getAttribute('data-key')).toBe(key);
    },
  );
});
