// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-ui T8 (R-1225, concept §3.14): the open findings of all servers, by
// server. Pins the groups (by name, an unknown server by its id), adopt and dismiss of
// one finding, adopt-all of one server, what adopting left out (named with the server,
// kept after the finding is gone, until closed or the next adopt), the empty, stale and
// unavailable texts, and the click that opens a server page.

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { Writable } from 'svelte/store';

const h = vi.hoisted(() => ({
  adoptFinding: vi.fn((): Promise<unknown> => Promise.resolve(null)),
  adoptAllFindings: vi.fn((): Promise<unknown> => Promise.resolve(null)),
  dismissFinding: vi.fn(() => Promise.resolve(true)),
}));

vi.mock('$lib/stores/monitoring', async () => {
  const { writable } = await import('svelte/store');
  return {
    monitoringCatalog: writable(null),
    adoptFinding: h.adoptFinding,
    adoptAllFindings: h.adoptAllFindings,
    dismissFinding: h.dismissFinding,
  };
});

import type { MonitorCatalog, MonitorFinding, Server } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import * as store from '$lib/stores/monitoring';
import FindingsView, { findingGroups } from './FindingsView.svelte';

const catalog = store.monitoringCatalog as unknown as Writable<MonitorCatalog | null>;

const SERVERS: Server[] = [
  { id: 'srv-web', name: 'web-10', hostname: 'web-10.example' },
  { id: 'srv-web2', name: 'web-2', hostname: 'web-2.example' },
  { id: 'srv-db', name: 'db-1', hostname: 'db-1.example' },
];

function finding(id: string, serverId: string, over: Partial<MonitorFinding> = {}): MonitorFinding {
  return {
    id,
    serverId,
    moduleId: 'nginx',
    moduleName: 'Nginx',
    instanceKey: `nginx@${id}`,
    kind: 'new',
    status: 'open',
    summary: {},
    catalogVersion: '1',
    firstSeen: null,
    lastSeen: null,
    decidedAt: null,
    silentChecks: [],
    droppedChecks: [],
    ...over,
  };
}

function groupsOf(el: HTMLElement): [string | null, string[]][] {
  return [...el.querySelectorAll('section')].map((s) => [
    s.getAttribute('aria-label'),
    [...s.querySelectorAll('.inbox-instance')].map((i) => i.textContent ?? ''),
  ]);
}

function noteLines(el: HTMLElement): string[] | null {
  const list = el.querySelector('.findings-note-list');
  return list ? [...list.querySelectorAll('li')].map((li) => li.textContent ?? '') : null;
}

function mount(findings: MonitorFinding[], error: string | null = null, onOpen = vi.fn()) {
  return render(FindingsView, { findings, error, servers: SERVERS, onOpen });
}

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  catalog.set(null);
});

describe('findingGroups', () => {
  it('groups by server, the servers by name, each in the order it came', () => {
    const groups = findingGroups(
      [
        finding('a', 'srv-web'),
        finding('b', 'srv-db'),
        finding('c', 'srv-web2'),
        finding('d', 'srv-web'),
      ],
      SERVERS,
    );
    expect(groups.map((g) => [g.serverId, g.serverName, g.findings.map((f) => f.id)])).toEqual([
      ['srv-db', 'db-1', ['b']],
      // Numbers by value: web-2 before web-10.
      ['srv-web2', 'web-2', ['c']],
      ['srv-web', 'web-10', ['a', 'd']],
    ]);
  });

  it('names a server the list does not know by its id', () => {
    const groups = findingGroups([finding('a', 'srv-gone'), finding('b', 'srv-db')], SERVERS);
    expect(groups.map((g) => [g.serverId, g.serverName])).toEqual([
      ['srv-db', 'db-1'],
      ['srv-gone', 'srv-gone'],
    ]);
  });

  it('is empty without findings', () => {
    expect(findingGroups([], SERVERS)).toEqual([]);
  });
});

describe('FindingsView', () => {
  it('shows one group per server with its count', () => {
    const { container } = mount([
      finding('a', 'srv-web'),
      finding('b', 'srv-db'),
      finding('c', 'srv-web'),
    ]);
    expect(screen.getByRole('region', { name: 'Neue Funde aller Server' })).toBeTruthy();
    expect(groupsOf(container)).toEqual([
      ['db-1', ['nginx@b']],
      ['web-10', ['nginx@a', 'nginx@c']],
    ]);
    const web = screen.getByRole('region', { name: 'web-10' });
    expect(web.querySelector('.findings-count')?.textContent).toBe('2');
    // Adopt all only where a server has more than one.
    expect(within(web).getByRole('button', { name: 'Alle 2 übernehmen' })).toBeTruthy();
    const db = screen.getByRole('region', { name: 'db-1' });
    expect(within(db).queryByRole('button', { name: /Alle/ })).toBeNull();
  });

  it('adopts and dismisses one finding', async () => {
    mount([finding('a', 'srv-web'), finding('b', 'srv-db')]);
    const db = screen.getByRole('region', { name: 'db-1' });
    await fireEvent.click(within(db).getByRole('button', { name: 'Übernehmen' }));
    expect(h.adoptFinding).toHaveBeenCalledExactlyOnceWith('b');
    const web = screen.getByRole('region', { name: 'web-10' });
    await fireEvent.click(within(web).getByRole('button', { name: 'Ignorieren' }));
    expect(h.dismissFinding).toHaveBeenCalledExactlyOnceWith('a');
    expect(h.adoptAllFindings).not.toHaveBeenCalled();
  });

  it('names what adopting left out with its server, after the finding is gone, until closed', async () => {
    catalog.set({
      version: '1',
      modules: [
        {
          id: 'nginx',
          name: 'Nginx',
          version: 1,
          description: '',
          instance: 'config',
          checks: [
            {
              key: 'tls',
              name: 'Zertifikat',
              sensor: 'nginx',
              interval: 60,
              fields: [],
              testObject: false,
              credential: null,
            },
          ],
          card: [],
        },
      ],
    });
    h.adoptFinding.mockImplementationOnce(() =>
      Promise.resolve({
        finding: finding('a', 'srv-web'),
        enabledChecks: ['c9'],
        disabledChecks: [],
        skippedChecks: [{ key: 'tls', reason: 'no port for this instance' }],
      }),
    );
    const view = mount([finding('a', 'srv-web')]);
    await fireEvent.click(screen.getByRole('button', { name: 'Übernehmen' }));
    await tick();
    // The finding is gone after the reload; the note stays.
    await view.rerender({ findings: [], error: null, servers: SERVERS, onOpen: vi.fn() });
    expect(screen.getByText('Nicht alles übernommen')).toBeTruthy();
    expect(noteLines(view.container)).toEqual([
      'web-10 · Nginx · nginx@a: Check „Zertifikat“ nicht angelegt — no port for this instance',
    ]);
    expect(screen.getByText('Nichts Neues gefunden')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(noteLines(view.container)).toBeNull();
  });

  it('adopts all of one server and names what it could not take', async () => {
    const list = [finding('a', 'srv-web'), finding('b', 'srv-web'), finding('c', 'srv-db')];
    h.adoptAllFindings.mockImplementationOnce(() =>
      Promise.resolve({
        adopted: [
          {
            finding: list[0],
            enabledChecks: [],
            disabledChecks: [],
            skippedChecks: [],
          },
        ],
        failed: [
          { findingId: 'b', reason: 'instance is gone' },
          { findingId: 'x', reason: 'unknown finding' },
        ],
      }),
    );
    const { container } = mount(list);
    const web = screen.getByRole('region', { name: 'web-10' });
    await fireEvent.click(within(web).getByRole('button', { name: 'Alle 2 übernehmen' }));
    await tick();
    expect(h.adoptAllFindings).toHaveBeenCalledExactlyOnceWith('srv-web');
    expect(noteLines(container)).toEqual([
      'web-10 · Nginx · nginx@b: nicht übernommen — instance is gone',
      'x: nicht übernommen — unknown finding',
    ]);
  });

  it('clears the note on the next adopt, and shows none when adopting failed', async () => {
    h.adoptAllFindings.mockImplementationOnce(() =>
      Promise.resolve({ adopted: [], failed: [{ findingId: 'a', reason: 'gone' }] }),
    );
    const { container } = mount([finding('a', 'srv-web'), finding('b', 'srv-web')]);
    await fireEvent.click(screen.getByRole('button', { name: 'Alle 2 übernehmen' }));
    await tick();
    expect(noteLines(container)).toHaveLength(1);
    // The store reports a failed adopt itself and returns null.
    await fireEvent.click(screen.getAllByRole('button', { name: 'Übernehmen' })[0]);
    await tick();
    expect(noteLines(container)).toBeNull();
  });

  it('says nothing new, or that the findings cannot be loaded', () => {
    mount([]);
    expect(screen.getByText('Nichts Neues gefunden')).toBeTruthy();
    cleanup();
    mount([], 'timeout');
    expect(screen.getByText('Funde gerade nicht abrufbar')).toBeTruthy();
    expect(screen.queryByRole('region')).toBeNull();
  });

  it('keeps the old list after a failed load and says so', () => {
    mount([finding('a', 'srv-web')], 'timeout');
    expect(screen.getByRole('status').textContent).toBe('Liste nicht aktuell: timeout');
    expect(screen.getByRole('region', { name: 'web-10' })).toBeTruthy();
  });

  it('opens the server page of a group', async () => {
    const onOpen = vi.fn();
    mount([finding('a', 'srv-web')], null, onOpen);
    await fireEvent.click(screen.getByRole('button', { name: 'web-10' }));
    expect(onOpen).toHaveBeenCalledExactlyOnceWith('srv-web');
  });
});
