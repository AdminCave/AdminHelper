// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// R-1078: open as the stand-in for an incident state, day groups in local time, the panel tabs
// and the center filters. Dates are built in local time, so the tests hold in any zone.

import { describe, it, expect } from 'vitest';
import type { NotificationItem } from '$lib/api/types';
import {
  categoriesOf,
  dayBucket,
  filterItems,
  groupByDay,
  isOpen,
  matchesMailbox,
  matchesTab,
  type CenterFilter,
} from './notifications';

const item = (over: Partial<NotificationItem>): NotificationItem => ({
  id: 1,
  createdAt: '2026-06-22T10:00:00Z',
  severity: 'warning',
  category: 'monitoring',
  eventType: 'monitoring.check.transition',
  title: 't',
  body: null,
  sourceType: 'server',
  sourceId: 'srv-1',
  read: false,
  readAt: null,
  ...over,
});

const local = (y: number, m: number, d: number, h = 0, min = 0) =>
  new Date(y, m - 1, d, h, min).toISOString();

const NOW = new Date(2026, 10, 4, 9, 30); // 2026-11-04 09:30 local

describe('isOpen', () => {
  it('is unread and warning or critical', () => {
    expect(isOpen(item({ severity: 'warning' }))).toBe(true);
    expect(isOpen(item({ severity: 'critical' }))).toBe(true);
    expect(isOpen(item({ severity: 'info' }))).toBe(false);
    expect(isOpen(item({ severity: 'critical', read: true }))).toBe(false);
  });
});

describe('dayBucket', () => {
  it('splits at local midnight', () => {
    expect(dayBucket(local(2026, 11, 4, 0, 0), NOW)).toBe('today');
    expect(dayBucket(local(2026, 11, 3, 23, 59), NOW)).toBe('yesterday');
    expect(dayBucket(local(2026, 11, 3, 0, 0), NOW)).toBe('yesterday');
    expect(dayBucket(local(2026, 11, 2, 23, 59), NOW)).toBe('older');
  });

  it('crosses a month boundary', () => {
    const first = new Date(2026, 11, 1, 8, 0); // 1 December
    expect(dayBucket(local(2026, 11, 30, 12, 0), first)).toBe('yesterday');
    expect(dayBucket(local(2026, 11, 29, 12, 0), first)).toBe('older');
  });

  it('puts an entry without a readable time into older', () => {
    expect(dayBucket(null, NOW)).toBe('older');
    expect(dayBucket('not a date', NOW)).toBe('older');
  });
});

describe('groupByDay', () => {
  it('keeps the non-empty groups in order and the feed order inside', () => {
    const items = [
      item({ id: 5, createdAt: local(2026, 11, 4, 9) }),
      item({ id: 4, createdAt: local(2026, 11, 1, 9) }),
      item({ id: 3, createdAt: local(2026, 11, 4, 8) }),
      item({ id: 2, createdAt: local(2026, 10, 1, 9) }),
    ];
    expect(groupByDay(items, NOW).map((g) => [g.bucket, g.items.map((n) => n.id)])).toEqual([
      ['today', [5, 3]],
      ['older', [4, 2]],
    ]);
    expect(groupByDay([], NOW)).toEqual([]);
  });
});

describe('tabs and mailboxes', () => {
  const unreadInfo = item({ severity: 'info' });
  const readCritical = item({ severity: 'critical', read: true });
  const openWarning = item({ severity: 'warning' });

  it('panel tabs: all, unread, open', () => {
    expect([unreadInfo, readCritical, openWarning].map((n) => matchesTab(n, 'all'))).toEqual([
      true,
      true,
      true,
    ]);
    expect([unreadInfo, readCritical, openWarning].map((n) => matchesTab(n, 'unread'))).toEqual([
      true,
      false,
      true,
    ]);
    expect([unreadInfo, readCritical, openWarning].map((n) => matchesTab(n, 'open'))).toEqual([
      false,
      false,
      true,
    ]);
  });

  it('mailboxes: inbox is unread or open, open, all', () => {
    expect([unreadInfo, readCritical, openWarning].map((n) => matchesMailbox(n, 'inbox'))).toEqual([
      true,
      false,
      true,
    ]);
    expect([unreadInfo, readCritical, openWarning].map((n) => matchesMailbox(n, 'open'))).toEqual([
      false,
      false,
      true,
    ]);
    expect([unreadInfo, readCritical, openWarning].map((n) => matchesMailbox(n, 'all'))).toEqual([
      true,
      true,
      true,
    ]);
  });
});

describe('filterItems', () => {
  const items = [
    item({ id: 1, severity: 'critical', category: 'monitoring', title: 'Disk full on web-01' }),
    item({ id: 2, severity: 'info', category: 'security', title: 'Login', body: 'New DEVICE' }),
    item({ id: 3, severity: 'warning', category: 'monitoring', title: 'Load', read: true }),
  ];
  const all: CenterFilter = { mailbox: 'all', severity: null, category: null, query: '' };

  it('combines mailbox, severity, category and search', () => {
    expect(filterItems(items, all).map((n) => n.id)).toEqual([1, 2, 3]);
    expect(filterItems(items, { ...all, mailbox: 'inbox' }).map((n) => n.id)).toEqual([1, 2]);
    expect(filterItems(items, { ...all, severity: 'warning' }).map((n) => n.id)).toEqual([3]);
    expect(filterItems(items, { ...all, category: 'monitoring' }).map((n) => n.id)).toEqual([1, 3]);
    expect(
      filterItems(items, { ...all, mailbox: 'open', category: 'monitoring' }).map((n) => n.id),
    ).toEqual([1]);
  });

  it('searches title and text, ignoring case and outer spaces', () => {
    expect(filterItems(items, { ...all, query: '  disk ' }).map((n) => n.id)).toEqual([1]);
    expect(filterItems(items, { ...all, query: 'device' }).map((n) => n.id)).toEqual([2]);
    expect(filterItems(items, { ...all, query: 'nothing' })).toEqual([]);
  });
});

describe('categoriesOf', () => {
  it('counts the categories of the feed, sorted by name', () => {
    const items = [
      item({ category: 'security' }),
      item({ category: 'monitoring' }),
      item({ category: 'security' }),
    ];
    expect(categoriesOf(items)).toEqual([
      { category: 'monitoring', count: 1 },
      { category: 'security', count: 2 },
    ]);
  });
});
