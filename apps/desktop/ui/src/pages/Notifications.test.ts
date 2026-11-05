// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// R-1078, R-1079 center page: the six mailboxes and the filters with their counts, search, the
// day groups, the bulk actions on picked entries (read, acknowledge, hide), the row's count and
// state, the detail of the entry in the path, and "load more". The detail itself has its own test
// (NotificationDetail.test.ts); here it loads nothing, as there is no session.

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
  hide: vi.fn(),
  ackIncidents: vi.fn(),
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
    hide: h.hide,
    ackIncidents: h.ackIncidents,
    markUnread: vi.fn(),
    addNote: vi.fn(),
    resolveIncident: vi.fn(),
    reopenIncident: vi.fn(),
    muteIncident: vi.fn(),
    unmuteIncident: vi.fn(),
    muteServer: vi.fn(),
    unmuteServer: vi.fn(),
  };
});

vi.mock('$lib/stores/session', () => ({ currentSession: () => null }));
vi.mock('$lib/stores/monitoring', () => ({ setTab: vi.fn() }));

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
  item({
    id: 4,
    title: 'Disk full',
    severity: 'critical',
    createdAt: at(4, 9),
    body: 'On web',
    incidentId: 4,
    state: 'open',
  }),
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

  it('lists all six mailboxes in the rail, the narrow switch keeps three', async () => {
    store<NotificationItem[]>(h.center).set([
      ...CENTER,
      item({ id: 7, severity: 'critical', state: 'acked', read: true, incidentId: 7 }),
      item({ id: 6, severity: 'warning', state: 'open', muted: true, incidentId: 6 }),
      item({ id: 5, severity: 'warning', state: 'resolved', read: true, incidentId: 5 }),
    ]);
    const { container } = render(Notifications);
    const boxes = [...container.querySelectorAll('.nc-rail-item[data-mailbox]')];
    expect(boxes.map((e) => e.getAttribute('data-mailbox'))).toEqual([
      'inbox',
      'open',
      'acked',
      'resolved',
      'muted',
      'all',
    ]);
    expect(railCount(container, 'data-mailbox="acked"')).toBe('1');
    expect(railCount(container, 'data-mailbox="resolved"')).toBe('1');
    expect(railCount(container, 'data-mailbox="muted"')).toBe('1');
    expect(container.querySelectorAll('.nc-mailbox-switch button')).toHaveLength(3);
    await fireEvent.click(rail(container, 'data-mailbox="muted"'));
    expect(container.querySelectorAll('.nc-row')).toHaveLength(1);
  });

  it('shows the count and the state of a row, and the category by its label', () => {
    store<NotificationItem[]>(h.center).set([
      item({ id: 9, title: 'CPU', severity: 'warning', state: 'acked', ackedBy: 'anna', count: 3 }),
    ]);
    const { container } = render(Notifications);
    // The inbox drops a read row, but this one is unread.
    expect(container.querySelector('.nc-row-count')?.textContent).toBe('×3');
    expect(container.querySelector('.nc-row-state')?.textContent).toBe('Bestätigt · anna');
    expect(container.querySelector('.nc-row-meta')?.textContent).toContain('Monitoring ·');
    expect(rail(container, 'data-category="monitoring"').textContent).toContain('Monitoring');
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
      { ...CENTER[0], read: true, state: 'acked' },
    ]);
    await tick();
    // The newer copy wins: "Disk full" is acknowledged and read now and leaves the inbox.
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

  it('acknowledges the open incidents of the picked entries, and says what it skipped', async () => {
    h.ackIncidents.mockResolvedValue({ updated: 0, skipped: [4] });
    const { container } = render(Notifications);
    const boxes = container.querySelectorAll<HTMLInputElement>('.nc-row input[type="checkbox"]');
    await fireEvent.click(boxes[0]); // Disk full, open incident 4
    await fireEvent.click(boxes[1]); // New login, no incident: not acknowledged
    const ack = container.querySelector<HTMLButtonElement>('.nc-ack-picked')!;
    expect(ack.textContent).toContain('1 bestätigen');
    await fireEvent.click(ack);
    expect(h.ackIncidents).toHaveBeenCalledWith([4]);
    await tick();
    expect(container.querySelector('.nc-hide-picked')).toBeNull();
    expect(container.querySelector('.nc-note')?.textContent).toContain('1 nicht bestätigt');
    // The next pick clears the note.
    await fireEvent.click(boxes[1]);
    expect(container.querySelector('.nc-note')).toBeNull();
  });

  it('hides the picked entries, and clears the pick on demand', async () => {
    h.hide.mockResolvedValue(true);
    const { container } = render(Notifications);
    const boxes = container.querySelectorAll<HTMLInputElement>('.nc-row input[type="checkbox"]');
    await fireEvent.click(boxes[0]);
    await fireEvent.click(boxes[1]);
    await fireEvent.click(container.querySelector<HTMLButtonElement>('.nc-hide-picked')!);
    expect(h.hide).toHaveBeenCalledWith([4, 2]);
    await tick();
    expect(container.querySelector('.nc-bulk')).toBeNull();

    await fireEvent.click(boxes[1]);
    expect(container.querySelector('.nc-bulk')).not.toBeNull();
    await fireEvent.click(container.querySelector<HTMLButtonElement>('.nc-unpick')!);
    expect(container.querySelector('.nc-bulk')).toBeNull();
    expect(h.hide).toHaveBeenCalledOnce();
  });

  it('shows the entry from the path in the detail, and marks it read from there', async () => {
    const { container } = render(Notifications);
    expect(container.querySelector('.nc-detail .nd')).toBeNull();
    expect(container.querySelector('.nc-detail')?.textContent).toContain('Nichts ausgewählt');

    await fireEvent.click(container.querySelectorAll<HTMLButtonElement>('.nc-row-main')[0]);
    expect(h.navigate).toHaveBeenCalledWith('/notifications/4');
    store<string[]>(h.segments).set(['notifications', '4']);
    await tick();
    const detail = container.querySelector('.nc-detail .nd')!;
    expect(detail.querySelector('.nd-title')?.textContent?.trim()).toBe('Disk full');
    expect(detail.querySelector('.nd-text')?.textContent).toBe('On web');
    expect(detail.querySelector('.nd-head')?.textContent).toContain('Kritisch');
    expect(detail.querySelector('.nd-head')?.textContent).toContain('Monitoring · srv-1');
    const fields = [...detail.querySelectorAll('dd')].map((e) => e.textContent);
    expect(fields.slice(1)).toEqual(['server srv-1', '#4']);
    expect(container.querySelector('.nc-row.selected .nc-row-title')?.textContent).toBe(
      'Disk full',
    );
    await fireEvent.click(detail.querySelector<HTMLButtonElement>('.nd-read')!);
    expect(h.markRead).toHaveBeenCalledWith([4]);

    // A read entry offers unread instead; an unknown id shows the empty detail.
    store<string[]>(h.segments).set(['notifications', '3']);
    await tick();
    expect(container.querySelector('.nd-read')).toBeNull();
    expect(container.querySelector('.nd-unread')).not.toBeNull();
    store<string[]>(h.segments).set(['notifications', '99']);
    await tick();
    expect(container.querySelector('.nc-detail .nd')).toBeNull();
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
