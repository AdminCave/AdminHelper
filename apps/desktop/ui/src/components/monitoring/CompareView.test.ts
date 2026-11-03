// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import type { ServerCompare } from '$lib/api/types';

const mocks = vi.hoisted(() => ({ fetchServerCompare: vi.fn() }));

vi.mock('$lib/api/monitoring', () => ({
  monitoringApi: { fetchServerCompare: mocks.fetchServerCompare },
}));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { sessionStore: writable({ session: { token: 's' }, settings: {} }) };
});
vi.mock('$lib/stores/monitoring', async () => {
  const { readable } = await import('svelte/store');
  return {
    monitoringServers: readable([
      { id: 'a', name: 'alpha', hostname: 'a.example' },
      { id: 'b', name: '', hostname: 'bravo.example' },
      { id: 'c', name: 'charlie', hostname: 'c.example' },
      { id: 'd', name: 'delta', hostname: 'd.example' },
      { id: 'e', name: 'echo', hostname: 'e.example' },
    ]),
  };
});

import { setLanguage } from '$lib/i18n';
import CompareView from './CompareView.svelte';

// jsdom measures 0 px, so the chart draws 800 px wide: a grid of 10 points puts index i at
// clientX 46 + i * 82 (as in TimeChart.test.ts).
const START = 1_700_000_100;
const STEP = 900;
const clientX = (i: number) => 46 + i * 82;
const pts = (vals: (number | null)[]): [number, number | null][] =>
  vals.map((v, i) => [START + i * STEP, v]);
const flat = (v: number | null) => pts(Array<number | null>(10).fill(v));

function compare(over: Partial<ServerCompare> = {}): ServerCompare {
  return {
    metric: 'cpu',
    period: '24h',
    step: STEP,
    start: START,
    end: START + 9 * STEP,
    servers: [
      // Busy early, quiet late: first over the whole period, last in the window 6..9.
      { serverId: 'a', points: pts([90, 90, 90, 90, 90, 90, 10, 10, 10, 10]) },
      { serverId: 'b', points: pts([10, 10, 10, 10, 10, 10, 80, 80, 80, 80]) },
      { serverId: 'c', points: flat(50) },
      { serverId: 'd', points: flat(40) },
      { serverId: 'e', points: flat(20) },
      { serverId: 'ghost', points: flat(null) },
    ],
    ...over,
  };
}

function order(): string[] {
  return screen.getAllByTestId('compare-row').map((r) => r.getAttribute('data-server') ?? '');
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

describe('CompareView', () => {
  it('ranks the servers with data by average and charts the four busiest', async () => {
    mocks.fetchServerCompare.mockResolvedValue(compare());
    const { container } = render(CompareView);
    await waitFor(() => expect(order()).toEqual(['a', 'c', 'd', 'b', 'e']));
    expect(mocks.fetchServerCompare).toHaveBeenCalledWith({ token: 's' }, 'cpu', '24h');
    expect(lines(container)).toEqual(['a', 'c', 'd', 'b']);
    // Names from the server store, the hostname when the name is empty.
    expect(screen.getByRole('button', { name: 'bravo.example' })).toBeTruthy();
    const alpha = screen.getByRole('rowheader', { name: 'alpha' }).closest('tr');
    expect([...(alpha?.querySelectorAll('td') ?? [])].slice(-2).map((c) => c.textContent)).toEqual([
      '58 %',
      '90 %',
    ]);
  });

  it('keeps at most four servers: a fifth replaces the one chosen first', async () => {
    mocks.fetchServerCompare.mockResolvedValue(compare());
    const { container } = render(CompareView);
    await waitFor(() => expect(lines(container)).toEqual(['a', 'c', 'd', 'b']));
    await fireEvent.click(screen.getByRole('checkbox', { name: 'Show echo in the chart' }));
    expect(lines(container)).toEqual(['c', 'd', 'b', 'e']);
    expect(
      (screen.getByRole('checkbox', { name: 'Show alpha in the chart' }) as HTMLInputElement)
        .checked,
    ).toBe(false);
    await fireEvent.click(screen.getByRole('button', { name: 'charlie' }));
    expect(lines(container)).toEqual(['d', 'b', 'e']);
  });

  it('ranks by the zoomed window', async () => {
    mocks.fetchServerCompare.mockResolvedValue(compare());
    render(CompareView);
    await waitFor(() => expect(order()).toEqual(['a', 'c', 'd', 'b', 'e']));
    const chart = screen.getByRole('application');
    await fireEvent.mouseDown(chart, { clientX: clientX(6) });
    await fireEvent.mouseMove(chart, { clientX: clientX(9) });
    await fireEvent.mouseUp(chart);
    expect(order()).toEqual(['b', 'c', 'd', 'e', 'a']);
    await fireEvent.click(screen.getByRole('button', { name: 'Reset zoom' }));
    expect(order()).toEqual(['a', 'c', 'd', 'b', 'e']);
  });

  it('reloads on a metric switch and keeps the choice', async () => {
    mocks.fetchServerCompare.mockResolvedValue(compare());
    const { container } = render(CompareView);
    await waitFor(() => expect(lines(container)).toHaveLength(4));
    await fireEvent.click(screen.getByRole('checkbox', { name: 'Show delta in the chart' }));
    mocks.fetchServerCompare.mockResolvedValue(compare({ metric: 'load' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Load per CPU' }));
    await waitFor(() =>
      expect(mocks.fetchServerCompare).toHaveBeenLastCalledWith({ token: 's' }, 'load', '24h'),
    );
    await waitFor(() => expect(lines(container)).toEqual(['a', 'c', 'b']));
  });

  it('shows the error instead of empty axes', async () => {
    mocks.fetchServerCompare.mockRejectedValue(new Error('502 Bad Gateway'));
    const { container } = render(CompareView);
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('502 Bad Gateway'));
    expect(container.querySelector('[role="application"]')).toBeNull();
  });

  it('says so when no server has agent data', async () => {
    mocks.fetchServerCompare.mockResolvedValue(compare({ servers: [] }));
    render(CompareView);
    await waitFor(() => expect(screen.getByText('No server with agent data yet.')).toBeTruthy());
  });
});
