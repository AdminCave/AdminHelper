// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// R-1078 center page: the mailboxes and filters with their counts, search, the day groups,
// several entries marked read at once, the detail of the entry in the path, and "load more".

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { Writable } from 'svelte/store';
import type { NotificationItem } from '$lib/api/types';

const h = vi.hoisted(() => ({
  center: null as unknown,
  items: null as unknown,
  hasMore: null as unknown,
  segments: null as unknown,
  loadCenter: vi.fn(),
  markRead: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock('$lib/stores/notifications', async () => {
  const { writable } = await import('svelte/store');
  h.center = writable<NotificationItem[]>([]);
  h.items = writable<NotificationItem[]>([]);
  h.hasMore = writable(false);
  return {
    centerItems: h.center,
    notificationItems: h.items,
    centerHasMore: h.hasMore,
    loadCenter: h.loadCenter,
    markRead: h.markRead,
  };
});

vi.mock('$lib/router', async () => {
  const { writable } = await import('svelte/store');
  h.segments = writable<string[]>(['notifications']);
  return { segments: h.segments, navigate: h.navigate };
});

import Notifications from './Notifications.svelte';
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

const CENTER = [
  item({ id: 4, title: 'Disk full', severity: 'critical', createdAt: at(4, 9), body: 'On web' }),
  item({ id: 3, title: 'Load high', severity: 'warning', createdAt: at(3, 15), read: true }),
  item({ id: 2, title: 'New login', severity: 'info', category: 'security', createdAt: at(3, 8) }),
  item({ id: 1, title: 'Backup done', severity: 'info', createdAt: at(1, 8), read: true }),
];

const titles = (c: HTMLElement) =>
  [...c.querySelectorAll('.nc-row-title')].map((e) => e.textContent);
const railCount = (c: HTMLElement, sel: string) =>
  c.querySelector(`.nc-rail-item[${sel}] .nc-count`)?.textContent;
const rail = (c: HTMLElement, sel: string) =>
  c.querySelector<HTMLButtonElement>(`.nc-rail-item[${sel}]`)!;

describe('Notifications page', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(NOW);
    setLanguage('de');
    store<NotificationItem[]>(h.center).set(CENTER);
    store<NotificationItem[]>(h.items).set([]);
    store<boolean>(h.hasMore).set(false);
    store<string[]>(h.segments).set(['notifications']);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('loads the list on open and starts in the inbox: unread or open, by day', () => {
    const { container } = render(Notifications);
    expect(h.loadCenter).toHaveBeenCalledOnce();
    expect(titles(container)).toEqual(['Disk full', 'New login']);
    expect([...container.querySelectorAll('.nc-group')].map((e) => e.textContent)).toEqual([
      'Heute',
      'Gestern',
    ]);
    expect(railCount(container, 'data-mailbox="inbox"')).toBe('2');
    expect(railCount(container, 'data-mailbox="open"')).toBe('1');
    expect(railCount(container, 'data-mailbox="all"')).toBe('4');
  });

  it('filters by mailbox, severity, category and search, with counts of the mailbox', async () => {
    const { container } = render(Notifications);
    await fireEvent.click(rail(container, 'data-mailbox="all"'));
    expect(titles(container)).toEqual(['Disk full', 'Load high', 'New login', 'Backup done']);
    expect(railCount(container, 'data-severity="info"')).toBe('2');
    expect(railCount(container, 'data-category="monitoring"')).toBe('3');

    await fireEvent.click(rail(container, 'data-severity="info"'));
    expect(titles(container)).toEqual(['New login', 'Backup done']);
    await fireEvent.click(rail(container, 'data-category="security"'));
    expect(titles(container)).toEqual(['New login']);
    // A second click takes a filter off again.
    await fireEvent.click(rail(container, 'data-severity="info"'));
    await fireEvent.click(rail(container, 'data-category="security"'));
    expect(titles(container)).toHaveLength(4);

    const search = container.querySelector<HTMLInputElement>('.nc-search input')!;
    await fireEvent.input(search, { target: { value: 'WEB' } });
    expect(titles(container)).toEqual(['Disk full']);
    await fireEvent.input(search, { target: { value: 'nothing' } });
    expect(titles(container)).toEqual([]);
    expect(container.querySelector('.nc-scroll .empty-state')?.textContent).toContain(
      'Keine Benachrichtigungen',
    );
  });

  it('takes entries that arrived after the page loaded from the bell feed', async () => {
    const { container } = render(Notifications);
    store<NotificationItem[]>(h.items).set([
      item({ id: 5, title: 'Cert expires', severity: 'warning' }),
      { ...CENTER[0], read: true },
    ]);
    await tick();
    // The newer copy wins: "Disk full" is read now and leaves the inbox.
    expect(titles(container)).toEqual(['Cert expires', 'New login']);
  });

  it('marks the picked unread entries read at once', async () => {
    const { container } = render(Notifications);
    await fireEvent.click(rail(container, 'data-mailbox="all"'));
    expect(container.querySelector('.nc-mark-picked')).toBeNull();
    const boxes = container.querySelectorAll<HTMLInputElement>('.nc-row input[type="checkbox"]');
    await fireEvent.click(boxes[0]);
    await fireEvent.click(boxes[1]); // already read: not counted, not sent
    await fireEvent.click(boxes[2]);
    const button = container.querySelector<HTMLButtonElement>('.nc-mark-picked')!;
    expect(button.textContent).toContain('2');
    await fireEvent.click(button);
    expect(h.markRead).toHaveBeenCalledWith([4, 2]);
    await tick();
    expect(container.querySelector('.nc-mark-picked')).toBeNull();
  });

  it('shows the entry from the path in the detail, and marks it read from there', async () => {
    const { container } = render(Notifications);
    expect(container.querySelector('.nc-detail-body')).toBeNull();
    expect(container.querySelector('.nc-detail')?.textContent).toContain('Nichts ausgewählt');

    await fireEvent.click(container.querySelectorAll<HTMLButtonElement>('.nc-row-main')[0]);
    expect(h.navigate).toHaveBeenCalledWith('/notifications/4');
    store<string[]>(h.segments).set(['notifications', '4']);
    await tick();
    const detail = container.querySelector('.nc-detail-body')!;
    expect(detail.querySelector('.nc-detail-title')?.textContent).toBe('Disk full');
    expect(detail.querySelector('.nc-detail-text')?.textContent).toBe('On web');
    const fields = [...detail.querySelectorAll('dd')].map((e) => e.textContent);
    expect(fields.slice(0, 3)).toEqual(['Kritisch', 'monitoring', 'server srv-1']);
    expect(container.querySelector('.nc-row.selected .nc-row-title')?.textContent).toBe(
      'Disk full',
    );
    await fireEvent.click(detail.querySelector<HTMLButtonElement>('.nc-detail-read')!);
    expect(h.markRead).toHaveBeenCalledWith([4]);

    // A read entry has no button; an unknown id shows the empty detail.
    store<string[]>(h.segments).set(['notifications', '3']);
    await tick();
    expect(container.querySelector('.nc-detail-read')).toBeNull();
    store<string[]>(h.segments).set(['notifications', '99']);
    await tick();
    expect(container.querySelector('.nc-detail-body')).toBeNull();
  });

  it('offers more only while the server has more', async () => {
    const { container } = render(Notifications);
    expect(container.querySelector('.nc-more')).toBeNull();
    store<boolean>(h.hasMore).set(true);
    await tick();
    await fireEvent.click(container.querySelector<HTMLButtonElement>('.nc-more button')!);
    expect(h.loadCenter).toHaveBeenLastCalledWith(false);
  });

  it('offers more even when the loaded entries hold no match', async () => {
    store<boolean>(h.hasMore).set(true);
    const { container } = render(Notifications);
    const search = container.querySelector<HTMLInputElement>('.nc-search input')!;
    await fireEvent.input(search, { target: { value: 'nothing' } });
    expect(titles(container)).toEqual([]);
    await fireEvent.click(container.querySelector<HTMLButtonElement>('.nc-more button')!);
    expect(h.loadCenter).toHaveBeenLastCalledWith(false);
  });

  it('marks only picked entries the filter still shows', async () => {
    const { container } = render(Notifications);
    const boxes = container.querySelectorAll<HTMLInputElement>('.nc-row input[type="checkbox"]');
    await fireEvent.click(boxes[0]); // Disk full, critical
    await fireEvent.click(boxes[1]); // New login, info
    await fireEvent.click(rail(container, 'data-severity="info"'));
    const button = container.querySelector<HTMLButtonElement>('.nc-mark-picked')!;
    expect(button.textContent).toContain('1');
    await fireEvent.click(button);
    expect(h.markRead).toHaveBeenCalledWith([2]);
  });
});
