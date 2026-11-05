// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Notification feed as the bell panel and the center page show it (R-1078, R-1079): what counts
// as open, the day groups, the mailboxes and the filters. Pure functions over the feed rows, no
// store.

import type { NotificationItem, NotificationSeverity } from '$lib/api/types';

export type DayBucket = 'today' | 'yesterday' | 'older';
export type PanelTab = 'all' | 'unread' | 'open';
export type Mailbox = 'inbox' | 'open' | 'acked' | 'resolved' | 'muted' | 'all';

/** The categories the hub writes, in the order the center lists them. */
export const NOTIFICATION_CATEGORIES = [
  'monitoring',
  'security',
  'tunnel',
  'backup',
  'ansible',
  'agent',
  'session',
] as const;

/**
 * Open = a warning or critical incident nobody has acknowledged or resolved, and not muted for
 * the reader. Read or unread does not matter: a read open incident still waits for someone.
 */
export function isOpen(n: NotificationItem): boolean {
  return (n.severity === 'warning' || n.severity === 'critical') && n.state === 'open' && !n.muted;
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** The day group of `createdAt` in local time; an entry without a time is older. */
export function dayBucket(createdAt: string | null, now: Date = new Date()): DayBucket {
  if (!createdAt) return 'older';
  const at = new Date(createdAt).getTime();
  if (Number.isNaN(at)) return 'older';
  const today = startOfDay(now);
  if (at >= today) return 'today';
  const yesterday = startOfDay(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1));
  return at >= yesterday ? 'yesterday' : 'older';
}

export interface DayGroup {
  bucket: DayBucket;
  items: NotificationItem[];
}

/** The non-empty day groups in the order today, yesterday, older; the feed order inside each. */
export function groupByDay(items: NotificationItem[], now: Date = new Date()): DayGroup[] {
  const order: DayBucket[] = ['today', 'yesterday', 'older'];
  const by = new Map<DayBucket, NotificationItem[]>(order.map((b) => [b, []]));
  for (const n of items) by.get(dayBucket(n.createdAt, now))!.push(n);
  return order
    .filter((b) => by.get(b)!.length)
    .map((bucket) => ({ bucket, items: by.get(bucket)! }));
}

export function matchesTab(n: NotificationItem, tab: PanelTab): boolean {
  if (tab === 'unread') return !n.read;
  if (tab === 'open') return isOpen(n);
  return true;
}

/** Inbox = what needs the reader: unread or open, a muted row never. */
export function matchesMailbox(n: NotificationItem, mailbox: Mailbox): boolean {
  switch (mailbox) {
    case 'inbox':
      return !n.muted && (!n.read || isOpen(n));
    case 'open':
      return isOpen(n);
    case 'acked':
      return n.state === 'acked';
    case 'resolved':
      return n.state === 'resolved';
    case 'muted':
      return !!n.muted;
    case 'all':
      return true;
  }
}

export interface CenterFilter {
  mailbox: Mailbox;
  severity: NotificationSeverity | null;
  category: string | null;
  query: string;
}

/** The entries the center page lists: mailbox, severity, category and a search in title and text. */
export function filterItems(items: NotificationItem[], f: CenterFilter): NotificationItem[] {
  const q = f.query.trim().toLocaleLowerCase();
  return items.filter(
    (n) =>
      matchesMailbox(n, f.mailbox) &&
      (f.severity === null || n.severity === f.severity) &&
      (f.category === null || n.category === f.category) &&
      (!q ||
        n.title.toLocaleLowerCase().includes(q) ||
        (n.body ?? '').toLocaleLowerCase().includes(q)),
  );
}

/**
 * The categories the feed holds, with their counts: the known ones in vocabulary order, then any
 * other (a newer server may write one) by name.
 */
export function categoriesOf(items: NotificationItem[]): { category: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const n of items) counts.set(n.category, (counts.get(n.category) ?? 0) + 1);
  const known: readonly string[] = NOTIFICATION_CATEGORIES;
  const rank = (c: string) => {
    const i = known.indexOf(c);
    return i < 0 ? known.length : i;
  };
  return [...counts]
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(([category, count]) => ({ category, count }));
}
