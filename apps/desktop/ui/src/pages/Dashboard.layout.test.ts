// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Dashboard layout: cards and panels per mode, the connect and monitoring ways (R-1062).

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { writable } from 'svelte/store';
import type { Connection } from '$lib/bridge/types';
import type { MonitorCheck, Server } from '$lib/api/types';

const h = vi.hoisted(() => ({
  initiateConnect: vi.fn(async () => {}),
  openEditor: vi.fn(),
  navigate: vi.fn(),
  loadServers: vi.fn(async () => {}),
  loadMonitoring: vi.fn(async () => {}),
  setSelectedServer: vi.fn(),
  setOverviewView: vi.fn(),
}));

vi.mock('$lib/stores/connections', async () => {
  const { writable: w } = await import('svelte/store');
  return {
    loadForCurrentMode: vi.fn(async () => {}),
    kindCounts: w({ total: 0, ssh: 0, rdp: 0, web: 0 }),
    recentConnections: w([]),
    loading: w(false),
  };
});
vi.mock('$lib/stores/session', async () => {
  const { writable: w } = await import('svelte/store');
  return { sessionStore: w({ settings: null, session: null }) };
});
vi.mock('$lib/stores/monitoring', async () => {
  const { writable: w } = await import('svelte/store');
  return {
    loadServers: h.loadServers,
    loadMonitoring: h.loadMonitoring,
    setSelectedServer: h.setSelectedServer,
    setOverviewView: h.setOverviewView,
    monitoringChecks: w([]),
    monitoringServers: w([]),
    monitoringHasLoaded: w(false),
    monitoringError: w<string | null>(null),
  };
});
vi.mock('$lib/stores/tunnel', async () => {
  const { writable: w } = await import('svelte/store');
  return { tunnel: w({ ui: 'connected' }), tunnelMappings: w([]) };
});
vi.mock('$lib/stores/connectFlow', () => ({ initiateConnect: h.initiateConnect }));
vi.mock('$lib/stores/editor', () => ({ openEditor: h.openEditor }));
vi.mock('$lib/router', () => ({ navigate: h.navigate }));
vi.mock('../components/ConnectionsLoadError.svelte', () => ({ default: vi.fn() }));
vi.mock('../components/monitoring/MonHeartbeatBar.svelte', () => ({ default: vi.fn() }));

import * as connMod from '$lib/stores/connections';
import * as sessionMod from '$lib/stores/session';
import * as monMod from '$lib/stores/monitoring';
import * as tunnelMod from '$lib/stores/tunnel';
import { setLanguage, tNow } from '$lib/i18n';
import Dashboard from './Dashboard.svelte';

type W<T> = ReturnType<typeof writable<T>>;
const counts = connMod.kindCounts as unknown as W<Record<string, number>>;
const recent = connMod.recentConnections as unknown as W<Partial<Connection>[]>;
const session = sessionMod.sessionStore as unknown as W<unknown>;
const checks = monMod.monitoringChecks as unknown as W<Partial<MonitorCheck>[]>;
const servers = monMod.monitoringServers as unknown as W<Partial<Server>[]>;
const hasLoaded = monMod.monitoringHasLoaded as unknown as W<boolean>;
const monError = monMod.monitoringError as unknown as W<string | null>;
const mappings = tunnelMod.tunnelMappings as unknown as W<unknown[]>;

const SERVER = {
  settings: { mode: 'server' },
  session: { serverUrl: 'https://hub.example', username: 'kevin', isAdmin: false },
};

function cards(c: HTMLElement): string[] {
  return [...c.querySelectorAll<HTMLElement>('[data-card]')].map((el) => el.dataset.card ?? '');
}
function panels(c: HTMLElement): string[] {
  return [...c.querySelectorAll<HTMLElement>('[data-panel]')].map((el) => el.dataset.panel ?? '');
}
function value(c: HTMLElement, card: string): string {
  return c.querySelector(`[data-card="${card}"] .dash-card-value`)?.textContent?.trim() ?? '';
}

beforeAll(() => setLanguage('en'));

beforeEach(() => {
  vi.clearAllMocks();
  counts.set({ total: 3, ssh: 2, rdp: 0, web: 1 });
  recent.set([
    { id: 'c1', name: 'Backup NAS', kind: 'ssh', host: 'nas.example', lastUsed: null },
    { id: 'c2', name: '', kind: 'web', url: 'https://wiki.example', lastUsed: null },
  ]);
  session.set({ settings: { mode: 'local' }, session: null });
  checks.set([]);
  servers.set([]);
  hasLoaded.set(false);
  monError.set(null);
  mappings.set([]);
});

afterEach(() => cleanup());

describe('Dashboard layout', () => {
  it('local mode shows the connections card and the recent panel only', () => {
    const { container } = render(Dashboard);
    expect(cards(container)).toEqual(['connections']);
    expect(panels(container)).toEqual(['recent']);
    expect(value(container, 'connections')).toBe('3');
    expect(container.textContent).toContain(tNow('dashboard.kindHint', { ssh: 2, rdp: 0, web: 1 }));
    expect(h.loadServers).not.toHaveBeenCalled();
  });

  it('a recent row connects through the connect flow and names its target', async () => {
    const { container } = render(Dashboard);
    const rows = container.querySelectorAll<HTMLElement>('[data-panel="recent"] li');
    expect(rows).toHaveLength(2);
    expect(rows[1].textContent).toContain('https://wiki.example');
    await fireEvent.click(within(rows[0]).getByRole('button', { name: tNow('action.connect') }));
    expect(h.initiateConnect).toHaveBeenCalledWith(expect.objectContaining({ id: 'c1' }));
  });

  it('the buttons open the editor and the list', async () => {
    const { getByRole } = render(Dashboard);
    await fireEvent.click(getByRole('button', { name: tNow('connections.new') }));
    expect(h.openEditor).toHaveBeenCalledWith(null);
    await fireEvent.click(getByRole('button', { name: tNow('dashboard.toList') }));
    expect(h.navigate).toHaveBeenCalledWith('/connections');
  });

  it('server mode adds servers, problems, monitoring and tunnel', async () => {
    session.set(SERVER);
    servers.set([
      { id: 's1', name: 'web-01', hostname: 'web-01' },
      { id: 's2', name: 'db-01', hostname: 'db-01' },
    ]);
    const { container } = render(Dashboard);
    expect(cards(container)).toEqual(['connections', 'servers', 'problems']);
    expect(panels(container)).toEqual(['recent', 'monitoring', 'tunnel']);
    expect(h.loadServers).toHaveBeenCalledOnce();
    // Before the first monitoring answer there is no number to show.
    expect(value(container, 'problems')).toBe('-');
    expect(value(container, 'servers')).toBe('2');
    expect(container.textContent).toContain(tNow('dashboard.noTunnels'));

    checks.set([
      {
        id: 'p1',
        serverId: 's1',
        checkType: 'agent_ping',
        enabled: true,
        state: { status: 'critical' },
      },
      { id: 'p2', serverId: 's2', checkType: 'agent_ping', enabled: true, state: { status: 'ok' } },
      {
        id: 'x1',
        serverId: 's2',
        checkType: 'ping',
        enabled: false,
        state: { status: 'critical' },
      },
      { id: 'x2', serverId: 's2', checkType: 'tcp', enabled: true, state: { status: 'ok' } },
    ] as Partial<MonitorCheck>[]);
    hasLoaded.set(true);
    mappings.set([
      {
        id: 'm1',
        name: 'ssh web-01',
        tunnelType: 'stcp',
        localPort: 22,
        visitorPort: 6022,
        enabled: true,
      },
      {
        id: 'm2',
        name: 'off',
        tunnelType: 'stcp',
        localPort: 80,
        visitorPort: 6080,
        enabled: false,
      },
    ]);
    await tick();

    expect(value(container, 'problems')).toBe('1');
    expect(container.textContent).toContain(tNow('dashboard.serversHint', { count: 2 }));
    const mon = container.querySelector<HTMLElement>('[data-panel="monitoring"]')!;
    expect(mon.textContent).toContain(tNow('dashboard.pillCrit', { count: 1 }));
    expect(mon.textContent).toContain(tNow('dashboard.pillOk', { count: 2 }));
    const problemRows = mon.querySelectorAll<HTMLElement>('li[data-server]');
    expect([...problemRows].map((r) => r.dataset.server)).toEqual(['s1']);
    await fireEvent.click(
      within(problemRows[0]).getByRole('button', { name: tNow('dashboard.open') }),
    );
    expect(h.setSelectedServer).toHaveBeenCalledWith('s1');
    expect(h.setOverviewView).toHaveBeenCalledWith('list');
    expect(h.navigate).toHaveBeenCalledWith('/monitoring');

    const tun = container.querySelector<HTMLElement>('[data-panel="tunnel"]')!;
    expect(tun.querySelectorAll('li')).toHaveLength(1);
    expect(tun.textContent).toContain('127.0.0.1:6022 → :22');
  });

  it('a failed monitoring load shows the error, not a healthy monitoring', async () => {
    session.set(SERVER);
    // What loadMonitoring leaves after a failure: loaded, no checks, the error.
    hasLoaded.set(true);
    monError.set('connection refused');
    const { container } = render(Dashboard);
    await tick();

    expect(value(container, 'problems')).toBe('-');
    const mon = container.querySelector<HTMLElement>('[data-panel="monitoring"]')!;
    expect(mon.querySelector('[role="alert"]')?.textContent?.trim()).toBe(
      tNow('error.monitoring', { message: 'connection refused' }),
    );
    expect(mon.textContent).not.toContain(tNow('dashboard.noProblems'));
    expect(mon.textContent).not.toContain(tNow('dashboard.pillOk', { count: 0 }));
  });
});
