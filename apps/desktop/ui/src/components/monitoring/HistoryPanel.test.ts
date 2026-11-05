// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import type { MonitorCheck, ServerHistory } from '$lib/api/types';

const mocks = vi.hoisted(() => ({
  fetchServerHistory: vi.fn(),
  fetchMetrics: vi.fn(),
  save: vi.fn(),
  writeExportCsv: vi.fn(),
}));

vi.mock('$lib/api/monitoring', () => ({
  monitoringApi: {
    fetchServerHistory: mocks.fetchServerHistory,
    fetchMetrics: mocks.fetchMetrics,
  },
}));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { sessionStore: writable({ session: { token: 's' }, settings: {} }) };
});
vi.mock('$lib/bridge', () => ({ writeExportCsv: mocks.writeExportCsv }));
vi.mock('@tauri-apps/plugin-dialog', () => ({ save: mocks.save }));

import { setLanguage } from '$lib/i18n';
import HistoryPanel from './HistoryPanel.svelte';

const START = 1_700_000_100;
const STEP = 900;
const grid = (vals: (number | null)[]): [number, number | null][] =>
  vals.map((v, i) => [START + i * STEP, v]);

function history(over: Partial<ServerHistory> = {}): ServerHistory {
  return {
    serverId: 'srv1',
    period: '24h',
    step: STEP,
    start: START,
    end: START + 4 * STEP,
    series: {
      cpu: grid([10, 20, 30, 40, 50]),
      ram: grid([60, 60, 60, 60, 60]),
      swap: grid([null, null, null, null, null]),
      loadPerCpu: grid([0.5, 0.5, 0.5, 0.5, 0.5]),
      netIn: grid([null, null, null, null, null]),
      netOut: grid([null, null, null, null, null]),
      disks: { '/': grid([50, 55, 60, 65, 70]), '/data': grid([30, 30, 30, 30, 30]) },
    },
    previous: {
      cpu: grid([5, 5, 5, 5, 5]),
      ram: grid([50, 50, 50, 50, 50]),
      swap: grid([null, null, null, null, null]),
      loadPerCpu: grid([0.2, 0.2, 0.2, 0.2, 0.2]),
      netIn: grid([null, null, null, null, null]),
      netOut: grid([null, null, null, null, null]),
      disks: {},
    },
    thresholds: { cpu: { warn: 80, crit: 95 }, disk: { warn: 85, crit: 95 } },
    events: [{ at: START + STEP, checkId: 'c1', checkName: 'Ping', status: 'critical' }],
    maintenance: [],
    ...over,
  };
}

const ping = { id: 'p1', name: 'Ping gw', checkType: 'ping' } as MonitorCheck;

function withNet(): ServerHistory {
  const h = history();
  return {
    ...h,
    series: { ...h.series, netIn: grid([1, 2, 3, 4, 5]), netOut: grid([0.5, 0.5, 0.5, 0.5, 0.5]) },
  };
}

/** The y coordinates of one drawn line. */
function ys(container: HTMLElement, key: string): number[] {
  const d = container.querySelector(`[data-testid="chart-line"][data-series="${key}"]`);
  return [...(d?.getAttribute('d') ?? '').matchAll(/[ML][\d.]+ ([\d.]+)/g)].map((m) =>
    Number(m[1]),
  );
}

function lines(container: HTMLElement): string[] {
  return [...container.querySelectorAll('[data-testid="chart-line"]')].map(
    (l) => l.getAttribute('data-series') ?? '',
  );
}

beforeEach(() => setLanguage('en'));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('HistoryPanel', () => {
  it('loads the 24h history with the previous period and draws CPU and RAM', async () => {
    mocks.fetchServerHistory.mockResolvedValue(history());
    const { container } = render(HistoryPanel, {
      serverId: 'srv1',
      serverName: 'web-1',
      latencyChecks: [],
    });
    await waitFor(() => expect(lines(container)).toEqual(['cpu', 'ram']));
    expect(mocks.fetchServerHistory).toHaveBeenCalledWith({ token: 's' }, 'srv1', '24h');
    expect(container.querySelectorAll('[data-testid="chart-prev"]')).toHaveLength(2);
    expect(screen.getByText('warn 80 %')).toBeTruthy();
    expect(screen.getByText('crit 95 %')).toBeTruthy();
    expect(container.querySelectorAll('[data-testid="chart-event"]')).toHaveLength(1);
    const cpuRow = screen.getByRole('rowheader', { name: 'CPU' }).closest('tr');
    expect([...(cpuRow?.querySelectorAll('td') ?? [])].map((c) => c.textContent)).toEqual([
      '30 %',
      '50 %',
      '50 %',
      '50 %',
    ]);
    expect(screen.queryByRole('tab', { name: 'Latency' })).toBeNull();
  });

  it('reloads on a period switch and drops the previous period on request', async () => {
    mocks.fetchServerHistory.mockResolvedValue(history());
    const { container } = render(HistoryPanel, {
      serverId: 'srv1',
      serverName: 'web-1',
      latencyChecks: [],
    });
    await waitFor(() => expect(lines(container)).toHaveLength(2));
    await fireEvent.click(screen.getByRole('button', { name: '7 days' }));
    await waitFor(() =>
      expect(mocks.fetchServerHistory).toHaveBeenLastCalledWith({ token: 's' }, 'srv1', '7d'),
    );
    await fireEvent.click(screen.getByRole('checkbox', { name: 'Previous period' }));
    expect(container.querySelectorAll('[data-testid="chart-prev"]')).toHaveLength(0);
  });

  it('hides a series from the chart and the table through the legend', async () => {
    mocks.fetchServerHistory.mockResolvedValue(history());
    const { container } = render(HistoryPanel, {
      serverId: 'srv1',
      serverName: 'web-1',
      latencyChecks: [],
    });
    await waitFor(() => expect(lines(container)).toHaveLength(2));
    const ram = screen.getByRole('button', { name: 'RAM', pressed: true });
    await fireEvent.click(ram);
    expect(lines(container)).toEqual(['cpu']);
    expect(screen.queryByRole('rowheader', { name: 'RAM' })).toBeNull();
    expect(ram.getAttribute('aria-pressed')).toBe('false');
  });

  it('forecasts a growing mount and names the days until it is full', async () => {
    mocks.fetchServerHistory.mockResolvedValue(history());
    const { container } = render(HistoryPanel, {
      serverId: 'srv1',
      serverName: 'web-1',
      latencyChecks: [],
    });
    await waitFor(() => expect(lines(container)).toHaveLength(2));
    await fireEvent.click(screen.getByRole('tab', { name: 'Storage' }));
    expect(lines(container)).toEqual(['disk:/', 'disk:/data', 'disk:/:forecast']);
    expect(screen.getByText('/ full in ~1 days')).toBeTruthy();
    expect(screen.queryByText(/\/data full/)).toBeNull();
    expect(screen.getByText('now → forecast')).toBeTruthy();
  });

  it('shows the error instead of empty axes', async () => {
    mocks.fetchServerHistory.mockRejectedValue(new Error('502 Bad Gateway'));
    const { container } = render(HistoryPanel, {
      serverId: 'srv1',
      serverName: 'web-1',
      latencyChecks: [],
    });
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('502 Bad Gateway'));
    expect(container.querySelector('svg')).toBeNull();
  });

  it('draws one latency line per check on the history grid', async () => {
    mocks.fetchServerHistory.mockResolvedValue(history());
    mocks.fetchMetrics.mockResolvedValue({
      data: [
        { metric: { __name__: 'monitor_check_duration_ms_value' }, values: [[START, '99']] },
        {
          metric: { __name__: 'monitor_ping_rtt_ms_value' },
          values: [
            [START + 10, '12.5'],
            [START + 2 * STEP - 30, '14'],
          ],
        },
      ],
    });
    const { container } = render(HistoryPanel, {
      serverId: 'srv1',
      serverName: 'web-1',
      latencyChecks: [ping],
    });
    await waitFor(() => expect(lines(container)).toHaveLength(2));
    await fireEvent.click(screen.getByRole('tab', { name: 'Latency' }));
    await waitFor(() => expect(lines(container)).toEqual(['check:p1']));
    expect(mocks.fetchMetrics).toHaveBeenCalledWith({ token: 's' }, 'p1', '24h');
    const row = screen.getByRole('rowheader', { name: 'Ping gw' }).closest('tr');
    // 12.5 and 14 on grid points 0 and 2; the duration series is not taken.
    expect(row?.querySelectorAll('td')[2].textContent).toBe('14 ms');
  });

  it('exports the tab as CSV to the chosen file', async () => {
    mocks.fetchServerHistory.mockResolvedValue(history());
    mocks.save.mockResolvedValue('/home/u/cpu.csv');
    mocks.writeExportCsv.mockResolvedValue('/home/u/cpu.csv');
    const { container } = render(HistoryPanel, {
      serverId: 'srv1',
      serverName: 'web 1',
      latencyChecks: [],
    });
    await waitFor(() => expect(lines(container)).toHaveLength(2));
    await fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
    await waitFor(() => expect(screen.getByText('Saved: /home/u/cpu.csv')).toBeTruthy());
    expect(mocks.save).toHaveBeenCalledWith(
      expect.objectContaining({ defaultPath: 'adminhelper-web-1-cpu-24h.csv' }),
    );
    const [path, csv] = mocks.writeExportCsv.mock.calls[0] as [string, string];
    expect(path).toBe('/home/u/cpu.csv');
    expect(csv.split('\n')[0]).toBe('time,CPU,RAM');
    expect(csv.split('\n')).toHaveLength(7);
  });

  it("drops the previous server's chart while the next one loads", async () => {
    mocks.fetchServerHistory.mockResolvedValueOnce(history());
    const { container, rerender } = render(HistoryPanel, {
      serverId: 'srv1',
      serverName: 'web-1',
      latencyChecks: [],
    });
    await waitFor(() => expect(lines(container)).toHaveLength(2));
    mocks.fetchServerHistory.mockReturnValueOnce(new Promise(() => {}));
    await rerender({ serverId: 'srv2', serverName: 'web-2', latencyChecks: [] });
    await waitFor(() =>
      expect(mocks.fetchServerHistory).toHaveBeenLastCalledWith({ token: 's' }, 'srv2', '24h'),
    );
    expect(lines(container)).toEqual([]);
    expect(screen.queryByRole('button', { name: 'Export CSV' })).toBeNull();
  });

  it('reports a failing save dialog as an export error', async () => {
    mocks.fetchServerHistory.mockResolvedValue(history());
    mocks.save.mockRejectedValue(new Error('no portal'));
    const { container } = render(HistoryPanel, {
      serverId: 'srv1',
      serverName: 'web-1',
      latencyChecks: [],
    });
    await waitFor(() => expect(lines(container)).toHaveLength(2));
    await fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('no portal'));
    expect(mocks.writeExportCsv).not.toHaveBeenCalled();
  });

  it('writes nothing when the save dialog is cancelled', async () => {
    mocks.fetchServerHistory.mockResolvedValue(history());
    mocks.save.mockResolvedValue(null);
    const { container } = render(HistoryPanel, {
      serverId: 'srv1',
      serverName: 'web-1',
      latencyChecks: [],
    });
    await waitFor(() => expect(lines(container)).toHaveLength(2));
    await fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
    await waitFor(() => expect(mocks.save).toHaveBeenCalled());
    expect(mocks.writeExportCsv).not.toHaveBeenCalled();
  });

  it('offers the network tab only with network data', async () => {
    mocks.fetchServerHistory.mockResolvedValue(history());
    const { container } = render(HistoryPanel, {
      serverId: 'srv1',
      serverName: 'web-1',
      latencyChecks: [],
    });
    await waitFor(() => expect(lines(container)).toHaveLength(2));
    expect(screen.queryByRole('tab', { name: 'Network' })).toBeNull();
  });

  it('draws incoming above and outgoing below zero in Mbit/s, without thresholds or events', async () => {
    mocks.fetchServerHistory.mockResolvedValue(withNet());
    const { container } = render(HistoryPanel, {
      serverId: 'srv1',
      serverName: 'web-1',
      latencyChecks: [],
    });
    await waitFor(() => expect(lines(container)).toHaveLength(2));
    await fireEvent.click(screen.getByRole('tab', { name: 'Network' }));
    await waitFor(() => expect(lines(container)).toEqual(['netIn', 'netOut']));
    // Height 230, padding 16 above and 28 below: the zero line of the mirrored axis is at 109.
    expect(ys(container, 'netIn').every((y) => y < 109)).toBe(true);
    expect(ys(container, 'netOut').every((y) => y > 109)).toBe(true);
    expect(container.querySelectorAll('[data-testid="chart-threshold"]')).toHaveLength(0);
    expect(container.querySelectorAll('[data-testid="chart-event"]')).toHaveLength(0);
    const row = screen.getByRole('rowheader', { name: 'Incoming' }).closest('tr');
    const cells = [...(row?.querySelectorAll('td') ?? [])].map((c) => c.textContent);
    expect(cells[0]).toBe('3.0 Mbit/s');
    expect(cells[3]).toBe('5.0 Mbit/s');
  });

  it('keeps the network tab over a period switch', async () => {
    mocks.fetchServerHistory.mockResolvedValue(withNet());
    const { container } = render(HistoryPanel, {
      serverId: 'srv1',
      serverName: 'web-1',
      latencyChecks: [],
    });
    await waitFor(() => expect(lines(container)).toHaveLength(2));
    await fireEvent.click(screen.getByRole('tab', { name: 'Network' }));
    await waitFor(() => expect(lines(container)).toEqual(['netIn', 'netOut']));
    await fireEvent.click(screen.getByRole('button', { name: '7 days' }));
    await waitFor(() =>
      expect(mocks.fetchServerHistory).toHaveBeenLastCalledWith({ token: 's' }, 'srv1', '7d'),
    );
    await waitFor(() => expect(lines(container)).toEqual(['netIn', 'netOut']));
    expect(screen.getByRole('tab', { name: 'Network' }).getAttribute('aria-selected')).toBe('true');
  });

  it('falls back to CPU when the next server has no network data', async () => {
    mocks.fetchServerHistory.mockResolvedValueOnce(withNet()).mockResolvedValue(history());
    const { container, rerender } = render(HistoryPanel, {
      serverId: 'srv1',
      serverName: 'web-1',
      latencyChecks: [],
    });
    await waitFor(() => expect(lines(container)).toHaveLength(2));
    await fireEvent.click(screen.getByRole('tab', { name: 'Network' }));
    await waitFor(() => expect(lines(container)).toEqual(['netIn', 'netOut']));
    await rerender({ serverId: 'srv2', serverName: 'db-1', latencyChecks: [] });
    await waitFor(() => expect(lines(container)).toEqual(['cpu', 'ram']));
    expect(screen.queryByRole('tab', { name: 'Network' })).toBeNull();
    expect(screen.getByRole('tab', { name: 'CPU & RAM' }).getAttribute('aria-selected')).toBe(
      'true',
    );
  });
});
