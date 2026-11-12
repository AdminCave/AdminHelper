// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-ui-3 T7 (R-1226): the full service list of a server in the Desktop.
// Pins the state groups, the reason, aliases with their target, one row per unit, the
// filter with its counts, the search over alias names, the sort with missing values last,
// "—" for fields a platform does not send, and the empty, no-agent, error and late states.
// T8: the error lines of a failed service fold out as text, never as HTML, and the switch
// per server saves, goes back when saving fails and drops a late answer.
// T10: "Mehr Log" opens the journal of a systemd unit over an SSH connection of the server.

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { Writable } from 'svelte/store';
import type { MonitorServiceEntry, MonitorServiceInventory } from '$lib/api/types';
import type { Connection } from '$lib/bridge/types';
import { IpcError } from '$lib/utils/errors';

const SESSION = { serverUrl: 'https://hub.example' };
const h = vi.hoisted(() => ({
  fetch: vi.fn(),
  save: vi.fn(),
  session: null as { serverUrl: string } | null,
  connectServiceLog: vi.fn(async (..._a: unknown[]) => {}),
}));
// A wait gets a bound of 30 s (testing.md, Fristen); testing-library's default is 1 s.
const WAIT = { timeout: 30_000 };

vi.mock('$lib/api/monitoring', () => ({
  monitoringApi: { fetchServerServices: h.fetch, setServiceLogLines: h.save },
}));
vi.mock('$lib/stores/session', () => ({ currentSession: () => h.session }));
vi.mock('$lib/stores/connectFlow', () => ({ connectServiceLog: h.connectServiceLog }));
vi.mock('$lib/stores/connections', async () => {
  const { writable } = await import('svelte/store');
  return { connections: writable([]) };
});

import { setLanguage } from '$lib/i18n';
import * as connectionStore from '$lib/stores/connections';
import ServiceList, { filterRows, reasonOf, serviceRows, stateOf } from './ServiceList.svelte';

const connectionList = connectionStore.connections as unknown as Writable<Connection[]>;

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
  h.save.mockReset();
  h.connectServiceLog.mockClear();
  h.session = SESSION;
  connectionList.set([]);
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

  it("gives error lines to a failed unit only, and only from the unit's own key", () => {
    const log = { since: ago(5), collectedAt: ago(4), lines: ['boom'] };
    const list = serviceRows(
      [
        { unit: 'a.service', active_state: 'failed' },
        { unit: 'b.service', active_state: 'active' },
        { unit: 'c.service', active_state: 'failed' },
        { unit: 'constructor', active_state: 'failed' },
        { unit: 'toString', active_state: 'failed' },
      ],
      { 'a.service': log, 'b.service': log, 'c.service': { ...log, lines: [] } },
    );
    expect(list.map((r) => [r.unit, r.log])).toEqual([
      ['a.service', log],
      ['b.service', null],
      ['c.service', null],
      ['constructor', null],
      ['toString', null],
    ]);
    expect(serviceRows([{ unit: 'a.service', active_state: 'failed' }])[0].log).toBeNull();
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

describe('error lines and their switch', () => {
  const NGINX_LOG = {
    since: ago(5),
    collectedAt: ago(4),
    lines: ['nginx: [emerg] bind() failed', 'password=***'],
  };

  function logButton(container: HTMLElement): HTMLButtonElement | null {
    return container.querySelector<HTMLButtonElement>('button[aria-expanded]');
  }

  function switchOf(container: HTMLElement): HTMLButtonElement {
    const sw = container.querySelector<HTMLButtonElement>('[role="switch"]');
    if (!sw) throw new Error('no switch');
    return sw;
  }

  function zfs(): MonitorServiceInventory {
    return inventory({ services: [{ unit: 'zfs.service', active_state: 'active' }] }, 'srv-2');
  }

  it('folds the error lines of a failed service out and in', async () => {
    const container = await shown({ logs: { 'nginx.service': NGINX_LOG } });
    expect(container.querySelectorAll('button[aria-expanded]')).toHaveLength(1);
    expect(logButton(container)?.textContent?.trim()).toBe('Fehlerzeilen (2)');
    expect(logButton(container)?.getAttribute('aria-expanded')).toBe('false');
    expect(container.querySelector('.svc-log-lines')).toBeNull();

    await fireEvent.click(logButton(container) as HTMLElement);
    expect(logButton(container)?.getAttribute('aria-expanded')).toBe('true');
    expect(container.querySelector('.svc-log-lines')?.textContent).toBe(
      'nginx: [emerg] bind() failed\npassword=***',
    );
    expect(container.textContent).toContain(
      'Geschwärzt, nur am Vorfall gespeichert · erfasst vor 4 min',
    );

    await fireEvent.click(logButton(container) as HTMLElement);
    expect(container.querySelector('.svc-log-lines')).toBeNull();
    // Folding is no reason to load again.
    expect(h.fetch).toHaveBeenCalledTimes(1);
  });

  it('renders the lines as text, never as HTML', async () => {
    const line = '<b>x</b><img src=x onerror="alert(1)">';
    const container = await shown({ logs: { 'nginx.service': { ...NGINX_LOG, lines: [line] } } });
    await fireEvent.click(logButton(container) as HTMLElement);
    const pre = container.querySelector('.svc-log-lines') as HTMLElement;
    expect(pre.textContent).toBe(line);
    expect(pre.querySelector('b, img')).toBeNull();
  });

  it('folds the lines in when another server is shown', async () => {
    h.fetch.mockImplementation((_auth: unknown, id: string) =>
      Promise.resolve(inventory({ logs: { 'nginx.service': NGINX_LOG } }, id)),
    );
    const { container, rerender } = render(ServiceList, { serverId: 'srv-1' });
    await waitFor(() => expect(logButton(container)).not.toBeNull(), WAIT);
    await fireEvent.click(logButton(container) as HTMLElement);
    expect(container.querySelector('.svc-log-lines')).not.toBeNull();

    await rerender({ serverId: 'srv-2' });
    await waitFor(() => expect(h.fetch).toHaveBeenCalledWith(SESSION, 'srv-2'), WAIT);
    await waitFor(() => expect(logButton(container)).not.toBeNull(), WAIT);
    expect(logButton(container)?.getAttribute('aria-expanded')).toBe('false');
    expect(container.querySelector('.svc-log-lines')).toBeNull();
  });

  it('switches the lines off, which drops the stored ones and names what off does', async () => {
    h.save.mockResolvedValue(inventory({ logLines: false, logs: {} }));
    const container = await shown({ logs: { 'nginx.service': NGINX_LOG } });
    expect(switchOf(container).getAttribute('aria-checked')).toBe('true');
    expect(container.textContent).toContain(
      'Aus blendet gespeicherte Zeilen sofort aus und löscht sie; der Agent folgt mit seinem nächsten Plan.',
    );

    await fireEvent.click(switchOf(container));
    expect(h.save).toHaveBeenCalledWith(SESSION, 'srv-1', false);
    await waitFor(() => expect(logButton(container)).toBeNull(), WAIT);
    expect(switchOf(container).getAttribute('aria-checked')).toBe('false');
    expect(switchOf(container).disabled).toBe(false);
  });

  it('switches the lines on and shows the switch as the service saved it', async () => {
    h.save.mockResolvedValueOnce(
      inventory({ logLines: true, logs: { 'nginx.service': NGINX_LOG } }),
    );
    const container = await shown({ logLines: false });
    expect(switchOf(container).getAttribute('aria-checked')).toBe('false');
    await fireEvent.click(switchOf(container));
    expect(h.save).toHaveBeenCalledWith(SESSION, 'srv-1', true);
    await waitFor(() => expect(logButton(container)).not.toBeNull(), WAIT);
    expect(switchOf(container).getAttribute('aria-checked')).toBe('true');

    // The service has the last word, e.g. when another admin switched it meanwhile.
    h.save.mockResolvedValueOnce(inventory({ logLines: true, logs: {} }));
    await fireEvent.click(switchOf(container));
    await waitFor(() => expect(logButton(container)).toBeNull(), WAIT);
    expect(switchOf(container).getAttribute('aria-checked')).toBe('true');
  });

  it('holds the switch while saving', async () => {
    h.save.mockImplementation(() => new Promise(() => {}));
    const container = await shown();
    await fireEvent.click(switchOf(container));
    expect(switchOf(container).disabled).toBe(true);
  });

  it('puts the switch back and says so when saving fails', async () => {
    h.save.mockRejectedValueOnce(new IpcError('HTTP 502', 'ERR_HTTP', 502));
    const container = await shown({ logs: { 'nginx.service': NGINX_LOG } });
    await fireEvent.click(switchOf(container));
    await waitFor(
      () =>
        expect(container.querySelector('[role="alert"]')?.textContent?.trim()).toBe(
          'Schalter nicht gespeichert: HTTP 502',
        ),
      WAIT,
    );
    expect(switchOf(container).getAttribute('aria-checked')).toBe('true');
    expect(switchOf(container).disabled).toBe(false);
    expect(logButton(container)).not.toBeNull();

    h.save.mockResolvedValueOnce(inventory({ logLines: false, logs: {} }));
    await fireEvent.click(switchOf(container));
    await waitFor(() => expect(container.querySelector('[role="alert"]')).toBeNull(), WAIT);
    expect(switchOf(container).getAttribute('aria-checked')).toBe('false');
  });

  it("does not carry a save error over to the next server's switch", async () => {
    h.save.mockRejectedValueOnce(new IpcError('HTTP 502', 'ERR_HTTP', 502));
    h.fetch.mockImplementation((_auth: unknown, id: string) =>
      Promise.resolve(id === 'srv-1' ? inventory() : zfs()),
    );
    const { container, rerender } = render(ServiceList, { serverId: 'srv-1' });
    await waitFor(() => expect(container.querySelector('table')).not.toBeNull(), WAIT);
    await fireEvent.click(switchOf(container));
    await waitFor(() => expect(container.querySelector('[role="alert"]')).not.toBeNull(), WAIT);

    await rerender({ serverId: 'srv-2' });
    await waitFor(() => expect(names(container)).toEqual(['zfs.service']), WAIT);
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('sends nothing without a session and leaves the switch as it was', async () => {
    const container = await shown();
    h.session = null;
    await fireEvent.click(switchOf(container));
    expect(h.save).not.toHaveBeenCalled();
    expect(switchOf(container).getAttribute('aria-checked')).toBe('true');
  });

  it('offers the switch before the agent has sent a list', async () => {
    h.fetch.mockResolvedValue(inventory({ reportedAt: null, services: [], logLines: false }));
    const { container } = render(ServiceList, { serverId: 'srv-1' });
    await waitFor(
      () =>
        expect(container.textContent).toContain('Der Agent hat noch keine Dienste-Liste gemeldet.'),
      WAIT,
    );
    expect(switchOf(container).getAttribute('aria-checked')).toBe('false');
  });

  it('drops a late save answer for the server shown before', async () => {
    let answer: (inv: MonitorServiceInventory) => void = () => {};
    h.save.mockImplementation(() => new Promise((resolve) => (answer = resolve)));
    h.fetch.mockImplementation((_auth: unknown, id: string) =>
      Promise.resolve(id === 'srv-1' ? inventory() : zfs()),
    );
    const { container, rerender } = render(ServiceList, { serverId: 'srv-1' });
    await waitFor(() => expect(container.querySelector('table')).not.toBeNull(), WAIT);
    await fireEvent.click(switchOf(container));
    await rerender({ serverId: 'srv-2' });
    await waitFor(() => expect(names(container)).toEqual(['zfs.service']), WAIT);
    expect(switchOf(container).disabled).toBe(false);

    answer(inventory({ logLines: false }));
    await tick();
    await tick();
    expect(names(container)).toEqual(['zfs.service']);
    expect(switchOf(container).getAttribute('aria-checked')).toBe('true');
    expect(switchOf(container).disabled).toBe(false);
  });

  it('drops a late save error for the server shown before', async () => {
    let refuse: (err: unknown) => void = () => {};
    h.save.mockImplementation(() => new Promise((_resolve, reject) => (refuse = reject)));
    h.fetch.mockImplementation((_auth: unknown, id: string) =>
      Promise.resolve(id === 'srv-1' ? inventory() : zfs()),
    );
    const { container, rerender } = render(ServiceList, { serverId: 'srv-1' });
    await waitFor(() => expect(container.querySelector('table')).not.toBeNull(), WAIT);
    await fireEvent.click(switchOf(container));
    await rerender({ serverId: 'srv-2' });
    await waitFor(() => expect(names(container)).toEqual(['zfs.service']), WAIT);

    refuse(new IpcError('HTTP 502', 'ERR_HTTP', 502));
    await tick();
    await tick();
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(switchOf(container).getAttribute('aria-checked')).toBe('true');
  });
});

describe('"Mehr Log" of a service', () => {
  function ssh(id: string, serverId: string, kind = 'ssh'): Connection {
    return { id, name: `${id}-name`, kind, host: `${id}.example`, serverId } as Connection;
  }

  function journalButtons(container: HTMLElement): string[] {
    return Array.from(container.querySelectorAll<HTMLElement>('tbody button'))
      .map((b) => b.getAttribute('aria-label') ?? '')
      .filter((l) => l.startsWith('Mehr Log'));
  }

  it('opens the journal of a systemd unit over the SSH connection of this server', async () => {
    connectionList.set([ssh('other', 'srv-2'), ssh('rdp', 'srv-1', 'rdp'), ssh('web', 'srv-1')]);
    const onJournal = vi.fn();
    h.fetch.mockResolvedValue(inventory());
    const { container } = render(ServiceList, { serverId: 'srv-1', onJournal });
    await waitFor(() => expect(container.querySelector('table')).not.toBeNull(), WAIT);

    // Every systemd service, alias targets included; a Windows name carries no journal.
    expect(journalButtons(container).sort()).toEqual([
      'Mehr Log von backup.service im Terminal öffnen',
      'Mehr Log von nginx.service im Terminal öffnen',
      'Mehr Log von ssh.service im Terminal öffnen',
    ]);
    expect(container.querySelector('select')).toBeNull();
    expect(container.textContent).toContain('nur die letzten 200 Journal-Zeilen');

    const nginx = container.querySelector<HTMLElement>(
      'button[aria-label="Mehr Log von nginx.service im Terminal öffnen"]',
    ) as HTMLElement;
    await fireEvent.click(nginx);
    expect(h.connectServiceLog).toHaveBeenCalledExactlyOnceWith(
      ssh('web', 'srv-1'),
      'nginx.service',
    );
    expect(onJournal).toHaveBeenCalledOnce();
  });

  it('takes the SSH connection the admin picks when the server has several', async () => {
    connectionList.set([ssh('a', 'srv-1'), ssh('b', 'srv-1')]);
    const container = await shown();
    const select = container.querySelector('select') as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual(['a-name', 'b-name']);
    expect(select.value).toBe('a');

    await fireEvent.change(select, { target: { value: 'b' } });
    await fireEvent.click(
      container.querySelector(
        'button[aria-label="Mehr Log von ssh.service im Terminal öffnen"]',
      ) as HTMLElement,
    );
    expect(h.connectServiceLog).toHaveBeenCalledExactlyOnceWith(ssh('b', 'srv-1'), 'ssh.service');
  });

  it('offers no journal without an SSH connection of this server and says why', async () => {
    connectionList.set([ssh('other', 'srv-2'), ssh('rdp', 'srv-1', 'rdp')]);
    const container = await shown();
    expect(journalButtons(container)).toEqual([]);
    expect(container.textContent).toContain(
      'Für „Mehr Log“ braucht der Server eine SSH-Verbindung.',
    );
    expect(h.connectServiceLog).not.toHaveBeenCalled();
  });

  it('offers no journal on a server without systemd services and says why', async () => {
    connectionList.set([ssh('web', 'srv-1')]);
    // Windows and FreeBSD report service names without the systemd suffix.
    const container = await shown({
      services: [
        { unit: 'Spooler', active_state: 'failed', exit: 'win32=1067' },
        { unit: 'sshd', active_state: 'active' },
      ],
    });
    expect(names(container).sort()).toEqual(['Spooler', 'sshd']);
    expect(journalButtons(container)).toEqual([]);
    expect(container.textContent).toContain(
      '„Mehr Log“ gibt es nur für systemd-Dienste unter Linux.',
    );
    expect(container.textContent).not.toContain('nur die letzten 200 Journal-Zeilen');
  });
});
