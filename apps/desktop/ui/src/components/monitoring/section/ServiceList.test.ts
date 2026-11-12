// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-ui-3 T7 (R-1226): the full service list of a server in the Desktop.
// Pins the state groups, the reason, aliases with their target, one row per unit, the
// filter with its counts, the search over alias names, the sort with missing values last,
// "—" for fields a platform does not send, and the empty, no-agent, error and late states.

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { MonitorServiceEntry, MonitorServiceInventory } from '$lib/api/types';
import { IpcError } from '$lib/utils/errors';

const h = vi.hoisted(() => ({ fetch: vi.fn() }));
// A wait gets a bound of 30 s (testing.md, Fristen); testing-library's default is 1 s.
const WAIT = { timeout: 30_000 };

vi.mock('$lib/api/monitoring', () => ({ monitoringApi: { fetchServerServices: h.fetch } }));
vi.mock('$lib/stores/session', () => ({
  currentSession: () => ({ serverUrl: 'https://hub.example' }),
}));

import { setLanguage } from '$lib/i18n';
import ServiceList, { filterRows, reasonOf, serviceRows, stateOf } from './ServiceList.svelte';

function ago(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString().replace(/\.\d{3}Z$/, 'Z');
}

function services(): MonitorServiceEntry[] {
  return [
    {
      unit: 'nginx.service',
      active_state: 'failed',
      enabled_state: 'enabled',
      sub_state: 'failed',
      result: 'exit-code',
      exit: 'status=1',
      since: ago(5),
      restarts: '3',
      memory_bytes: '0',
    },
    {
      unit: 'ssh.service',
      active_state: 'active',
      enabled_state: 'enabled',
      sub_state: 'running',
      result: 'success',
      since: ago(120),
      restarts: '0',
      memory_bytes: '4194304',
    },
    {
      unit: 'sshd.service',
      active_state: 'inactive',
      enabled_state: 'alias',
      alias_of: 'ssh.service',
    },
    {
      unit: 'backup.service',
      active_state: 'inactive',
      enabled_state: 'static',
      sub_state: 'dead',
      result: 'success',
      exit: 'status=0',
      since: ago(30),
      restarts: '0',
      memory_bytes: '1048576',
    },
    // A Windows service: no sub-state, since, restarts nor RAM.
    { unit: 'Spooler', active_state: 'inactive', enabled_state: 'unknown', exit: 'win32=1067' },
  ];
}

function inventory(
  over: Partial<MonitorServiceInventory> = {},
  serverId = 'srv-1',
): MonitorServiceInventory {
  return {
    serverId,
    reportedAt: ago(10),
    logLines: true,
    services: services(),
    logs: {},
    ...over,
  };
}

function rows(container: HTMLElement): string[][] {
  return Array.from(container.querySelectorAll('tbody tr')).map((tr) =>
    Array.from(tr.querySelectorAll('td')).map((td) =>
      (td.textContent ?? '').replace(/\s+/g, ' ').trim(),
    ),
  );
}

function names(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('tbody .svc-unit')).map((e) => e.textContent ?? '');
}

function radio(container: HTMLElement, label: string): HTMLElement {
  const all = Array.from(container.querySelectorAll<HTMLElement>('[role="radio"]'));
  const found = all.find((b) => b.textContent?.trim() === label);
  if (!found) throw new Error(`no filter ${label}: ${all.map((b) => b.textContent).join('|')}`);
  return found;
}

function sortButton(container: HTMLElement, label: string): HTMLElement {
  const th = Array.from(container.querySelectorAll('thead th')).find(
    (e) => e.textContent?.trim() === label,
  );
  if (!th) throw new Error(`no column ${label}`);
  return th.querySelector('button') as HTMLElement;
}

async function shown(over: Partial<MonitorServiceInventory> = {}): Promise<HTMLElement> {
  h.fetch.mockResolvedValue(inventory(over));
  const { container } = render(ServiceList, { serverId: 'srv-1' });
  await waitFor(() => expect(container.querySelector('table')).not.toBeNull(), WAIT);
  return container;
}

beforeAll(() => setLanguage('de'));
// A block body: a function beforeEach returns is a cleanup hook, and mockReset returns the mock.
beforeEach(() => {
  h.fetch.mockReset();
});
afterEach(() => cleanup());

describe('service rows', () => {
  it('groups failed, active and everything else as inactive', () => {
    expect(stateOf('failed')).toBe('failed');
    for (const s of ['active', 'reloading', 'refreshing']) expect(stateOf(s)).toBe('active');
    for (const s of [
      'inactive',
      'activating',
      'deactivating',
      'maintenance',
      'unknown',
      undefined,
    ]) {
      expect(stateOf(s)).toBe('inactive');
    }
  });

  it('gives a reason unless the result is success, an exit alone without a result', () => {
    expect(reasonOf({ unit: 'a', result: 'exit-code', exit: 'status=1' })).toBe(
      'exit-code, status=1',
    );
    expect(reasonOf({ unit: 'a', result: 'success', exit: 'status=0' })).toBeNull();
    expect(reasonOf({ unit: 'a', result: 'timeout' })).toBe('timeout');
    expect(reasonOf({ unit: 'a', exit: 'win32=1067' })).toBe('win32=1067');
    expect(reasonOf({ unit: 'a' })).toBeNull();
  });

  it('puts an alias with its target, drops one without, and keeps the first entry of a unit', () => {
    const list = serviceRows([
      { unit: 'b.service', active_state: 'active' },
      { unit: 'x.service', enabled_state: 'alias', alias_of: 'b.service' },
      { unit: 'y.service', enabled_state: 'alias', alias_of: 'b.service' },
      { unit: 'z.service', enabled_state: 'alias' },
      { unit: 'w.service', enabled_state: 'alias', alias_of: 'gone.service' },
      { unit: 'b.service', active_state: 'failed' },
    ]);
    expect(list.map((r) => [r.unit, r.aliases, r.state])).toEqual([
      ['b.service', ['x.service', 'y.service'], 'active'],
    ]);
  });

  it('takes unit names that are Object members as plain names', () => {
    const list = serviceRows([
      { unit: 'constructor', active_state: 'active' },
      { unit: '__proto__', active_state: 'failed' },
      { unit: 'toString', enabled_state: 'alias', alias_of: 'hasOwnProperty' },
      { unit: 'hasOwnProperty', active_state: 'inactive' },
    ]);
    expect(list.map((r) => [r.unit, r.aliases, r.state])).toEqual([
      ['constructor', [], 'active'],
      ['__proto__', [], 'failed'],
      ['hasOwnProperty', ['toString'], 'inactive'],
    ]);
  });

  it('reads counts and times only when they are what the agent sends', () => {
    const [r] = serviceRows([{ unit: 'a', restarts: '2x', memory_bytes: '-1', since: 'gestern' }]);
    expect([r.restarts, r.memoryBytes, r.sinceMs]).toEqual([null, null, null]);
    const [s] = serviceRows([
      { unit: 'a', restarts: '2', memory_bytes: '1024', since: '2026-11-12T10:00:00Z' },
    ]);
    expect([s.restarts, s.memoryBytes, s.sinceMs]).toEqual([
      2,
      1024,
      Date.parse('2026-11-12T10:00:00Z'),
    ]);
  });

  it('filters by state group', () => {
    const list = serviceRows(services());
    expect(filterRows(list, 'all')).toHaveLength(4);
    expect(filterRows(list, 'failed').map((r) => r.unit)).toEqual(['nginx.service']);
    expect(filterRows(list, 'active').map((r) => r.unit)).toEqual(['ssh.service']);
    expect(filterRows(list, 'inactive').map((r) => r.unit)).toEqual(['backup.service', 'Spooler']);
  });
});

describe('ServiceList', () => {
  it('lists every service by name with its columns and "—" for what is not sent', async () => {
    const container = await shown();
    expect(h.fetch).toHaveBeenCalledWith({ serverUrl: 'https://hub.example' }, 'srv-1');
    expect(container.textContent).toContain('Stand: vor 10 min');
    expect(rows(container)).toEqual([
      ['backup.service', 'inactive · dead', 'vor 30 min', '0', '1 MiB', '—'],
      ['nginx.service', 'failed · failed', 'vor 5 min', '3', '0 B', 'exit-code, status=1'],
      ['Spooler', 'inactive', '—', '—', '—', 'win32=1067'],
      ['ssh.service auch: sshd.service', 'active · running', 'vor 2 h', '0', '4 MiB', '—'],
    ]);
    expect(container.querySelector('[data-state="failed"] .pill-crit')).not.toBeNull();
  });

  it('filters by state and counts each group', async () => {
    const container = await shown();
    expect(
      Array.from(container.querySelectorAll('[role="radio"]')).map((b) => b.textContent?.trim()),
    ).toEqual(['Alle (4)', 'Fehlgeschlagen (1)', 'Inaktiv (2)', 'Aktiv (1)']);

    await fireEvent.click(radio(container, 'Fehlgeschlagen (1)'));
    expect(names(container)).toEqual(['nginx.service']);
    await fireEvent.click(radio(container, 'Inaktiv (2)'));
    expect(names(container)).toEqual(['backup.service', 'Spooler']);
    await fireEvent.click(radio(container, 'Alle (4)'));
    expect(names(container)).toHaveLength(4);
  });

  it('says so when no service is in the chosen state', async () => {
    const container = await shown({
      services: [{ unit: 'ssh.service', active_state: 'active' }],
    });
    await fireEvent.click(radio(container, 'Fehlgeschlagen (0)'));
    expect(container.querySelector('table')).toBeNull();
    expect(container.textContent).toContain('Kein Dienst in diesem Zustand');
  });

  it('finds a service by its alias name', async () => {
    const container = await shown();
    const input = container.querySelector('input[type="search"]') as HTMLInputElement;
    await fireEvent.input(input, { target: { value: 'sshd' } });
    expect(names(container)).toEqual(['ssh.service']);
    await fireEvent.input(input, { target: { value: 'NGINX' } });
    expect(names(container)).toEqual(['nginx.service']);
  });

  it('sorts by since, restarts and RAM with missing values last', async () => {
    const container = await shown();
    await fireEvent.click(sortButton(container, 'RAM'));
    expect(names(container)).toEqual(['nginx.service', 'backup.service', 'ssh.service', 'Spooler']);
    await fireEvent.click(sortButton(container, 'RAM'));
    expect(names(container)).toEqual(['ssh.service', 'backup.service', 'nginx.service', 'Spooler']);

    await fireEvent.click(sortButton(container, 'Neustarts'));
    expect(names(container).slice(-2)).toEqual(['nginx.service', 'Spooler']);

    // Oldest change first.
    await fireEvent.click(sortButton(container, 'Seit'));
    expect(names(container)).toEqual(['ssh.service', 'backup.service', 'nginx.service', 'Spooler']);
  });

  it('says so while the agent has sent no list yet', async () => {
    h.fetch.mockResolvedValue(inventory({ reportedAt: null, services: [] }));
    const { container } = render(ServiceList, { serverId: 'srv-1' });
    await waitFor(
      () =>
        expect(container.textContent).toContain('Der Agent hat noch keine Dienste-Liste gemeldet.'),
      WAIT,
    );
    expect(container.querySelector('table')).toBeNull();
  });

  it('counts an inventory of aliases alone as empty', async () => {
    h.fetch.mockResolvedValue(
      inventory({ services: [{ unit: 'a.service', enabled_state: 'alias', alias_of: 'b' }] }),
    );
    const { container } = render(ServiceList, { serverId: 'srv-1' });
    await waitFor(
      () =>
        expect(container.textContent).toContain('Der Agent hat noch keine Dienste-Liste gemeldet.'),
      WAIT,
    );
  });

  it('names a server the monitoring service knows no agent of', async () => {
    h.fetch.mockRejectedValue(new IpcError('Server not found', 'ERR_HTTP', 404));
    const { container } = render(ServiceList, { serverId: 'srv-1' });
    await waitFor(
      () =>
        expect(container.textContent).toContain('Für diesen Server liegen keine Agent-Daten vor.'),
      WAIT,
    );
    expect(container.textContent).not.toContain('Server not found');
  });

  it('shows any other error with its message', async () => {
    h.fetch.mockRejectedValue(new IpcError('HTTP 502', 'ERR_HTTP', 502));
    const { container } = render(ServiceList, { serverId: 'srv-1' });
    await waitFor(
      () => expect(container.textContent).toContain('Dienste-Liste nicht geladen: HTTP 502'),
      WAIT,
    );
  });

  it('shows a loading line until the answer is in', async () => {
    h.fetch.mockImplementation(() => new Promise(() => {}));
    const { container } = render(ServiceList, { serverId: 'srv-1' });
    await tick();
    expect(container.textContent).toContain('Lade…');
    expect(container.querySelector('table')).toBeNull();
  });

  it('drops a late answer for the server shown before', async () => {
    const answers: Record<string, (inv: MonitorServiceInventory) => void> = {};
    h.fetch.mockImplementation(
      (_auth: unknown, id: string) => new Promise((resolve) => (answers[id] = resolve)),
    );
    const { container, rerender } = render(ServiceList, { serverId: 'srv-1' });
    await tick();
    await rerender({ serverId: 'srv-2' });
    answers['srv-2'](
      inventory({ services: [{ unit: 'zfs.service', active_state: 'active' }] }, 'srv-2'),
    );
    await waitFor(() => expect(names(container)).toEqual(['zfs.service']), WAIT);
    answers['srv-1'](inventory());
    await tick();
    await tick();
    expect(names(container)).toEqual(['zfs.service']);
  });

  it('drops a late error for the server shown before', async () => {
    const refuse: Record<string, (err: unknown) => void> = {};
    h.fetch.mockImplementation((_auth: unknown, id: string) =>
      id === 'srv-1'
        ? new Promise((_resolve, reject) => (refuse[id] = reject))
        : Promise.resolve(
            inventory({ services: [{ unit: 'zfs.service', active_state: 'active' }] }, 'srv-2'),
          ),
    );
    const { container, rerender } = render(ServiceList, { serverId: 'srv-1' });
    await tick();
    await rerender({ serverId: 'srv-2' });
    await waitFor(() => expect(names(container)).toEqual(['zfs.service']), WAIT);
    refuse['srv-1'](new IpcError('HTTP 502', 'ERR_HTTP', 502));
    await tick();
    await tick();
    expect(names(container)).toEqual(['zfs.service']);
    expect(container.textContent).not.toContain('HTTP 502');
  });
});
