// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Notification feed as the bell panel and the center page show it (R-1078, R-1079): what counts
// as open, the day groups, the mailboxes and the filters. Pure functions over the feed rows, no
// store.

import type { NotificationItem, NotificationSeverity } from '$lib/api/types';
import type { TranslateFn } from '$lib/i18n';

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

/** The label of a category of the vocabulary; any other as the server wrote it. */
export function categoryLabel(category: string, tr: TranslateFn): string {
  const known: readonly string[] = NOTIFICATION_CATEGORIES;
  return known.includes(category) ? tr(`notifications.category.${category}`) : category;
}

const CHANNELS = ['bell', 'email', 'telegram', 'webhook'];

/** The label of a hub channel or an alert rule's channel; any other as it came. */
export function channelLabel(channel: string, tr: TranslateFn): string {
  return CHANNELS.includes(channel) ? tr(`notifications.channel.${channel}`) : channel;
}

/** A time of today as hh:mm, one of another day with its date; '' for none. */
export function shortTime(
  iso: string | null | undefined,
  locale: string,
  now = new Date(),
): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const time: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit' };
  return startOfDay(d) === startOfDay(now)
    ? d.toLocaleTimeString(locale, time)
    : d.toLocaleString(locale, { day: '2-digit', month: '2-digit', ...time });
}

/**
 * The state a row shows next to its title: the reader's mute first, then acknowledged (by whom)
 * or resolved; an open incident and a row without one show nothing.
 */
export function stateLabel(
  n: NotificationItem,
  tr: TranslateFn,
  locale: string,
  now = new Date(),
): string | null {
  if (n.muted) {
    return n.mutedUntil
      ? tr('notifications.state.muted', { time: shortTime(n.mutedUntil, locale, now) })
      : tr('notifications.mailbox.muted');
  }
  if (n.state === 'acked') {
    return n.ackedBy
      ? tr('notifications.state.ackedBy', { user: n.ackedBy })
      : tr('notifications.state.acked');
  }
  if (n.state === 'resolved') return tr('notifications.state.resolved');
  return null;
}
