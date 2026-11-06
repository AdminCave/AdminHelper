// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// R-1079 incident detail: head, fields and history from the incident, the team actions by state
// and only with sight on every server, the reader's mute and its undo, a note, a failed load, a
// reload when the row changes, and a row without an incident.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { IncidentDetail, NotificationItem } from '$lib/api/types';

const h = vi.hoisted(() => ({
  fetchIncident: vi.fn(),
  ackIncidents: vi.fn(),
  resolveIncident: vi.fn(),
  reopenIncident: vi.fn(),
  addNote: vi.fn(),
  markRead: vi.fn(),
  markUnread: vi.fn(),
  muteIncident: vi.fn(),
  unmuteIncident: vi.fn(),
  muteServer: vi.fn(),
  unmuteServer: vi.fn(),
  setTab: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock('$lib/api/notifications', () => ({
  notificationsApi: { fetchIncident: h.fetchIncident },
}));
vi.mock('$lib/stores/session', () => ({ currentSession: () => ({ username: 'me' }) }));
vi.mock('$lib/stores/monitoring', () => ({ setTab: h.setTab }));
vi.mock('$lib/router', () => ({ navigate: h.navigate }));
vi.mock('$lib/stores/notifications', () => ({
  ackIncidents: h.ackIncidents,
  resolveIncident: h.resolveIncident,
  reopenIncident: h.reopenIncident,
  addNote: h.addNote,
  markRead: h.markRead,
  markUnread: h.markUnread,
  muteIncident: h.muteIncident,
  unmuteIncident: h.unmuteIncident,
  muteServer: h.muteServer,
  unmuteServer: h.unmuteServer,
}));

import NotificationDetail from './NotificationDetail.svelte';
import { setLanguage } from '$lib/i18n';

const NOW = new Date(2026, 10, 4, 9, 30);
const at = (hour: number, min = 0) => new Date(2026, 10, 4, hour, min).toISOString();

const ROW: NotificationItem = {
  id: 40,
  createdAt: at(9),
  severity: 'critical',
  category: 'monitoring',
  eventType: 'monitoring.check.transition',
  title: 'Disk full',
  body: 'On web',
  sourceType: 'server',
  sourceId: 'srv-1',
  read: false,
  readAt: null,
  incidentId: 4,
  state: 'open',
  count: 2,
  notifiedAt: at(9),
  muted: false,
  mutedUntil: null,
  muteSource: null,
};

const row = (over: Partial<NotificationItem> = {}): NotificationItem => ({ ...ROW, ...over });

const detail = (over: Partial<IncidentDetail> = {}): IncidentDetail => ({
  id: 4,
  state: 'open',
  severity: 'critical',
  category: 'monitoring',
  eventType: 'monitoring.check.transition',
  title: 'Disk full',
  body: 'On web',
  sourceType: 'server',
  sourceId: 'srv-1',
  count: 2,
  firstAt: at(8, 50),
  lastAt: at(9),
  ackedBy: null,
  ackedAt: null,
  resolvedBy: null,
  resolvedAt: null,
  bundle: false,
  servers: [{ id: 'srv-1', name: 'web-01', recoveredAt: null }],
  rules: [
    { name: 'Disk', channel: 'webhook', ok: true },
    { name: 'Disk', channel: 'email', ok: false },
  ],
  channels: ['bell', 'email'],
  history: [
    {
      id: 1,
      at: at(8, 50),
      kind: 'triggered',
      actor: null,
      text: 'Disk full\nOn web',
      severity: 'critical',
      serverId: 'srv-1',
    },
    {
      id: 2,
      at: at(8, 50),
      kind: 'notified',
      actor: null,
      text: 'bell, email',
      severity: null,
      serverId: null,
    },
  ],
  canAct: true,
  row: ROW,
  ...over,
});

// The fetch answers in a microtask; the page then needs a render pass.
const flush = () => new Promise((r) => setTimeout(r, 0)).then(() => tick());
const fields = (c: HTMLElement) => [...c.querySelectorAll('dd')].map((e) => e.textContent);
const menuEntries = (c: HTMLElement) =>
  [...c.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].map((b) => b.textContent?.trim());

async function show(item: NotificationItem, d: IncidentDetail | Error = detail()) {
  if (d instanceof Error) h.fetchIncident.mockRejectedValue(d);
  else h.fetchIncident.mockResolvedValue(d);
  const view = render(NotificationDetail, { item });
  await flush();
  return view;
}

describe('NotificationDetail', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(NOW);
    setLanguage('de');
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('shows the incident: head, count, fields and its history', async () => {
    const { container } = await show(row());
    expect(h.fetchIncident).toHaveBeenCalledWith({ username: 'me' }, 4);
    expect(container.querySelector('.nd-head')?.textContent).toContain('Kritisch');
    expect(container.querySelector('.nd-source')?.textContent?.trim()).toBe('Monitoring · web-01');
    expect(container.querySelector('.nd-count')?.textContent).toBe('×2');
    expect(container.querySelector('.nd-text')?.textContent).toBe('On web');
    expect(fields(container).slice(1)).toEqual([
      'web-01',
      'Disk',
      'E-Mail, Webhook, E-Mail (fehlgeschlagen)',
      '#4',
    ]);
    const entries = [...container.querySelectorAll('.nd-entry')];
    expect(entries.map((e) => e.querySelector('.nd-entry-kind')?.textContent)).toEqual([
      'Ausgelöst',
      'Benachrichtigt',
    ]);
    expect(entries[0].querySelector('.nd-entry-meta')?.textContent).toContain(
      '08:50 · automatisch',
    );
    expect(entries[1].querySelector('.nd-entry-text')?.textContent?.trim()).toBe('Glocke, E-Mail');
  });

  it('says bell only when no other channel went out', async () => {
    const { container } = await show(row(), detail({ channels: ['bell'], rules: null }));
    expect(fields(container).slice(1)).toEqual(['web-01', '—', 'nur Glocke', '#4']);
  });

  it('offers acknowledge and resolve on an open incident', async () => {
    const resolved = detail({ state: 'resolved', resolvedBy: 'me' });
    h.resolveIncident.mockResolvedValue(resolved);
    const { container } = await show(row());
    expect(container.querySelector('.nd-reopen')).toBeNull();
    await fireEvent.click(container.querySelector<HTMLButtonElement>('.nd-ack')!);
    expect(h.ackIncidents).toHaveBeenCalledWith([4]);
    await fireEvent.click(container.querySelector<HTMLButtonElement>('.nd-resolve')!);
    expect(h.resolveIncident).toHaveBeenCalledWith(4);
  });

  it('offers resolve on an acknowledged incident and reopen on a resolved one', async () => {
    const view = await show(row({ state: 'acked', ackedBy: 'anna' }));
    const c = view.container;
    expect(c.querySelector('.nd-ack')).toBeNull();
    expect(c.querySelector('.nd-resolve')).not.toBeNull();
    expect(c.querySelector('.nd-head')?.textContent).toContain('Bestätigt · anna');

    h.fetchIncident.mockResolvedValue(detail({ state: 'resolved' }));
    await view.rerender({ item: row({ state: 'resolved', resolvedBy: 'anna' }) });
    await flush();
    // A changed row loads the detail again.
    expect(h.fetchIncident).toHaveBeenCalledTimes(2);
    expect(c.querySelector('.nd-resolve')).toBeNull();
    await fireEvent.click(c.querySelector<HTMLButtonElement>('.nd-reopen')!);
    expect(h.reopenIncident).toHaveBeenCalledWith(4);
  });

  it('offers no team action without sight on every server', async () => {
    const { container } = await show(row(), detail({ canAct: false }));
    expect(container.querySelector('.nd-ack')).toBeNull();
    expect(container.querySelector('.nd-resolve')).toBeNull();
    expect(container.querySelector('.nd-note')).toBeNull();
    expect(container.querySelector('.nd-hint')?.textContent).toContain('alle Server');
    // Read and the own mute stay the reader's.
    expect(container.querySelector('.nd-read')).not.toBeNull();
    expect(container.querySelector('.nd-mute')).not.toBeNull();
  });

  it('mutes for an hour, until tomorrow 07:00 or the server for a day, and edits the rule', async () => {
    const { container } = await show(row());
    const open = () => fireEvent.click(container.querySelector<HTMLButtonElement>('.nd-mute')!);
    const choose = (i: number) =>
      fireEvent.click(container.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')[i]);

    await open();
    expect(menuEntries(container)).toEqual([
      '1 Stunde',
      'Bis morgen 07:00',
      'web-01 für 24 h',
      'Regel bearbeiten',
    ]);
    await choose(0);
    expect(h.muteIncident).toHaveBeenLastCalledWith(
      4,
      new Date(NOW.getTime() + 3600_000).toISOString(),
    );
    await open();
    await choose(1);
    expect(h.muteIncident).toHaveBeenLastCalledWith(4, new Date(2026, 10, 5, 7, 0).toISOString());
    await open();
    await choose(2);
    expect(h.muteServer).toHaveBeenCalledWith(
      'srv-1',
      new Date(NOW.getTime() + 86_400_000).toISOString(),
    );
    await open();
    await choose(3);
    expect(h.setTab).toHaveBeenCalledWith('alerts');
    expect(h.navigate).toHaveBeenCalledWith('/monitoring');
  });

  it('offers neither the server nor the rule where there is none', async () => {
    const { container } = await show(row({ category: 'security', sourceType: 'user' }));
    await fireEvent.click(container.querySelector<HTMLButtonElement>('.nd-mute')!);
    expect(menuEntries(container)).toEqual(['1 Stunde', 'Bis morgen 07:00']);
  });

  it('undoes the mute where it came from: the incident or the server', async () => {
    const until = at(10, 30);
    const view = await show(row({ muted: true, mutedUntil: until, muteSource: 'incident' }));
    const c = view.container;
    expect(c.querySelector('.nd-mute')).toBeNull();
    expect(c.querySelector('.nd-head')?.textContent).toContain('Stumm bis 10:30');
    await fireEvent.click(c.querySelector<HTMLButtonElement>('.nd-unmute')!);
    expect(h.unmuteIncident).toHaveBeenCalledWith(4);

    await view.rerender({ item: row({ muted: true, mutedUntil: until, muteSource: 'server' }) });
    await fireEvent.click(c.querySelector<HTMLButtonElement>('.nd-unmute')!);
    expect(h.unmuteServer).toHaveBeenCalledWith('srv-1');
    expect(h.unmuteIncident).toHaveBeenCalledOnce();
  });

  it('adds a note on Enter and shows the answer', async () => {
    const noted = detail({
      history: [
        ...detail().history,
        {
          id: 3,
          at: at(9, 20),
          kind: 'note',
          actor: 'me',
          text: 'TCK-1',
          severity: null,
          serverId: null,
        },
      ],
    });
    h.addNote.mockResolvedValue(noted);
    const { container } = await show(row());
    const input = container.querySelector<HTMLInputElement>('.nd-note input')!;
    await fireEvent.input(input, { target: { value: '  TCK-1 ' } });
    await fireEvent.keyDown(input, { key: 'Enter' });
    await flush();
    expect(h.addNote).toHaveBeenCalledWith(4, 'TCK-1');
    const last = [...container.querySelectorAll('.nd-entry')].at(-1)!;
    expect(last.querySelector('.nd-entry-kind')?.textContent).toBe('Notiz');
    expect(last.querySelector('.nd-entry-meta')?.textContent).toContain('me');
    expect(input.value).toBe('');
  });

  it('keeps the typed note when adding it fails', async () => {
    h.addNote.mockResolvedValueOnce(null);
    const { container } = await show(row());
    const input = container.querySelector<HTMLInputElement>('.nd-note input')!;
    await fireEvent.input(input, { target: { value: 'TCK-2' } });
    await fireEvent.keyDown(input, { key: 'Enter' });
    await flush();
    expect(h.addNote).toHaveBeenCalledWith(4, 'TCK-2');
    expect(input.value).toBe('TCK-2');
    expect(container.querySelectorAll('.nd-entry')).toHaveLength(2);
  });

  it('keeps the row when the detail does not load', async () => {
    const { container } = await show(row(), new Error('down'));
    expect(container.querySelector('.nd-failed')?.textContent).toBe(
      'Details konnten nicht geladen werden.',
    );
    expect(container.querySelector('.nd-title')?.textContent).toContain('Disk full');
    expect(container.querySelector('.nd-ack')).toBeNull();
    expect(fields(container).slice(1)).toEqual(['server srv-1', '#4']);
  });

  it('drops a late answer for the incident shown before', async () => {
    let answer: (d: IncidentDetail) => void = () => {};
    h.fetchIncident.mockReturnValueOnce(new Promise((r) => (answer = r)));
    const view = render(NotificationDetail, { item: row() });
    h.fetchIncident.mockResolvedValue(
      detail({ id: 5, servers: [{ id: 'srv-1', name: 'db-01', recoveredAt: null }] }),
    );
    await view.rerender({ item: row({ id: 50, incidentId: 5 }) });
    await flush();
    answer(detail());
    await flush();
    expect(view.container.querySelector('.nd-source')?.textContent?.trim()).toBe(
      'Monitoring · db-01',
    );
  });

  it('shows a row without an incident without loading anything', async () => {
    const { container } = await show(
      row({ id: 7, incidentId: null, state: null, count: null, read: true }),
    );
    expect(h.fetchIncident).not.toHaveBeenCalled();
    expect(container.querySelector('.nd-mute')).toBeNull();
    expect(container.querySelector('.nd-history')).toBeNull();
    expect(fields(container).slice(1)).toEqual(['server srv-1', '#7']);
    await fireEvent.click(container.querySelector<HTMLButtonElement>('.nd-unread')!);
    expect(h.markUnread).toHaveBeenCalledWith([7]);
  });
});
