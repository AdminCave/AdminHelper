// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Changeable orders (Kevin 2026-11-19): every order in both directions, hidden objects at the
// end and empty values at the bottom, the first page after a new order, the choice across a
// remount (a change of tab or server) and the default after a reset (a reload).
import { afterEach, describe, expect, it, vi } from 'vitest';

// jsdom has no matchMedia (svelte/motion reads it at import) and no Web Animations (the board's
// flip and fade): here every animation ends in a microtask.
vi.hoisted(() => {
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
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
});

import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { ALL_OBJECTS } from '../fixtures';
import { SCALE_OBJECTS } from '../fixtures/scale';
import { NOW } from '../fixtures/time';
import type { Kind, MonObject, Status } from '../model';
import { isHidden, sortObjects, statusRank } from '../grammar';
import AllServers from './AllServers.svelte';
import { CROSS_VIEWS, cellValue, defaultSort, orderRows } from './cross';
import CrossView from './CrossView.svelte';
import ObjectsView from './ObjectsView.svelte';
import ServerNav from './ServerNav.svelte';
import {
  lageByServer,
  needsLook,
  newestSince,
  orderBoard,
  orderServers,
  serverSummaries,
} from './servers';
import {
  BY_STATE,
  type Dir,
  type Sort,
  type SortValue,
  OBJECT_COLUMNS,
  ariaSort,
  forecastValue,
  isEmpty,
  nextSort,
  orderObjects,
  percentValue,
  resetSorting,
  sizeValue,
  sortBy,
  sorting,
} from './sorting';

afterEach(() => {
  cleanup();
  document.body.innerHTML = '';
  resetSorting();
});

const DIRS: Dir[] = ['asc', 'desc'];

/** The order the spec asks for: numbers by size before strings, strings like a German reader. */
function cmp(a: string | number, b: string | number): number {
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  if (typeof a === 'number') return -1;
  if (typeof b === 'number') return 1;
  return a.localeCompare(b, 'de', { numeric: true, sensitivity: 'base' });
}

/** Asserts the order of `values` under `dir`: every set value in order, then the empty ones. */
function expectOrdered(values: SortValue[], dir: Dir, what: string): void {
  const firstEmpty = values.findIndex(isEmpty);
  const set = firstEmpty < 0 ? values : values.slice(0, firstEmpty);
  if (firstEmpty >= 0)
    expect(values.slice(firstEmpty).every(isEmpty), `${what}: empty values at the bottom`).toBe(
      true,
    );
  for (let i = 1; i < set.length; i++) {
    const c = cmp(set[i - 1] as string | number, set[i] as string | number);
    expect(dir === 'asc' ? c <= 0 : c >= 0, `${what}: ${set[i - 1]} before ${set[i]}`).toBe(true);
  }
}

describe('sortBy', () => {
  type Row = { id: string; v: SortValue; hidden?: boolean };
  const ROWS: Row[] = [
    { id: 'a', v: 10 },
    { id: 'b', v: '–' },
    { id: 'c', v: 2 },
    { id: 'd', v: 'web-10' },
    { id: 'e', v: undefined },
    { id: 'f', v: 'web-2' },
    { id: 'g', v: 1, hidden: true },
    { id: 'h', v: '' },
    { id: 'i', v: 'Äpfel' },
    { id: 'j', v: 99, hidden: true },
    { id: 'k', v: '—' },
  ];
  const run = (dir: Dir) =>
    sortBy(ROWS, (r) => r.v, dir, {
      hidden: (r) => !!r.hidden,
      tie: (a, b) => a.id.localeCompare(b.id),
    }).map((r) => r.id);

  it('orders numbers before words ascending, words by German reading with numbers in them', () => {
    expect(run('asc')).toEqual(['c', 'a', 'i', 'f', 'd', 'b', 'e', 'h', 'k', 'g', 'j']);
  });

  it('turns the set values descending and keeps empty values and hidden rows at the end', () => {
    expect(run('desc')).toEqual(['d', 'f', 'i', 'a', 'c', 'b', 'e', 'h', 'k', 'g', 'j']);
  });

  it('breaks a tie in the tie order whatever the direction, also between two "nie" values', () => {
    // "Letztes Backup: nie" sorts as Infinity; Infinity - Infinity is NaN, which is no tie.
    for (const v of [1, Infinity]) {
      const rows = [
        { id: 'z', v },
        { id: 'x', v },
        { id: 'y', v },
      ];
      for (const dir of DIRS)
        expect(
          sortBy(rows, (r) => r.v, dir, { tie: (a, b) => a.id.localeCompare(b.id) }).map(
            (r) => r.id,
          ),
        ).toEqual(['x', 'y', 'z']);
    }
  });

  it('does not change the list it gets', () => {
    const before = ROWS.map((r) => r.id);
    run('desc');
    expect(ROWS.map((r) => r.id)).toEqual(before);
  });
});

describe('column heads', () => {
  it('a click on the active column turns its direction, another column starts with its first', () => {
    expect(nextSort(BY_STATE, 'state')).toEqual({ col: 'state', dir: 'desc' });
    expect(nextSort({ col: 'state', dir: 'desc' }, 'state')).toEqual(BY_STATE);
    expect(nextSort(BY_STATE, 'temp', 'desc')).toEqual({ col: 'temp', dir: 'desc' });
    expect(nextSort(BY_STATE, 'name')).toEqual({ col: 'name', dir: 'asc' });
  });

  it('only the active column carries aria-sort', () => {
    expect(ariaSort(BY_STATE, 'state')).toBe('ascending');
    expect(ariaSort({ col: 'state', dir: 'desc' }, 'state')).toBe('descending');
    expect(ariaSort(BY_STATE, 'name')).toBeUndefined();
  });
});

describe('sort values of cells that show text', () => {
  it('reads sizes in one unit', () => {
    expect(sizeValue('4 TB')).toBe(4096);
    expect(sizeValue('460 GB')).toBe(460);
    expect(sizeValue('1,8 TB')).toBeCloseTo(1843.2);
    expect(sizeValue('512 MB')).toBe(0.5);
    expect(sizeValue('—')).toBe('—');
  });

  it('reads percentages; "unbekannt" counts as empty', () => {
    expect(percentValue('12 %')).toBe(12);
    expect(percentValue('7,5 %')).toBe(7.5);
    expect(percentValue('unbekannt')).toBeUndefined();
  });

  it('reads the forecast as days until full; "gleichbleibend" counts as empty', () => {
    expect(forecastValue('voll')).toBe(0);
    expect(forecastValue('voll in ~6 h')).toBe(0.25);
    expect(forecastValue('voll in ~9 Tagen')).toBe(9);
    expect(forecastValue('voll in ~1 Tag')).toBe(1);
    expect(forecastValue('gleichbleibend')).toBeUndefined();
  });
});

describe('object table order', () => {
  it('the default is the order of sortObjects', () => {
    for (const all of [ALL_OBJECTS, SCALE_OBJECTS])
      expect(orderObjects(all, BY_STATE).map((o) => o.key)).toEqual(
        sortObjects(all).map((o) => o.key),
      );
  });

  it('every column in both directions, hidden objects at the end', () => {
    expect(ALL_OBJECTS.some(isHidden)).toBe(true);
    for (const c of OBJECT_COLUMNS)
      for (const dir of DIRS) {
        const out = orderObjects(ALL_OBJECTS, { col: c.col, dir });
        expect(out).toHaveLength(ALL_OBJECTS.length);
        const firstHidden = out.findIndex(isHidden);
        expect(out.slice(firstHidden).every(isHidden), `${c.col} ${dir}: hidden at the end`).toBe(
          true,
        );
        expectOrdered(out.slice(0, firstHidden).map(c.value), dir, `${c.col} ${dir}`);
      }
  });
});

describe('cross view order', () => {
  it('every column of every view in both directions, hidden rows at the end, empty at the bottom', () => {
    let hiddenSeen = 0;
    let emptySeen = 0;
    for (const v of CROSS_VIEWS) {
      const delivered = v.rows(ALL_OBJECTS);
      const cols = ['state', ...v.columns.map((c) => c.key)];
      for (const col of cols)
        for (const dir of DIRS) {
          const what = `${v.id}/${col} ${dir}`;
          const out = orderRows(v, delivered, { col, dir });
          expect(out.map((r) => r.object.key).sort(), what).toEqual(
            delivered.map((r) => r.object.key).sort(),
          );
          const firstHidden = out.findIndex((r) => isHidden(r.object));
          const shown = firstHidden < 0 ? out : out.slice(0, firstHidden);
          if (firstHidden >= 0) {
            hiddenSeen++;
            expect(
              out.slice(firstHidden).every((r) => isHidden(r.object)),
              what,
            ).toBe(true);
          }
          // The view's own default keeps the delivered order; everything else is checked here.
          if (col === defaultSort(v).col && dir === defaultSort(v).dir) continue;
          const i = v.columns.findIndex((c) => c.key === col);
          const values = shown.map((r) => (i < 0 ? r.object.status : cellValue(r.cells[i])));
          if (values.some(isEmpty)) emptySeen++;
          if (i < 0)
            expectOrdered(
              shown.map((r) => statusRank(r.object.status)),
              dir,
              what,
            );
          else expectOrdered(values, dir, what);
        }
    }
    // The fixtures must exercise both rules, or the loop above proves nothing about them.
    expect(hiddenSeen).toBeGreaterThan(0);
    expect(emptySeen).toBeGreaterThan(0);
  });

  it('the default keeps the order the view delivers (worst first, mounts by use)', () => {
    for (const v of CROSS_VIEWS) {
      const delivered = v.rows(ALL_OBJECTS);
      expect(orderRows(v, delivered, defaultSort(v))).toBe(delivered);
    }
    expect(defaultSort(CROSS_VIEWS.find((v) => v.id === 'mounts')!)).toEqual({
      col: 'used',
      dir: 'desc',
    });
  });

  it('mounts by forecast: full first, then hours, then days, the steady ones last', () => {
    const v = CROSS_VIEWS.find((x) => x.id === 'mounts')!;
    const i = v.columns.findIndex((c) => c.key === 'forecast');
    const texts = orderRows(v, v.rows(ALL_OBJECTS), { col: 'forecast', dir: 'asc' })
      .filter((r) => !isHidden(r.object))
      .map((r) => r.cells[i].text);
    expect(texts.indexOf('voll')).toBe(0);
    expect(texts.indexOf('voll in ~6 h')).toBeLessThan(texts.indexOf('voll in ~9 Tagen'));
    expect(texts.indexOf('voll in ~9 Tagen')).toBeLessThan(texts.indexOf('voll in ~140 Tagen'));
    expect(texts.at(-1)).toBe('gleichbleibend');
  });

  it('disks by capacity, largest first: terabytes before gigabytes', () => {
    const v = CROSS_VIEWS.find((x) => x.id === 'disks')!;
    const i = v.columns.findIndex((c) => c.key === 'capacity');
    expect(v.columns[i].first).toBe('desc');
    const values = orderRows(v, v.rows(ALL_OBJECTS), { col: 'capacity', dir: 'desc' })
      .filter((r) => !isHidden(r.object))
      .map((r) => r.cells[i].text);
    const tb = values.map((t) => t.endsWith('TB')).lastIndexOf(true);
    const gb = values.findIndex((t) => t.endsWith('GB'));
    expect(tb).toBeGreaterThanOrEqual(0);
    expect(gb).toBeGreaterThan(tb);
  });
});

describe('server orders', () => {
  it('the server list by name keeps worst first as its default', () => {
    const s = serverSummaries(ALL_OBJECTS);
    expect(orderServers(s, 'state')).toEqual(s);
    const byName = orderServers(s, 'name').map((x) => x.server);
    expectOrdered(byName, 'asc', 'nav name');
    expect(byName).not.toEqual(s.map((x) => x.server));
  });

  it('the board: worst first, newest problem first or by name', () => {
    const { attention } = lageByServer(ALL_OBJECTS);
    expect(orderBoard(attention, 'state')).toEqual(attention);
    expectOrdered(
      orderBoard(attention, 'name').map((g) => g.summary.server),
      'asc',
      'board name',
    );
    const newest = orderBoard(attention, 'newest');
    expectOrdered(newest.map(newestSince), 'desc', 'board newest');
    expect(newest.map((g) => g.summary.server)).not.toEqual(attention.map((g) => g.summary.server));
  });
});

// ---------- the views ----------

const text = (el: Element | null) => (el?.textContent ?? '').replace(/\s+/g, ' ').trim();
const byKey = new Map([...ALL_OBJECTS, ...SCALE_OBJECTS].map((o) => [o.key, o]));
/** The rated objects of the table in their order; hidden ones end it in their own order. */
const rowObjects = (c: HTMLElement) =>
  [...c.querySelectorAll<HTMLElement>('tbody tr[data-key]')]
    .map((tr) => byKey.get(tr.dataset.key!)!)
    .filter((o) => !isHidden(o));
const head = (c: HTMLElement, col: string) =>
  c.querySelector<HTMLButtonElement>(`.sort-btn[data-col="${col}"]`)!;
const sorted = (c: HTMLElement) =>
  [...c.querySelectorAll('th[aria-sort]')].map(
    (th) =>
      `${th.querySelector<HTMLElement>('.sort-btn')?.dataset.col} ${th.getAttribute('aria-sort')}`,
  );
function option(c: HTMLElement, group: string, label: string): HTMLButtonElement {
  const g = c.querySelector(`[role="radiogroup"][aria-label="${group}"]`)!;
  return [...g.querySelectorAll<HTMLButtonElement>('button.opt')].find((b) => text(b) === label)!;
}

describe('object table', { timeout: 20_000 }, () => {
  const show = (objects: MonObject[] = ALL_OBJECTS) =>
    render(ObjectsView, { objects, now: NOW, onOpen: () => {} });

  it('starts worst first; a click on a head sorts by it, a second click turns it', async () => {
    const { container } = show();
    expect(sorted(container)).toEqual(['state ascending']);
    await fireEvent.click(head(container, 'server'));
    expect(sorted(container)).toEqual(['server ascending']);
    expectOrdered(
      rowObjects(container).map((o) => o.server),
      'asc',
      'server asc',
    );
    await fireEvent.click(head(container, 'server'));
    expect(sorted(container)).toEqual(['server descending']);
    expectOrdered(
      rowObjects(container).map((o) => o.server),
      'desc',
      'server desc',
    );
    await fireEvent.click(head(container, 'since'));
    expect(sorted(container)).toEqual(['since descending']);
  });

  it('a new order starts at the first page', async () => {
    const { container } = show(SCALE_OBJECTS);
    expect(container.querySelectorAll('tbody tr')).toHaveLength(200);
    await fireEvent.click(container.querySelector('.page-btn')!);
    expect(container.querySelectorAll('tbody tr')).toHaveLength(400);
    await fireEvent.click(head(container, 'name'));
    expect(container.querySelectorAll('tbody tr')).toHaveLength(200);
  });

  it('the choice holds across a remount and a change of data; a reset brings the default', async () => {
    const first = show();
    await fireEvent.click(head(first.container, 'kind'));
    await fireEvent.click(head(first.container, 'kind'));
    expect(sorting.objects).toEqual({ col: 'kind', dir: 'desc' });
    cleanup();
    const again = show(SCALE_OBJECTS);
    expect(sorted(again.container)).toEqual(['kind descending']);
    cleanup();
    resetSorting();
    expect(sorted(show().container)).toEqual(['state ascending']);
  });
});

describe('cross views', { timeout: 20_000 }, () => {
  const show = (objects: MonObject[] = ALL_OBJECTS, view = 'disks') =>
    render(CrossView, { objects, now: NOW, view, onOpen: () => {} });

  it('a numeric column starts with the largest; the choice is per view and holds', async () => {
    const { container } = show();
    expect(sorted(container)).toEqual(['state ascending']);
    await fireEvent.click(head(container, 'temp'));
    expect(sorted(container)).toEqual(['temp descending']);
    await fireEvent.click(option(container, 'Querschnitt', 'Pools'));
    expect(sorted(container)).toEqual(['state ascending']);
    await fireEvent.click(option(container, 'Querschnitt', 'Platten'));
    expect(sorted(container)).toEqual(['temp descending']);
    cleanup();
    expect(sorted(show(SCALE_OBJECTS).container)).toEqual(['temp descending']);
    cleanup();
    expect(sorted(show(ALL_OBJECTS, 'mounts').container)).toEqual(['used descending']);
  });

  it('a new order starts at the first page', async () => {
    const { container } = show(SCALE_OBJECTS);
    expect(container.querySelectorAll('tbody tr')).toHaveLength(150);
    await fireEvent.click(container.querySelector('.page-btn')!);
    expect(container.querySelectorAll('tbody tr')).toHaveLength(300);
    await fireEvent.click(head(container, 'place'));
    expect(container.querySelectorAll('tbody tr')).toHaveLength(150);
  });
});

/** One host per server; a stale host has no problem but wants a look. */
function host(server: string, status: Status, since = NOW): MonObject {
  return {
    key: `${server}/host/0`,
    server,
    kind: 'host' as Kind,
    name: 'host-0',
    identity: ['x'],
    status,
    reason: status === 'ok' ? 'Läuft.' : 'Fällt aus.',
    since: since.toISOString(),
    metrics: [],
  };
}

describe('server list', { timeout: 20_000 }, () => {
  const show = (objects: MonObject[] = ALL_OBJECTS) =>
    render(ServerNav, { summaries: serverSummaries(objects), server: '', onSelect: () => {} });
  const listed = (c: HTMLElement) =>
    [...c.querySelectorAll<HTMLElement>('button.item:not(.all)')].map((b) => b.dataset.server!);

  it('lists by name within both groups; the choice holds across a remount', async () => {
    const s = serverSummaries(ALL_OBJECTS);
    const troubled = s.filter(needsLook).map((x) => x.server);
    const quiet = s.filter((x) => !needsLook(x)).map((x) => x.server);
    const { container } = show();
    expect(listed(container)).toEqual([...troubled, ...quiet]);
    await fireEvent.click(option(container, 'Reihenfolge der Server', 'Name'));
    const byName = (l: string[]) => [...l].sort((a, b) => cmp(a, b));
    expect(listed(container)).toEqual([...byName(troubled), ...byName(quiet)]);
    expect(listed(container)).not.toEqual([...troubled, ...quiet]);
    cleanup();
    expect(listed(show().container)).toEqual([...byName(troubled), ...byName(quiet)]);
  });

  it('counts a server with stale values as one with problems, like its group', () => {
    const { container } = show([
      host('a-crit', 'critical'),
      host('b-stale', 'stale'),
      host('c-ok', 'ok'),
    ]);
    expect(text(container.querySelector('h2'))).toBe('Mit Problemen 2');
    expect(text(container.querySelector('button.item.all'))).toContain('2 von 3 mit Problemen');
  });
});

describe('Alle Server board', { timeout: 20_000 }, () => {
  const show = (objects: MonObject[] = ALL_OBJECTS) =>
    render(AllServers, { objects, now: NOW, onOpen: () => {}, onServer: () => {} });
  const cards = (c: HTMLElement) =>
    [...c.querySelectorAll<HTMLElement>('.board-card')].map((el) => el.dataset.server!);

  it('switches between worst first, newest problem first and by name; the choice holds', async () => {
    const { attention } = lageByServer(ALL_OBJECTS);
    const { container } = show();
    expect(cards(container)).toEqual(attention.map((g) => g.summary.server));
    await fireEvent.click(option(container, 'Reihenfolge der Server', 'Neueste'));
    expect(cards(container)).toEqual(orderBoard(attention, 'newest').map((g) => g.summary.server));
    await fireEvent.click(option(container, 'Reihenfolge der Server', 'Name'));
    expect(cards(container)).toEqual(orderBoard(attention, 'name').map((g) => g.summary.server));
    cleanup();
    expect(cards(show().container)).toEqual(
      orderBoard(attention, 'name').map((g) => g.summary.server),
    );
  });

  it('a new order starts with the first cards again', async () => {
    const { container } = show(SCALE_OBJECTS);
    expect(cards(container)).toHaveLength(24);
    await fireEvent.click(container.querySelector('.more-btn')!);
    expect(cards(container)).toHaveLength(48);
    await fireEvent.click(option(container, 'Reihenfolge der Server', 'Name'));
    expect(cards(container)).toHaveLength(24);
  });

  it('newest: the server whose problem began last comes first', () => {
    const old = new Date(NOW.getTime() - 86_400_000);
    const { attention } = lageByServer([
      host('a', 'critical', old),
      host('b', 'warning', NOW),
      host('c', 'ok'),
    ]);
    expect(orderBoard(attention, 'state').map((g) => g.summary.server)).toEqual(['a', 'b']);
    expect(orderBoard(attention, 'newest').map((g) => g.summary.server)).toEqual(['b', 'a']);
  });
});

// The type of a choice must stay what the views write.
const _check: Sort = sorting.objects;
void _check;
