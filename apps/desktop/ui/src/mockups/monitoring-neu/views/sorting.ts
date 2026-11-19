// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Changeable orders (Kevin 2026-11-19): tables sort by a click on a column head, the server list
// and the board of "Alle Server" switch between a few orders. The choice holds for the session
// (switching tab, server or data keeps it, a reload starts at the default again): a fresh look
// always begins with the worst, and no problem slips down through an old choice. Hidden objects
// stay at the end and empty values at the bottom in both directions.

import { KIND_LABEL, byPlace, isHidden, statusRank } from '../grammar';
import type { MonObject } from '../model';

export type Dir = 'asc' | 'desc';

export interface Sort {
  col: string;
  dir: Dir;
}

export type SortValue = string | number | undefined;

export type NavOrder = 'state' | 'name';
export type BoardOrder = 'state' | 'newest' | 'name';

/** The default of every table: the Zustand column, worst first. */
export const BY_STATE: Sort = { col: 'state', dir: 'asc' };

/** What a cell shows when it has no value. */
const EMPTY: ReadonlySet<string> = new Set(['', '–', '—']);

export function isEmpty(v: SortValue): boolean {
  return v === undefined || (typeof v === 'string' && EMPTY.has(v.trim()));
}

function compare(a: string | number, b: string | number): number {
  // a === b first: Infinity ("nie") minus Infinity is NaN, and sort reads NaN as a tie it never breaks.
  if (typeof a === 'number' && typeof b === 'number') return a === b ? 0 : a - b;
  if (typeof a === 'number') return -1;
  if (typeof b === 'number') return 1;
  return a.localeCompare(b, 'de', { numeric: true, sensitivity: 'base' });
}

/** The list in the order of `value`; hidden entries at the end, empty values behind the rest in
 * both directions, a tie in the order of `tie` (ascending whatever the direction). */
export function sortBy<T>(
  list: readonly T[],
  value: (t: T) => SortValue,
  dir: Dir,
  opts: { hidden?: (t: T) => boolean; tie?: (a: T, b: T) => number } = {},
): T[] {
  const sign = dir === 'asc' ? 1 : -1;
  const keyed = list.map((t) => ({ t, v: value(t), hidden: opts.hidden?.(t) ?? false }));
  keyed.sort((a, b) => {
    if (a.hidden !== b.hidden) return a.hidden ? 1 : -1;
    if (!a.hidden) {
      const ea = isEmpty(a.v);
      const eb = isEmpty(b.v);
      if (ea !== eb) return ea ? 1 : -1;
      if (!ea) {
        const c = compare(a.v as string | number, b.v as string | number) * sign;
        if (c !== 0) return c;
      }
    }
    return opts.tie ? opts.tie(a.t, b.t) : 0;
  });
  return keyed.map((k) => k.t);
}

/** A click on a column head: the active column turns its direction, another one starts with its
 * first direction. */
export function nextSort(current: Sort, col: string, first: Dir = 'asc'): Sort {
  if (current.col === col) return { col, dir: current.dir === 'asc' ? 'desc' : 'asc' };
  return { col, dir: first };
}

export function sameSort(a: Sort, b: Sort): boolean {
  return a.col === b.col && a.dir === b.dir;
}

/** aria-sort of a column head: only the active one carries it. */
export function ariaSort(sort: Sort, col: string): 'ascending' | 'descending' | undefined {
  if (sort.col !== col) return undefined;
  return sort.dir === 'asc' ? 'ascending' : 'descending';
}

/** "4 TB", "1,8 TB", "460 GB" as gigabytes; anything else stays as it is. */
export function sizeValue(text: string | undefined): SortValue {
  const m = text?.match(/^([\d.,]+)\s*([KMGTP])i?B$/);
  if (!m) return text;
  const n = Number(m[1].replace(/\./g, '').replace(',', '.'));
  return n * 1024 ** ('KMGTP'.indexOf(m[2]) - 2);
}

/** "12 %" as 12; "unbekannt" counts as empty. */
export function percentValue(text: string | undefined): SortValue {
  const m = text?.match(/^([\d.,]+)\s*%$/);
  return m ? Number(m[1].replace(',', '.')) : undefined;
}

/** The forecast of a mount in days until full: "voll" 0, "voll in ~6 h" 0.25, "voll in ~9 Tagen"
 * 9; "gleichbleibend" never fills and counts as empty. */
export function forecastValue(text: string | undefined): SortValue {
  if (text === 'voll') return 0;
  const m = text?.match(/^voll in ~(\d+) (h|Tag|Tagen)$/);
  if (!m) return undefined;
  return m[2] === 'h' ? Number(m[1]) / 24 : Number(m[1]);
}

/** The columns of the object table and what each sorts by. */
export const OBJECT_COLUMNS: {
  col: string;
  title: string;
  first?: Dir;
  value: (o: MonObject) => SortValue;
}[] = [
  { col: 'state', title: 'Zustand', value: (o) => statusRank(o.status) },
  { col: 'name', title: 'Objekt', value: (o) => o.name },
  { col: 'kind', title: 'Art', value: (o) => KIND_LABEL[o.kind] },
  { col: 'server', title: 'Server', value: (o) => o.server },
  // Newest first: what just broke is the first question.
  { col: 'since', title: 'Seit', first: 'desc', value: (o) => o.since },
];

/** The objects in the chosen order; the default is the one of sortObjects. */
export function orderObjects(list: readonly MonObject[], sort: Sort): MonObject[] {
  const column = OBJECT_COLUMNS.find((c) => c.col === sort.col) ?? OBJECT_COLUMNS[0];
  return sortBy(list, column.value, sort.dir, { hidden: isHidden, tie: byPlace });
}

/** The choice of the session. Views read it when they mount and write it on every change. */
export const sorting: {
  objects: Sort;
  cross: Record<string, Sort>;
  nav: NavOrder;
  board: BoardOrder;
} = { objects: BY_STATE, cross: {}, nav: 'state', board: 'state' };

/** Back to the defaults (a reload; the tests between cases). */
export function resetSorting(): void {
  sorting.objects = BY_STATE;
  sorting.cross = {};
  sorting.nav = 'state';
  sorting.board = 'state';
}
