// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// R-1078 bell and panel: the badge colour, the tabs with their counts, the day groups, read by
// quick action or by opening an entry, nothing read by opening the panel, and do not disturb.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { Writable } from 'svelte/store';
import type { NotificationItem } from '$lib/api/types';

const h = vi.hoisted(() => ({
  items: null as unknown,
  unread: null as unknown,
  open: null as unknown,
  dndUntil: null as unknown,
  markRead: vi.fn(),
  markAllRead: vi.fn(),
  closePanel: vi.fn(),
  togglePanel: vi.fn(),
  startDnd: vi.fn(),
  endDnd: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock('$lib/stores/notifications', async () => {
  const { writable } = await import('svelte/store');
  h.items = writable<NotificationItem[]>([]);
  h.unread = writable(0);
  h.open = writable(true);
  return {
    notificationItems: h.items,
    unreadCount: h.unread,
    panelOpen: h.open,
    markRead: h.markRead,
    markAllRead: h.markAllRead,
    closePanel: h.closePanel,
    togglePanel: h.togglePanel,
  };
});

vi.mock('$lib/stores/dnd', async () => {
  const { writable } = await import('svelte/store');
  h.dndUntil = writable<number | null>(null);
  return { dndUntil: h.dndUntil, startDnd: h.startDnd, endDnd: h.endDnd };
});

vi.mock('$lib/router', () => ({ navigate: h.navigate }));

import NotificationBell from './NotificationBell.svelte';
import { setLanguage } from '$lib/i18n';

const store = <T>(s: unknown) => s as Writable<T>;
const NOW = new Date(2026, 10, 4, 9, 30);
const at = (d: number, hour: number) => new Date(2026, 10, d, hour).toISOString();

const item = (over: Partial<NotificationItem>): NotificationItem => ({
  id: 1,
  createdAt: at(4, 9),
  severity: 'info',
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

const FEED = [
  item({ id: 4, title: 'Disk full', severity: 'critical', createdAt: at(4, 9) }),
  item({ id: 3, title: 'Load high', severity: 'warning', createdAt: at(3, 15), read: true }),
  item({ id: 2, title: 'Backup done', severity: 'info', createdAt: at(3, 8) }),
  item({ id: 1, title: 'Login', severity: 'info', createdAt: at(1, 8), read: true }),
];

function feed(items: NotificationItem[]) {
  store<NotificationItem[]>(h.items).set(items);
  store<number>(h.unread).set(items.filter((n) => !n.read).length);
}

const titles = (c: HTMLElement) =>
  [...c.querySelectorAll('.notif-item-title')].map((e) => e.textContent);
const groups = (c: HTMLElement) =>
  [...c.querySelectorAll('.notif-group')].map((e) => e.textContent);
const tabButtons = (c: HTMLElement) => [...c.querySelectorAll<HTMLButtonElement>('[role="tab"]')];

describe('NotificationBell', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(NOW);
    setLanguage('de');
    store<boolean>(h.open).set(true);
    store<number | null>(h.dndUntil).set(null);
    feed(FEED);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('shows the unread count, red while an unread critical entry is there', async () => {
    const { container } = render(NotificationBell);
    const badge = container.querySelector('.notif-badge')!;
    expect(badge.textContent).toBe('2');
    expect(badge.classList.contains('critical')).toBe(true);

    feed(FEED.map((n) => (n.id === 4 ? { ...n, read: true } : n)));
    await tick();
    expect(container.querySelector('.notif-badge')?.classList.contains('critical')).toBe(false);

    feed(FEED.map((n) => ({ ...n, read: true })));
    await tick();
    expect(container.querySelector('.notif-badge')).toBeNull();
  });

  it('groups by day and filters by tab, with counts', async () => {
    const { container } = render(NotificationBell);
    expect(groups(container)).toEqual(['Heute', 'Gestern', 'Älter']);
    expect(titles(container)).toEqual(['Disk full', 'Load high', 'Backup done', 'Login']);
    expect(tabButtons(container).map((b) => b.textContent?.replace(/\s+/g, ''))).toEqual([
      'Alle4',
      'Ungelesen2',
      'Offen1',
    ]);

    await fireEvent.click(tabButtons(container)[1]);
    expect(titles(container)).toEqual(['Disk full', 'Backup done']);
    expect(groups(container)).toEqual(['Heute', 'Gestern']);

    await fireEvent.click(tabButtons(container)[2]);
    expect(titles(container)).toEqual(['Disk full']);
  });

  it('says per tab when there is nothing to show', async () => {
    feed(FEED.map((n) => ({ ...n, read: true })));
    const { container } = render(NotificationBell);
    await fireEvent.click(tabButtons(container)[1]);
    expect(container.querySelector('.notif-empty')?.textContent).toBe('Alles gelesen');
    await fireEvent.click(tabButtons(container)[2]);
    expect(container.querySelector('.notif-empty')?.textContent).toBe('Nichts offen');
    feed([]);
    await fireEvent.click(tabButtons(container)[0]);
    expect(container.querySelector('.notif-empty')?.textContent).toBe('Keine Benachrichtigungen');
  });

  it('marks one entry read by quick action, without opening it', async () => {
    const { container } = render(NotificationBell);
    const quick = container.querySelectorAll<HTMLButtonElement>('.notif-item-read');
    // Only the two unread entries carry the action.
    expect(quick).toHaveLength(2);
    await fireEvent.click(quick[0]);
    expect(h.markRead).toHaveBeenCalledWith([4]);
    expect(h.navigate).not.toHaveBeenCalled();
    expect(h.closePanel).not.toHaveBeenCalled();
  });

  it('opens an entry on the center page and marks it read; a read one is not marked again', async () => {
    const { container } = render(NotificationBell);
    const mains = container.querySelectorAll<HTMLButtonElement>('.notif-item-main');
    await fireEvent.click(mains[0]);
    expect(h.markRead).toHaveBeenCalledWith([4]);
    expect(h.closePanel).toHaveBeenCalledOnce();
    expect(h.navigate).toHaveBeenCalledWith('/notifications/4');

    await fireEvent.click(mains[1]);
    expect(h.markRead).toHaveBeenCalledOnce();
    expect(h.navigate).toHaveBeenLastCalledWith('/notifications/3');
  });

  it('opening the panel marks nothing read; the foot marks all and shows the center page', async () => {
    store<boolean>(h.open).set(false);
    const { container } = render(NotificationBell);
    await fireEvent.click(container.querySelector('.notif-bell')!);
    expect(h.togglePanel).toHaveBeenCalledOnce();
    store<boolean>(h.open).set(true);
    await tick();
    expect(h.markRead).not.toHaveBeenCalled();
    expect(h.markAllRead).not.toHaveBeenCalled();

    const foot = [...container.querySelectorAll<HTMLButtonElement>('.notif-panel-foot button')];
    expect(foot.map((b) => b.textContent?.trim())).toEqual([
      'Alle als gelesen markieren',
      'Alle anzeigen',
    ]);
    await fireEvent.click(foot[0]);
    expect(h.markAllRead).toHaveBeenCalledOnce();
    await fireEvent.click(foot[1]);
    expect(h.navigate).toHaveBeenCalledWith('/notifications');
    expect(h.closePanel).toHaveBeenCalledOnce();
  });

  it('starts do not disturb from the menu, then shows the note, the muted bell and the end', async () => {
    const { container } = render(NotificationBell);
    expect(container.querySelector('.notif-dnd-note')).toBeNull();
    const bellIcon = () => container.querySelector('.notif-bell svg')?.getAttribute('class');
    expect(bellIcon()).toContain('lucide-bell');
    expect(bellIcon()).not.toContain('bell-off');

    await fireEvent.click(container.querySelector('.notif-dnd')!);
    const entries = () =>
      [...container.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].map((b) =>
        b.textContent?.trim(),
      );
    expect(entries()).toEqual(['Für 1 Stunde', 'Für 4 Stunden', 'Bis morgen früh']);
    await fireEvent.click(container.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')[1]);
    expect(h.startDnd).toHaveBeenCalledWith('4h');

    store<number | null>(h.dndUntil).set(new Date(2026, 10, 4, 13, 30).getTime());
    await tick();
    expect(container.querySelector('.notif-dnd-note span')?.textContent).toBe(
      'Ruhe bis 13:30. Kritisches kommt trotzdem durch.',
    );
    expect(bellIcon()).toContain('bell-off');
    await fireEvent.click(container.querySelector<HTMLButtonElement>('.notif-dnd-note button')!);
    expect(h.endDnd).toHaveBeenCalledOnce();

    await fireEvent.click(container.querySelector('.notif-dnd')!);
    expect(entries()).toContain('Beenden');
  });
});
