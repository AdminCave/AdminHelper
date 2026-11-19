// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-neu-p0 T5 (R-1558): Lage, Server, Objekte and the cross views all derive from
// the one object list. The Lage lists only open problems, the filter never finds a hidden object
// by status, every cross view has its columns filled, and a click opens the same drawer.
// arch-monitoring-neu-p0-abnahme T5: the Lage shows on "Alle Server", the start of the server
// tab; the frame keeps the server list on the left, a drawer on a phone, starts every change of
// tab or server at the top and switches between the normal and the large fleet.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// jsdom has no matchMedia, which svelte/motion and the phone layout read; `phone.on` makes the
// query for at most 760 px match. It has no Web Animations either, which the cards and the scrim
// fade with (every animation ends in a microtask here), and no scrolling: `scrolled` records
// each element told to scroll.
const { phone, scrolled } = vi.hoisted(() => {
  const phone = { on: false };
  const scrolled: Element[] = [];
  window.matchMedia = (query: string) =>
    ({
      get matches() {
        return phone.on && query.includes('max-width: 760px');
      },
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
  Element.prototype.scrollTo = function (this: Element) {
    scrolled.push(this);
  } as Element['scrollTo'];
  Element.prototype.scrollIntoView = () => {};
  Element.prototype.getAnimations = () => [];
  Element.prototype.animate = function () {
    let cancelled = false;
    let done = () => {};
    return {
      playState: 'finished',
      effect: null,
      cancel: () => {
        cancelled = true;
      },
      get onfinish() {
        return done;
      },
      set onfinish(fn: () => void) {
        done = fn;
        queueMicrotask(() => {
          if (!cancelled && done === fn) fn();
        });
      },
    } as unknown as Animation;
  };
  return { phone, scrolled };
});

import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import MockupApp from '../MockupApp.svelte';
import ObjectDrawer from '../ObjectDrawer.svelte';
import type { MonObject, Status } from '../model';
import { isHidden, statusRank } from '../grammar';
import { ACKS, ALL_OBJECTS } from '../fixtures';
import { NOW } from '../fixtures/time';
import { SCALE_OBJECTS } from '../fixtures/scale';
import AllServers from './AllServers.svelte';
import CrossView from './CrossView.svelte';
import ObjectsView from './ObjectsView.svelte';
import ServerView from './ServerView.svelte';
import { CROSS_VIEWS, NONE } from './cross';
import { NO_FILTER, filterObjects, isProblem, lageOf, nestParts, serversOf } from './lists';

afterEach(() => {
  cleanup();
  phone.on = false;
  document.body.innerHTML = '';
});

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

/** "Alle Server" with metrics and every server shown: each problem as a row under its server. */
async function lageInFull(objects: MonObject[]): Promise<HTMLElement> {
  const { container, getByRole } = render(AllServers, {
    objects,
    now: NOW,
    onOpen: () => {},
    onServer: () => {},
  });
  await fireEvent.click(getByRole('radio', { name: 'Mit Kennzahlen' }));
  // By class: a role query for a named button weighs every button of the board (over a second).
  const more = () => container.querySelector<HTMLButtonElement>('button.more-btn');
  for (let b = more(); b; b = more()) await fireEvent.click(b);
  return container;
}

describe('Lage', () => {
  it('lists only open problems, never an ok, info or stale object as a row', async () => {
    const container = await lageInFull(ALL_OBJECTS);
    const keys = rowKeys(container, '.wide-card button.row[data-key]');
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

  it('keeps stale values without a host problem in their own section', async () => {
    const objects = [
      obj('srv-01/host', { kind: 'host', name: 'srv-01' }),
      obj('srv-01/cpu', { kind: 'cpu', name: 'CPU', status: 'stale' }),
    ];
    const lage = lageOf(objects);
    expect(lage.problems).toEqual([]);
    expect(lage.staleLeft).toEqual([{ server: 'srv-01', objects: [objects[1]] }]);
    const container = await lageInFull(objects);
    expect(
      container.querySelector('[data-stale-server="srv-01"] [data-stale-key="srv-01/cpu"]'),
    ).not.toBeNull();
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

  it('shows who acknowledged a problem; the problem stays open', async () => {
    expect(Object.keys(ACKS).length).toBeGreaterThan(0);
    for (const key of Object.keys(ACKS)) {
      const o = byKey.get(key);
      expect(o, key).toBeDefined();
      expect(o?.ack).toEqual(ACKS[key]);
      expect(isProblem(o as MonObject), key).toBe(true);
    }
    const container = await lageInFull(ALL_OBJECTS);
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
    const { container, getByTestId, getByRole } = render(ServerView, {
      objects: ALL_OBJECTS,
      now: NOW,
      server: 'nas-01',
      onOpen: () => {},
    });
    expect(container.querySelector('header[data-server="nas-01"] h2')?.textContent).toBe('nas-01');
    const own = ALL_OBJECTS.filter((o) => o.server === 'nas-01');
    const nums = (getByTestId('coverage').textContent ?? '').match(/\d+/g)?.map(Number) ?? [];
    expect(nums.reduce((a, b) => a + b, 0)).toBe(own.length);
    expect(
      rowKeys(container, 'section[aria-label="Probleme"] button.row[data-key]').sort(),
    ).toEqual(
      own
        .filter(isProblem)
        .map((o) => o.key)
        .sort(),
    );
    // The object-kind groups start closed; opened, every object of the server is a row.
    expect(container.querySelector('details[data-kind] button.row')).toBeNull();
    await fireEvent.click(getByRole('button', { name: 'Alle aufklappen' }));
    const listed = rowKeys(container, 'details[data-kind] button.row[data-key]');
    expect(listed.sort()).toEqual(own.map((o) => o.key).sort());
  });
});

// Drawing the large fleet takes jsdom up to about 3.5 s here; 5 s leaves a slower runner too little.
describe('frame', { timeout: 20_000 }, () => {
  const TABS = ['Server', 'Objekte', 'Querschnitte', 'Objektarten', 'Ausgeblendet', 'Abdeckung'];

  function app() {
    const r = render(MockupApp);
    const main = r.container.querySelector('main') as HTMLElement;
    const nav = (name: string) =>
      r.container.querySelector(`#server-nav button.item[data-server="${name}"]`) as HTMLElement;
    const heading = () => r.container.querySelector('main h2')?.textContent ?? '';
    return { ...r, main, nav, heading };
  }

  beforeEach(() => {
    scrolled.length = 0;
  });

  it('starts on "Alle Server" beside the server list; the tab "Lage" is gone', () => {
    const { getAllByRole, heading, nav } = app();
    expect(getAllByRole('tab').map((t) => t.textContent?.trim())).toEqual(TABS);
    expect(getAllByRole('tab', { selected: true }).map((t) => t.textContent?.trim())).toEqual([
      'Server',
    ]);
    expect(heading()).toBe('Alle Server');
    expect(nav('').getAttribute('aria-current')).toBe('true');
    expect(nav('nas-01')).not.toBeNull();
  });

  it('the server list picks the server page and leads back to "Alle Server"', async () => {
    const { container, heading, nav } = app();
    await fireEvent.click(nav('nas-01'));
    expect(heading()).toBe('nas-01');
    expect(container.querySelector('main header[data-server="nas-01"]')).not.toBeNull();
    expect(nav('nas-01').getAttribute('aria-current')).toBe('true');
    expect(container.querySelector('.m-label')?.textContent).toBe('nas-01');
    await fireEvent.click(nav(''));
    expect(heading()).toBe('Alle Server');
    expect(container.querySelector('.m-label')?.textContent).toBe('Alle Server');
  });

  it('a server card and a Lagekarte cell open the server page', async () => {
    const { container, heading, nav } = app();
    const card = container.querySelector('.board-card') as HTMLElement;
    const name = card.dataset.server ?? '';
    await fireEvent.click(card.querySelector('button.server') as HTMLElement);
    expect(heading()).toBe(name);
    await fireEvent.click(nav(''));
    // A cell with several objects opens their server and the group of that kind.
    const several = new Map<string, number>();
    for (const o of ALL_OBJECTS) {
      several.set(`${o.server}|${o.kind}`, (several.get(`${o.server}|${o.kind}`) ?? 0) + 1);
    }
    const cell = [...container.querySelectorAll<HTMLElement>('button.lk-cell')].find(
      (c) => (several.get(`${c.dataset.server}|${c.dataset.kind}`) ?? 0) > 1,
    ) as HTMLElement;
    expect(cell).toBeDefined();
    await fireEvent.click(cell);
    expect(heading()).toBe(cell.dataset.server);
    const group = container.querySelector(
      `details[data-kind="${cell.dataset.kind}"]`,
    ) as HTMLDetailsElement;
    expect(group.open).toBe(true);
  });

  it('every change of tab or server starts at the top', async () => {
    const { getByRole, main, nav } = app();
    await fireEvent.click(getByRole('tab', { name: 'Objekte' }));
    expect(scrolled).toEqual([main]);
    await fireEvent.click(getByRole('tab', { name: 'Server' }));
    await fireEvent.click(nav('nas-01'));
    expect(scrolled).toEqual([main, main, main]);
  });

  it('switches to the large fleet and back, starting again at "Alle Server" at the top', async () => {
    const big = new Set(SCALE_OBJECTS.map((o) => o.server)).size;
    const { container, getByRole, heading, main, nav } = app();
    await fireEvent.click(nav('nas-01'));
    expect(scrolled).toEqual([main]);
    await fireEvent.click(getByRole('radio', { name: `Groß · ${big} Server` }));
    expect(scrolled).toEqual([main, main]);
    expect(heading()).toBe('Alle Server');
    expect(container.querySelector('[data-testid="lage-summary"]')?.textContent).toMatch(
      new RegExp(`von ${big} Servern$`),
    );
    expect(container.querySelector('.m-hint')?.textContent).toMatch(new RegExp(`von ${big} mit`));
    await fireEvent.click(getByRole('radio', { name: 'Normal' }));
    expect(scrolled).toEqual([main, main, main]);
    const normal = new Set(ALL_OBJECTS.map((o) => o.server)).size;
    expect(container.querySelector('[data-testid="lage-summary"]')?.textContent).toMatch(
      new RegExp(`von ${normal} Servern$`),
    );
  });

  it(
    'on a phone the server list is a drawer: the button, Escape and a pick close it',
    { timeout: 40_000 },
    async () => {
      phone.on = true;
      const { container, heading, nav } = app();
      const slot = container.querySelector('#server-nav') as HTMLElement;
      const toggle = container.querySelector('button.m-pick') as HTMLElement;
      expect(toggle.getAttribute('aria-controls')).toBe('server-nav');
      expect(toggle.getAttribute('aria-expanded')).toBe('false');
      expect(slot.inert).toBe(true);

      await fireEvent.click(toggle);
      expect(toggle.getAttribute('aria-expanded')).toBe('true');
      expect(slot.inert).toBe(false);
      expect(slot.classList.contains('open')).toBe(true);
      await fireEvent.keyDown(window, { key: 'Escape' });
      expect(toggle.getAttribute('aria-expanded')).toBe('false');
      expect(slot.inert).toBe(true);

      await fireEvent.click(toggle);
      await fireEvent.click(
        container.querySelector('button[aria-label="Serverliste schließen"]') as HTMLElement,
      );
      expect(toggle.getAttribute('aria-expanded')).toBe('false');
      await waitFor(() => expect(container.querySelector('.scrim')).toBeNull(), {
        timeout: 30_000,
      });

      await fireEvent.click(toggle);
      await fireEvent.click(nav('nas-01'));
      expect(heading()).toBe('nas-01');
      expect(toggle.getAttribute('aria-expanded')).toBe('false');
      expect(slot.inert).toBe(true);
    },
  );

  it('on a wide screen the server list stays open and reachable', () => {
    const { container } = app();
    const slot = container.querySelector('#server-nav') as HTMLElement;
    expect(slot.inert).toBe(false);
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
    const tr = container.querySelector('tbody tr.is-hidden');
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

  // [case, tab, what opens the drawer there]; "Server" is the page of one server.
  it.each([
    ['Alle Server', 'Server', 'main button.p-line[data-key]'],
    ['Server', 'Server', 'main section[aria-label="Probleme"] button.row[data-key]'],
    ['Objekte', 'Objekte', 'main tr[data-key] button.open'],
    ['Querschnitte', 'Querschnitte', 'main tr[data-key] button.open'],
    ['Objektarten', 'Objektarten', 'main button.row[data-key]'],
  ])('%s: a click opens the drawer of that object', async (label, tab, selector) => {
    const { container, getByRole } = render(MockupApp);
    await fireEvent.click(getByRole('tab', { name: tab }));
    if (label === 'Server') {
      await fireEvent.click(
        container.querySelector('#server-nav button.item[data-server="nas-01"]') as HTMLElement,
      );
    }
    if (label === 'Objektarten') {
      // Object-kind groups start closed; open the first one.
      const group = container.querySelector('main details.group') as HTMLDetailsElement;
      group.open = true;
      await fireEvent(group, new Event('toggle'));
    }
    const target = container.querySelector(selector) as HTMLElement;
    expect(target, label).not.toBeNull();
    const key =
      target.getAttribute('data-key') ?? target.closest('tr')?.getAttribute('data-key') ?? '';
    await fireEvent.click(target);
    expect(container.querySelector('aside.drawer')?.getAttribute('data-key')).toBe(key);
  });
});
